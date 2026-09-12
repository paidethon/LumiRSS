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

import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any

from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_NAME_LENGTH = 50
_MAX_TAGS_PER_ITEM = 30


class TagInvalid(ValueError):
    """Tag name or binding failed validation."""


class TagNotFound(Exception):
    """No such tag."""


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
        await self._db.execute("DELETE FROM item_tags WHERE tag_id = ?", (tag_id,))
        await self._db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        return True

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
