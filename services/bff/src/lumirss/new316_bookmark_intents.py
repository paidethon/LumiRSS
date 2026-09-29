"""NEW-316 书签意图字段 —— 为什么保存、希望什么时候用，可按意图筛选。

- 意图是用户显式输入的两个自由文本字段（reason / when_to_use，各
  ≤500 字符），与书签 1:1；两个都为空的写入被拒绝（422）——空意图
  不是数据，不该落行；
- 筛选是真实的数据库过滤：``when`` 按保存的用途精确匹配（大小写不
  敏感的文本等值），``q`` 对 reason/when_to_use/标题做子串匹配；
  没写意图的书签在筛选里如实缺席，绝不编造「未分类」桶；
- 引用的书签必须真实存在（404），跨账户引用天然不可见（per-user 库）。
"""

import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_FIELD_CHARS = 500
_LIST_LIMIT = 200


class IntentInvalid(ValueError):
    """意图负载非法（映射 422）。"""


class IntentBookmarkNotFound(Exception):
    """意图引用的书签不存在（404）。"""


def _clean_field(raw: Any, field: str, *, required: bool = False) -> str:
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        raise IntentInvalid(f"{field} 必须是字符串。")
    clean = raw.strip()
    if len(clean) > _MAX_FIELD_CHARS:
        raise IntentInvalid(f"{field} 超过 {_MAX_FIELD_CHARS} 字符上限。")
    if required and not clean:
        raise IntentInvalid(f"{field} 不能为空。")
    return clean


class BookmarkIntentStore:
    """意图字段的 CRUD + 筛选（per-user）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def set_intent(
        self, bookmark_item_uuid: str, reason: Any, when_to_use: Any
    ) -> dict[str, Any]:
        clean_reason = _clean_field(reason, "reason")
        clean_when = _clean_field(when_to_use, "whenToUse")
        if not clean_reason and not clean_when:
            raise IntentInvalid("reason 与 whenToUse 至少填写一项——空意图不落行。")
        await self._db.migrate()
        bookmark = await self._bookmark(bookmark_item_uuid)
        if bookmark is None:
            raise IntentBookmarkNotFound()
        now = utc_now()

        def _tx(conn: Any) -> None:
            existing = conn.execute(
                "SELECT 1 AS ok FROM bookmark_intents WHERE bookmark_item_uuid = ?",
                (bookmark_item_uuid,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO bookmark_intents (bookmark_item_uuid, reason, when_to_use, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (bookmark_item_uuid, clean_reason, clean_when, now, now),
                )
            else:
                conn.execute(
                    "UPDATE bookmark_intents SET reason = ?, when_to_use = ?, updated_at = ?"
                    " WHERE bookmark_item_uuid = ?",
                    (clean_reason, clean_when, now, bookmark_item_uuid),
                )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        result = await self.get_intent(bookmark_item_uuid)
        assert result is not None
        return result

    async def get_intent(self, bookmark_item_uuid: str) -> dict[str, Any] | None:
        await self._db.migrate()
        bookmark = await self._bookmark(bookmark_item_uuid)
        if bookmark is None:
            raise IntentBookmarkNotFound()
        row = await self._db.fetch_one(
            "SELECT reason, when_to_use, created_at, updated_at FROM bookmark_intents"
            " WHERE bookmark_item_uuid = ?",
            (bookmark_item_uuid,),
        )
        if row is None:
            return None
        return self._intent_row(bookmark_item_uuid, bookmark, row)

    async def delete_intent(self, bookmark_item_uuid: str) -> bool:
        await self._db.migrate()
        if await self._bookmark(bookmark_item_uuid) is None:
            raise IntentBookmarkNotFound()
        row = await self._db.fetch_one(
            "SELECT 1 AS ok FROM bookmark_intents WHERE bookmark_item_uuid = ?",
            (bookmark_item_uuid,),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM bookmark_intents WHERE bookmark_item_uuid = ?",
            (bookmark_item_uuid,),
        )
        return True

    async def list_intents(
        self, *, q: str | None = None, when: str | None = None
    ) -> dict[str, Any]:
        """按意图筛选（真实过滤：like 子串 / when 精确等值）。"""
        await self._db.migrate()
        conditions: list[str] = []
        params: list[Any] = []
        if when:
            clean_when = _clean_field(when, "when", required=True)
            conditions.append("LOWER(i.when_to_use) = LOWER(?)")
            params.append(clean_when)
        if q:
            clean_q = _clean_field(q, "q", required=True)
            needle = f"%{clean_q}%"
            conditions.append(
                "(i.reason LIKE ? OR i.when_to_use LIKE ? OR b.title LIKE ?)"
            )
            params.extend([needle, needle, needle])
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await self._db.fetch_all(
            "SELECT b.item_uuid, b.url, b.rss_item_ref, b.title, i.reason, i.when_to_use, i.updated_at"
            " FROM bookmark_intents i JOIN library_bookmarks b"
            " ON b.item_uuid = i.bookmark_item_uuid"
            f"{where} ORDER BY i.updated_at DESC LIMIT ?",
            (*params, _LIST_LIMIT),
        )
        return {
            "items": [
                {
                    "ref": f"library:{row['item_uuid']}",
                    "title": str(row["title"]),
                    "url": str(row["url"]) if row["url"] is not None else None,
                    "reason": str(row["reason"]),
                    "whenToUse": str(row["when_to_use"]),
                    "updatedAt": str(row["updated_at"]),
                }
                for row in rows
            ],
            "total": len(rows),
        }

    async def _bookmark(self, bookmark_item_uuid: str) -> Any:
        return await self._db.fetch_one(
            "SELECT item_uuid, url, title FROM library_bookmarks WHERE item_uuid = ?",
            (bookmark_item_uuid,),
        )

    @staticmethod
    def _intent_row(item_uuid: str, bookmark: Any, row: Any) -> dict[str, Any]:
        return {
            "ref": f"library:{item_uuid}",
            "title": str(bookmark["title"]),
            "url": str(bookmark["url"]) if bookmark["url"] is not None else None,
            "reason": str(row["reason"]),
            "whenToUse": str(row["when_to_use"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }


def new_intent_id() -> str:
    """行主键 = 书签 item_uuid；此工具仅用于测试夹具造 uuid。"""
    return str(_uuid.uuid4())
