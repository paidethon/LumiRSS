"""NEW-209 订阅变动回收箱 —— 退订配置捕获、限期与恢复。

语义边界（模块存在的理由）：

- 捕获发生在退订成功**之后**：箱内存的是**订阅配置**（URL / 标题 /
  分类），恢复 = 按原配置重新订阅。绝不承诺恢复**正文**——退订后
  源站（FreshRSS）已删的条目物理上不可找回，响应以 note 如实声明；
- keep_days 由用户选择（1..365）；``purge_after`` 只是建议清理日，
  本库无调度器：过期行如实标注 ``expired=true`` 并继续等待用户显式
  discard（与全库「无后台清理器」口径一致）；
- restore 产生**新代次**（restored_stream_id 记录新 stream id）：
  退订时已被级联清理的检查侧私有状态（source_refresh_log 等）不会
  复活，用户手工配置（备注/覆盖）按既有跨代语义处理；
- discard / restore 都是 set 语义：只对 kept 行有效，非 kept 行操作
  → 稳定 409（不是幂等 204——状态陈旧如实报告）。
"""

import uuid as _uuid
from datetime import datetime, timedelta
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

KEEP_DAYS_MIN = 1
KEEP_DAYS_MAX = 365
_MAX_ROWS = 200


class BinRowNotFound(Exception):
    """回收箱行不存在 —— 404 bin_row_not_found。"""


class BinRowNotRestorable(Exception):
    """行不是 kept 状态（已恢复/已放弃）—— 409 bin_row_not_restorable。"""


def _iso_plus_days(iso: str, days: int) -> str:
    moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (moment + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_expired(row: dict[str, Any], *, now: str | None = None) -> bool:
    """purge_after 已过（kept 行才有「过期」语义；纯函数可注入）。

    接受 store 行（snake_case）与 API 视图（camelCase）两种键形态。"""
    if row.get("status") != "kept":
        return False
    purge_after = row.get("purge_after", row.get("purgeAfter"))
    assert purge_after is not None
    moment = now or utc_now()
    return str(purge_after) <= moment


def _row_to_view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "feedUrl": str(row["feed_url"]),
        "streamId": str(row["stream_id"]),
        "title": row["title"],
        "categoryId": row["category_id"],
        "categoryLabel": row["category_label"],
        "keepDays": int(row["keep_days"]),
        "unsubscribedAt": str(row["unsubscribed_at"]),
        "purgeAfter": str(row["purge_after"]),
        "status": str(row["status"]),
        "restoredAt": row["restored_at"],
        "restoredStreamId": row["restored_stream_id"],
        "discardedAt": row["discarded_at"],
        "createdAt": str(row["created_at"]),
    }


class UnsubscribeBinStore:
    """SQL 唯一入口；inline literal at each execute site（repo 约定）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def capture(
        self,
        *,
        feed_url: str,
        stream_id: str,
        title: str | None,
        category_id: str | None,
        category_label: str | None,
        keep_days: int,
        unsubscribed_at: str,
    ) -> dict[str, Any]:
        row_id = str(_uuid.uuid4())
        created_at = utc_now()
        purge_after = _iso_plus_days(unsubscribed_at, keep_days)
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO new209_unsubscribe_bin"
            " (id, feed_url, stream_id, title, category_id, category_label,"
            "  keep_days, unsubscribed_at, purge_after, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'kept', ?)",
            (
                row_id,
                feed_url,
                stream_id,
                title,
                category_id,
                category_label,
                int(keep_days),
                unsubscribed_at,
                purge_after,
                created_at,
            ),
        )
        return {
            "id": row_id,
            "feedUrl": feed_url,
            "streamId": stream_id,
            "title": title,
            "categoryId": category_id,
            "categoryLabel": category_label,
            "keepDays": keep_days,
            "unsubscribedAt": unsubscribed_at,
            "purgeAfter": purge_after,
            "status": "kept",
            "restoredAt": None,
            "restoredStreamId": None,
            "discardedAt": None,
            "createdAt": created_at,
        }

    async def list_rows(self, *, include_discarded: bool = False) -> list[dict[str, Any]]:
        await self._db.migrate()
        if include_discarded:
            rows = await self._db.fetch_all(
                "SELECT * FROM new209_unsubscribe_bin"
                " ORDER BY unsubscribed_at DESC, id DESC LIMIT ?",
                (_MAX_ROWS,),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT * FROM new209_unsubscribe_bin WHERE status != 'discarded'"
                " ORDER BY unsubscribed_at DESC, id DESC LIMIT ?",
                (_MAX_ROWS,),
            )
        return [_row_to_view(row) for row in rows]

    async def get(self, row_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM new209_unsubscribe_bin WHERE id = ?", (row_id,)
        )
        return _row_to_view(row) if row is not None else None

    async def mark_restored(self, row_id: str, restored_stream_id: str) -> dict[str, Any]:
        await self._require_kept(row_id)
        await self._db.execute(
            "UPDATE new209_unsubscribe_bin SET status = 'restored',"
            " restored_at = ?, restored_stream_id = ? WHERE id = ?",
            (utc_now(), restored_stream_id, row_id),
        )
        return await self._require_kept_successor(row_id)

    async def mark_discarded(self, row_id: str) -> dict[str, Any]:
        await self._require_kept(row_id)
        await self._db.execute(
            "UPDATE new209_unsubscribe_bin SET status = 'discarded',"
            " discarded_at = ? WHERE id = ?",
            (utc_now(), row_id),
        )
        updated = await self.get(row_id)
        assert updated is not None
        return updated

    async def _require_kept(self, row_id: str) -> dict[str, Any]:
        row = await self.get(row_id)
        if row is None:
            raise BinRowNotFound(row_id)
        if row["status"] != "kept":
            raise BinRowNotRestorable(row_id)
        return row

    async def _require_kept_successor(self, row_id: str) -> dict[str, Any]:
        updated = await self.get(row_id)
        assert updated is not None
        return updated
