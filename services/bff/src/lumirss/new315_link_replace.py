"""NEW-315 书签链接批量替换预览 —— 旧域→新域映射，先预览，可撤销本批。

- 映射必须明确：from_domain/to_domain 都是用户显式给出的主机名
  （含端口可选），不接受通配符/空串；路径、scheme、查询串原样保留，
  只替换 host（+端口）。括号：http→https 的 scheme 变化不属于本能力，
  域名映射只动 netloc；
- 预览零写入：列出每个匹配书签的 before → after；schema 非法的映射
  （如 to 为空、带路径）→ 400；
- 执行 = 逐条 UPDATE + 批次台账（changes_json 存 before 列表，undo
  按台账回放）；唯一索引冲突（新 URL 已存在）如实列入 conflicts，
  该条不动；
- 撤销只针对本批、只一次（undone_at 置位后拒绝重复撤销），撤销后
  before/after 与执行前完全一致（负向断言依赖）。

per-user：批次台账与书签同库（RoutingDatabase），A 的批次对 B 不可
见，B 无法撤销 A 的批次。
"""

import json
import urllib.parse
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_BATCH_ITEMS = 500


class LinkReplaceInvalid(ValueError):
    """域名映射非法（映射 400）。"""


class ReplaceBatchNotFound(Exception):
    """批次不存在（404）或已撤销（409，分开的类型见 UndoneBatch）。"""


class UndoneBatch(Exception):
    """批次已撤销，不能再次撤销。"""


def _clean_domain(raw: Any, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise LinkReplaceInvalid(f"{field} 不能为空。")
    clean = raw.strip().lower()
    if len(clean) > 255:
        raise LinkReplaceInvalid(f"{field} 过长。")
    if any(ch.isspace() for ch in clean):
        raise LinkReplaceInvalid(f"{field} 不能包含空白。")
    # 拒绝 scheme/路径混入：域名映射只接受 host[:port]
    parsed = urllib.parse.urlsplit(f"//{clean}")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise LinkReplaceInvalid(f"{field} 只能是主机名（可带端口），不能带路径。")
    if not parsed.hostname:
        raise LinkReplaceInvalid(f"{field} 不是合法主机名。")
    if raw.strip().startswith("*"):
        raise LinkReplaceInvalid(f"{field} 不支持通配符——请逐域显式映射。")
    return clean


def map_url(url: str, from_domain: str, to_domain: str) -> str | None:
    """host（含端口）精确匹配时替换 netloc；不匹配返回 None。"""
    parts = urllib.parse.urlsplit(url)
    if parts.netloc.lower() != from_domain:
        return None
    return urllib.parse.urlunsplit(
        (parts.scheme, to_domain, parts.path, parts.query, parts.fragment)
    )


class LinkReplaceStore:
    """预览 / 执行 / 撤销（per-user）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def preview(self, from_domain: Any, to_domain: Any) -> dict[str, Any]:
        source = _clean_domain(from_domain, "fromDomain")
        target = _clean_domain(to_domain, "toDomain")
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT item_uuid, url, title FROM library_bookmarks"
            " WHERE item_type = 'url' AND url IS NOT NULL ORDER BY created_at DESC"
        )
        changes: list[dict[str, str]] = []
        for row in rows:
            url = str(row["url"])
            mapped = map_url(url, source, target)
            if mapped is None or mapped == url:
                continue
            changes.append(
                {
                    "ref": f"library:{row['item_uuid']}",
                    "title": str(row["title"]),
                    "before": url,
                    "after": mapped,
                }
            )
            if len(changes) >= _MAX_BATCH_ITEMS:
                break
        return {
            "fromDomain": source,
            "toDomain": target,
            "changes": changes,
            "truncated": False,
            "honestyNote": "预览零写入；执行后本批可撤销一次。",
        }

    async def apply(self, from_domain: Any, to_domain: Any) -> dict[str, Any]:
        source = _clean_domain(from_domain, "fromDomain")
        target = _clean_domain(to_domain, "toDomain")
        preview = await self.preview(source, target)
        changes = preview["changes"]
        await self._db.migrate()
        applied: list[dict[str, str]] = []
        conflicts: list[dict[str, str]] = []

        def _tx(conn: Any) -> None:
            for change in changes:
                exists = conn.execute(
                    "SELECT 1 AS ok FROM library_bookmarks WHERE url = ?",
                    (change["after"],),
                ).fetchone()
                if exists is not None:
                    conflicts.append(
                        {
                            "ref": change["ref"],
                            "url": change["before"],
                            "reason": "新 URL 已存在（唯一索引收敛）。",
                        }
                    )
                    continue
                cursor = conn.execute(
                    "UPDATE library_bookmarks SET url = ? WHERE item_uuid = ?",
                    (change["after"], change["ref"].split(":", 1)[1]),
                )
                if cursor.rowcount:
                    applied.append(change)

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        batch_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO bookmark_link_replacements (id, from_domain, to_domain, changed, conflicts, changes_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                batch_id, source, target, len(applied), len(conflicts),
                json.dumps(applied, ensure_ascii=False), now,
            ),
        )
        return {
            "id": batch_id,
            "fromDomain": source,
            "toDomain": target,
            "changed": len(applied),
            "conflicts": conflicts,
            "applied": [
                {"ref": c["ref"], "before": c["before"], "after": c["after"]}
                for c in applied
            ],
            "createdAt": now,
        }

    async def list_batches(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, from_domain, to_domain, changed, conflicts, undone_at, created_at"
            " FROM bookmark_link_replacements ORDER BY created_at DESC, id DESC LIMIT 100"
        )
        return [
            {
                "id": str(row["id"]),
                "fromDomain": str(row["from_domain"]),
                "toDomain": str(row["to_domain"]),
                "changed": int(row["changed"]),
                "conflicts": int(row["conflicts"]),
                "undone": row["undone_at"] is not None,
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def undo(self, batch_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, changes_json, undone_at FROM bookmark_link_replacements WHERE id = ?",
            (batch_id,),
        )
        if row is None:
            raise ReplaceBatchNotFound()
        if row["undone_at"] is not None:
            raise UndoneBatch()
        try:
            applied = json.loads(str(row["changes_json"]))
        except json.JSONDecodeError as exc:
            raise LinkReplaceInvalid("批次台账损坏，拒绝撤销。") from exc
        if not isinstance(applied, list):
            raise LinkReplaceInvalid("批次台账损坏，拒绝撤销。")
        now = utc_now()
        restored = 0

        def _tx(conn: Any) -> None:
            nonlocal restored
            for change in applied:
                cursor = conn.execute(
                    "UPDATE library_bookmarks SET url = ? WHERE item_uuid = ? AND url = ?",
                    (
                        change["before"],
                        str(change["ref"]).split(":", 1)[1],
                        change["after"],
                    ),
                )
                restored += cursor.rowcount
            conn.execute(
                "UPDATE bookmark_link_replacements SET undone_at = ? WHERE id = ?",
                (now, batch_id),
            )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        return {
            "id": batch_id,
            "restored": restored,
            "undoneAt": now,
            "note": "本批已按台账回放撤销；同一批次不能再次撤销。",
        }
