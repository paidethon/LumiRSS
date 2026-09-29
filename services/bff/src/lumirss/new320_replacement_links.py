"""NEW-320 书签失效替代关联 —— 指定可信新来源，保留旧链接与理由。

- 替代（POST）：针对一个已有书签记录「新 URL + 为什么换」；旧书签
  及其 URL 一字不动（保留旧链接是硬要求，负向断言依赖）；新 URL 走
  与书签创建同一校验（http/https、长度、无空白）；
- 历史保留：同一书签可多次替代，全部可查；「当前生效」= 最新一条，
  查询响应里以 current 标注，绝不悄悄覆盖旧记录；
- 引用者视角：按旧 ref 查 → 完整变更史（旧 URL、每次替代的新 URL
  与理由、时间），变更对引用者可见；
- per-user：A 的替代关联对 B 完全不可见（B 查询 → 404）。
"""

import uuid as _uuid
from typing import Any

from lumirss.library import _validate_bookmark_url
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_REASON_CHARS = 1000
_LIST_LIMIT = 100


class ReplacementInvalid(ValueError):
    """替代负载非法（映射 422）。"""


class ReplacementBookmarkNotFound(Exception):
    """书签不存在（404）。"""


class ReplacementLinkNotFound(Exception):
    """该书签没有替代关联（404）。"""


class BookmarkReplacementStore:
    """替代关联（per-user，只追加）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def add_replacement(
        self, bookmark_item_uuid: str, new_url: Any, reason: Any
    ) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason.strip():
            raise ReplacementInvalid("替换理由不能为空——变更必须可追溯。")
        clean_reason = reason.strip()
        if len(clean_reason) > _MAX_REASON_CHARS:
            raise ReplacementInvalid(
                f"替换理由超过 {_MAX_REASON_CHARS} 字符上限。"
            )
        try:
            clean_url = _validate_bookmark_url(new_url)
        except Exception as exc:
            raise ReplacementInvalid("新来源 URL 必须是 http(s) 地址。") from exc
        await self._db.migrate()
        bookmark = await self._bookmark(bookmark_item_uuid)
        if bookmark is None:
            raise ReplacementBookmarkNotFound()
        replacement_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO bookmark_replacement_links (id, bookmark_item_uuid, new_url, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (replacement_id, bookmark_item_uuid, clean_url, clean_reason, now),
        )
        return {
            "id": replacement_id,
            "ref": f"library:{bookmark_item_uuid}",
            "oldUrl": str(bookmark["url"]) if bookmark["url"] is not None else None,
            "newUrl": clean_url,
            "reason": clean_reason,
            "createdAt": now,
            "current": True,
        }

    async def list_replacements(
        self, bookmark_item_uuid: str
    ) -> dict[str, Any]:
        """引用者视角：旧链接 + 完整变更史（最新一条标 current）。"""
        await self._db.migrate()
        bookmark = await self._bookmark(bookmark_item_uuid)
        if bookmark is None:
            raise ReplacementBookmarkNotFound()
        # rowid 单调：同秒多次替代时按真实插入序取「最新」（同秒决胜）。
        rows = await self._db.fetch_all(
            "SELECT id, new_url, reason, created_at FROM bookmark_replacement_links"
            " WHERE bookmark_item_uuid = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (bookmark_item_uuid, _LIST_LIMIT),
        )
        if not rows:
            raise ReplacementLinkNotFound()
        history = [
            {
                "id": str(row["id"]),
                "newUrl": str(row["new_url"]),
                "reason": str(row["reason"]),
                "createdAt": str(row["created_at"]),
                "current": index == 0,
            }
            for index, row in enumerate(rows)
        ]
        return {
            "ref": f"library:{bookmark_item_uuid}",
            "title": str(bookmark["title"]),
            "oldUrl": str(bookmark["url"]) if bookmark["url"] is not None else None,
            "oldLinkPreserved": True,
            "current": history[0],
            "history": history,
        }

    async def _bookmark(self, bookmark_item_uuid: str) -> Any:
        return await self._db.fetch_one(
            "SELECT item_uuid, url, title FROM library_bookmarks WHERE item_uuid = ?",
            (bookmark_item_uuid,),
        )
