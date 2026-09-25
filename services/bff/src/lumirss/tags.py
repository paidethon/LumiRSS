"""Unified tag model (phase2 G8).

One schema for both domains: tags attach to typed ItemRefs only
(``rss:…`` / ``library:…``). Names are NFC-normalized, stripped of a
leading ``#``, length-capped, and unique case-insensitively for ASCII
(NOCASE unique index, migration 0017; the first-created form is kept).
AI suggestions attach as ``status='suggested'`` and are invisible to
listing/filtering until explicitly accepted; acceptance upgrades the
SAME row (origin→manual, status→active) — suggestions never pollute
the active tag space. Attach validates the binding is new before the
per-item cap applies (idempotent re-attach always succeeds).
"""

import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_NAME_LENGTH = 50
_MAX_TAGS_PER_ITEM = 30
# N150：合并撤销窗口（TTL）。
_UNDO_TTL = 24 * 3600


class TagInvalid(ValueError):
    """Tag name or binding failed validation."""


class TagNotFound(Exception):
    """No such tag."""


class TagMergeUndoNotFound(Exception):
    """N150：没有可撤销的合并（无快照或已超 24h 窗口）→ 404。"""


class TagMergeSourceRecreated(Exception):
    """N150：源标签名已被占用（含上一次 undo 自身重建）→ 409。"""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


@dataclass(frozen=True)
class TagRecord:
    id: int
    name: str
    count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "count": self.count}


def normalize_tag_name(raw: str) -> str:
    if not isinstance(raw, str):
        raise TagInvalid("标签名必须是字符串。")
    clean = unicodedata.normalize("NFC", raw).strip().lstrip("#").strip()
    if not clean:
        raise TagInvalid("标签名不能为空。")
    if len(clean) > _MAX_NAME_LENGTH:
        raise TagInvalid("标签名过长。")
    return clean


class TagStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_tags(self, *, q: str | None = None) -> list[TagRecord]:
        """Active tags with usage counts; suggested rows are invisible."""
        await self._db.migrate()
        like = (
            f"%{_escape_like(unicodedata.normalize('NFC', q.strip()))}%"
            if q and q.strip()
            else None
        )
        rows = await self._db.fetch_all(
            "SELECT t.id, t.name, COUNT(CASE WHEN it.status = 'active' THEN 1 END) AS n FROM tags t LEFT JOIN item_tags it ON it.tag_id = t.id WHERE (? IS NULL OR t.name LIKE ? ESCAPE '\\') AND (NOT EXISTS (SELECT 1 FROM item_tags s WHERE s.tag_id = t.id) OR EXISTS (SELECT 1 FROM item_tags a WHERE a.tag_id = t.id AND a.status = 'active')) GROUP BY t.id, t.name ORDER BY n DESC, t.name ASC",
            (like, like),
        )
        return [
            TagRecord(id=int(r["id"]), name=str(r["name"]), count=int(r["n"]))
            for r in rows
        ]

    async def rename(self, tag_id: int, new_name: str) -> TagRecord:
        clean = normalize_tag_name(new_name)
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM tags WHERE id = ?", (tag_id,))
        if row is None:
            raise TagNotFound(str(tag_id))
        dupe = await self._db.fetch_one(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE AND id != ?",
            (clean, tag_id),
        )
        if dupe is not None:
            raise TagInvalid("同名标签已存在。")
        await self._db.execute("UPDATE tags SET name = ? WHERE id = ?", (clean, tag_id))
        return TagRecord(id=tag_id, name=clean)

    async def delete(self, tag_id: int) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM tags WHERE id = ?", (tag_id,))
        if row is None:
            return False
        # Pool #45: membership + tag rows die atomically — a crash between
        # two autocommit deletes used to leave orphaned item_tags rows.
        def _delete_tag(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM item_tags WHERE tag_id = ?", (tag_id,))
            conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))

        await transaction(self._db, _delete_tag)
        return True

    async def merge_preview(
        self, source_tag_id: int, target_tag_id: int
    ) -> dict[str, Any]:
        """Affected-count preview for a merge (pool #16): how many source
        bindings move to the target and how many are exact duplicates
        that collapse away. Read-only."""
        if source_tag_id == target_tag_id:
            raise TagInvalid("源标签与目标标签相同。")
        await self._db.migrate()
        if await self._db.fetch_one("SELECT id FROM tags WHERE id = ?", (source_tag_id,)) is None:
            raise TagNotFound(str(source_tag_id))
        if await self._db.fetch_one("SELECT id FROM tags WHERE id = ?", (target_tag_id,)) is None:
            raise TagNotFound(str(target_tag_id))
        bindings = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM item_tags WHERE tag_id = ?",
            (source_tag_id,),
        )
        overlaps = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM item_tags a WHERE a.tag_id = ? AND EXISTS (SELECT 1 FROM item_tags b WHERE b.item_ref = a.item_ref AND b.tag_id = ?)",
            (source_tag_id, target_tag_id),
        )
        source_bindings = int(bindings["n"]) if bindings is not None else 0
        overlap = int(overlaps["n"]) if overlaps is not None else 0
        return {
            "sourceTagId": source_tag_id,
            "targetTagId": target_tag_id,
            "bindings": source_bindings,
            "overlaps": overlap,
            "willMove": source_bindings - overlap,
        }

    async def merge(self, source_tag_id: int, target_tag_id: int) -> dict[str, Any]:
        """Merge source INTO target atomically (pool #16): exact-duplicate
        bindings collapse, the rest re-point to the target, the source
        tag row is removed. One transaction — no half-merged state.
        Touches Lumi-owned item_tags/tags only; FreshRSS categories are
        never involved.

        N150：同一事务内先快照源标签绑定到 tag_merge_undo（单例行，新
        合并覆盖旧快照），崩溃/中止都不会留下「无快照的合并」。"""
        await self.merge_preview(source_tag_id, target_tag_id)  # shared validation

        def _merge(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            # N150：先在写锁内快照（dedupe/移动删除发生之前）。
            source_name_row = conn.execute(
                "SELECT name FROM tags WHERE id = ?", (source_tag_id,)
            ).fetchone()
            rows = conn.execute(
                "SELECT item_ref, origin, status, created_at FROM item_tags WHERE tag_id = ?",
                (source_tag_id,),
            ).fetchall()
            bindings = [
                {
                    "itemRef": str(row["item_ref"]),
                    "origin": str(row["origin"]),
                    "status": str(row["status"]),
                    "createdAt": str(row["created_at"]),
                }
                for row in rows
            ]
            conn.execute("DELETE FROM tag_merge_undo WHERE id = 1")
            conn.execute(
                "INSERT INTO tag_merge_undo (id, source_tag_id, source_tag_name, target_tag_id, bindings_json, created_at)"
                " VALUES (1, ?, ?, ?, ?, ?)",
                (
                    source_tag_id,
                    str(source_name_row["name"]) if source_name_row is not None else "",
                    target_tag_id,
                    json.dumps(bindings, ensure_ascii=False),
                    utc_now(),
                ),
            )
            deduped_cur = conn.execute(
                "DELETE FROM item_tags WHERE tag_id = ? AND item_ref IN (SELECT item_ref FROM item_tags WHERE tag_id = ?)",
                (source_tag_id, target_tag_id),
            )
            deduped = deduped_cur.rowcount if deduped_cur.rowcount and deduped_cur.rowcount > 0 else 0
            cur = conn.execute(
                "UPDATE item_tags SET tag_id = ? WHERE tag_id = ?",
                (target_tag_id, source_tag_id),
            )
            moved = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            conn.execute("DELETE FROM tags WHERE id = ?", (source_tag_id,))
            return {
                "targetTagId": target_tag_id,
                "movedBindings": moved,
                "dedupedBindings": deduped,
            }

        return await transaction(self._db, _merge)

    # -- N150：标签合并撤销 ---------------------------------------------------

    async def undo_merge(self) -> dict[str, Any]:
        """撤销最近一次合并（24h 窗口内）：重建源标签并原样恢复其绑定
        （含被折叠的重复绑定——目标保留合并来的绑定，两侧语义都与合并
        前一致）。单行快照在成功后保留：再次 undo 必须以 409 失败（源
        标签名已被上一次 undo 占用），绝不二次恢复；无快照或超 TTL →
        404。恢复动作单事务完成。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT source_tag_name, target_tag_id, bindings_json, created_at FROM tag_merge_undo WHERE id = 1",
            (),
        )
        if row is None:
            raise TagMergeUndoNotFound("没有可撤销的标签合并。")
        try:
            created_at = datetime.fromisoformat(str(row["created_at"]))
        except ValueError as exc:
            raise TagMergeUndoNotFound("合并快照时间戳无效。") from exc
        elapsed = datetime.now(UTC) - created_at
        if elapsed.total_seconds() > _UNDO_TTL:
            # TTL 过期：快照失效（清除后按 404 诚实上报）。
            await self._db.execute("DELETE FROM tag_merge_undo WHERE id = 1", ())
            raise TagMergeUndoNotFound("合并撤销窗口（24 小时）已过期。")
        name = normalize_tag_name(str(row["source_tag_name"]))
        target_tag_id = int(row["target_tag_id"])
        try:
            bindings = json.loads(str(row["bindings_json"]))
        except ValueError as exc:
            raise TagMergeUndoNotFound("合并快照数据损坏。") from exc
        if not isinstance(bindings, list):
            raise TagMergeUndoNotFound("合并快照数据损坏。")

        # 与「撤销后源标签已存在」同源冲突：合并后有人重建了同名标签 →
        # 409（含上一次 undo 的重建）。
        existing = await self._db.fetch_one(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)
        )
        if existing is not None:
            raise TagMergeSourceRecreated(name)

        def _undo(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            new_source_id = int(cur.lastrowid)
            restored = 0
            for binding in bindings:
                if not isinstance(binding, dict):
                    continue
                item_ref = str(binding.get("itemRef") or "")
                origin = str(binding.get("origin") or "manual")
                status = str(binding.get("status") or "active")
                created = str(binding.get("createdAt") or utc_now())
                if not item_ref or origin not in ("manual", "source", "ai"):
                    continue
                conn.execute(
                    "INSERT INTO item_tags (item_ref, tag_id, origin, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    (item_ref, new_source_id, origin, status, created),
                )
                restored += 1
            return {
                "sourceTagId": new_source_id,
                "name": name,
                "targetTagId": target_tag_id,
                "restoredBindings": restored,
            }

        return await transaction(self._db, _undo)

    async def attach(
        self,
        item_ref: str,
        name: str,
        *,
        origin: str = "manual",
        status: str = "active",
    ) -> dict[str, Any]:
        """Idempotent attach; returns the binding's effective state.

        Order matters (P0-10g): an already-bound tag returns as-is even
        when the item is at the per-item cap — only NEW bindings count
        against it. Name lookup is case-insensitive (NOCASE index,
        migration 0017); the stored form stays the first-created one.
        """
        parsed = parse_item_ref(item_ref)
        clean = normalize_tag_name(name)
        if origin not in ("manual", "source", "ai"):
            raise TagInvalid("非法标签来源。")
        await self._db.migrate()
        tag_row = await self._db.fetch_one(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (clean,)
        )
        if tag_row is None:
            try:
                await self._db.execute(
                    "INSERT INTO tags (name) VALUES (?)",
                    (clean,),
                )
            except sqlite3.IntegrityError as exc:
                raise TagInvalid("标签创建冲突。") from exc
            tag_row = await self._db.fetch_one(
                "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (clean,)
            )
        tag_id = int(tag_row["id"])
        existing = await self._db.fetch_one(
            "SELECT origin, status FROM item_tags WHERE item_ref = ? AND tag_id = ? AND origin = ?",
            (parsed.format(), tag_id, origin),
        )
        if existing is not None:
            return {
                "tagId": tag_id,
                "name": clean,
                "ref": parsed.format(),
                "origin": str(existing["origin"]),
                "status": str(existing["status"]),
            }
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM item_tags WHERE item_ref = ?",
            (parsed.format(),),
        )
        if int(count_row["n"]) >= _MAX_TAGS_PER_ITEM:
            raise TagInvalid("该条目标签数量已达上限。")
        try:
            await self._db.execute(
                "INSERT INTO item_tags (item_ref, tag_id, origin, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (parsed.format(), tag_id, origin, status, utc_now()),
            )
        except sqlite3.IntegrityError as exc:
            raise TagInvalid("标签绑定冲突。") from exc
        return {
            "tagId": tag_id,
            "name": clean,
            "ref": parsed.format(),
            "origin": origin,
            "status": status,
        }

    async def detach(self, item_ref: str, name: str, *, origin: str = "manual") -> bool:
        parsed = parse_item_ref(item_ref)
        clean = normalize_tag_name(name)
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (clean,)
        )
        if row is None:
            return False
        before = await self._db.fetch_one(
            "SELECT rowid FROM item_tags WHERE item_ref = ? AND tag_id = ? AND origin = ?",
            (parsed.format(), int(row["id"]), origin),
        )
        if before is None:
            return False
        await self._db.execute(
            "DELETE FROM item_tags WHERE item_ref = ? AND tag_id = ? AND origin = ?",
            (parsed.format(), int(row["id"]), origin),
        )
        return True

    async def accept_suggestion(self, item_ref: str, name: str) -> dict[str, Any]:
        """Adopt one AI suggestion: upgrade the SAME row to manual/active."""
        parsed = parse_item_ref(item_ref)
        clean = normalize_tag_name(name)
        await self._db.migrate()
        tag_row = await self._db.fetch_one(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (clean,)
        )
        if tag_row is None:
            raise TagNotFound(clean)
        row = await self._db.fetch_one(
            "SELECT rowid FROM item_tags WHERE item_ref = ? AND tag_id = ? AND origin = 'ai' AND status = 'suggested'",
            (parsed.format(), int(tag_row["id"])),
        )
        if row is None:
            raise TagNotFound(clean)
        await self._db.execute(
            "UPDATE item_tags SET origin = 'manual', status = 'active' WHERE rowid = ?",
            (int(row["rowid"]),),
        )
        return {"ref": parsed.format(), "name": clean, "status": "active"}

    async def item_refs_for_tag(self, tag_id: int, *, limit: int = 100) -> list[str]:
        """Item refs bound to one tag (active bindings, newest first)."""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT item_ref FROM item_tags WHERE tag_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT ?",
            (int(tag_id), max(1, min(limit, 200))),
        )
        return [str(row["item_ref"]) for row in rows]

    async def tags_for_item(
        self, item_ref: str, *, include_suggested: bool = False
    ) -> list[dict[str, Any]]:
        parsed = parse_item_ref(item_ref)
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT t.id, t.name, it.origin, it.status FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE it.item_ref = ? ORDER BY t.name ASC",
            (parsed.format(),),
        )
        result = []
        for row in rows:
            status = str(row["status"])
            if status == "suggested" and not include_suggested:
                continue
            result.append(
                {
                    "tagId": int(row["id"]),
                    "name": str(row["name"]),
                    "origin": str(row["origin"]),
                    "status": status,
                }
            )
        return result


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
