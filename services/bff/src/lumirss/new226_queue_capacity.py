"""NEW-226 队列容量上限 —— 用户给今日队列设容量，满时新候选进待确认区。

与 N041 队列的关系：容量是「加入意愿」的守门，不是新队列——

- ``offer``：想加入时的唯一入口。容量未满 / 未启用 → 直接走既有
  ReadingQueueStore.add_item（语义原样：created/duplicate/resurrected）；
  已满 → 候选落 ``queue_overflow_candidates``（pending_choice），**绝不
  自动顶掉任何行**；
- 裁决：``replace``（用户指定被替换的队列行 → 移除该行 + 加入候选）
  或 ``dismiss``（暂不加入）。两者都是显式用户动作；
- today queue 的行数沿用 reading_queue 口径（status != 'removed'）。
"""

import uuid
from typing import Any

from lumirss.reading_queue import (
    QueueInvalid,
    QueueItemDone,
    QueueItemNotFound,
    ReadingQueueStore,
)
from lumirss.storage import Database
from lumirss.util import utc_now

_MIN_CAPACITY = 1
_MAX_CAPACITY = 100
_MAX_PENDING_CHOICES = 50


class CapacityInvalid(Exception):
    """容量/载荷非法——422 invalid_queue_capacity。"""


class CapacityCandidateNotFound(Exception):
    """待确认候选不存在（或已裁决）——404 queue_capacity_candidate_not_found。"""


def validate_item_ref(item_ref: str) -> str:
    from lumirss.itemref import InvalidItemRef, parse_item_ref

    try:
        parse_item_ref(item_ref)
    except InvalidItemRef as exc:
        raise CapacityInvalid(f"itemRef 不合法：{exc}") from exc
    return item_ref


class QueueCapacityStore:
    """Persistence for queue_capacity_settings / queue_overflow_candidates."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._queue = ReadingQueueStore(db)

    # -- settings ----------------------------------------------------------------

    async def get_settings(self) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT capacity, enabled, updated_at FROM queue_capacity_settings"
            " WHERE id = 1"
        )
        if row is None:
            return {
                "capacity": None,
                "enabled": False,
                "updatedAt": None,
                "note": "未设置容量上限；设置后满员时新候选会进待确认区。",
            }
        return {
            "capacity": int(row["capacity"]),
            "enabled": bool(row["enabled"]),
            "updatedAt": str(row["updated_at"]),
            "note": None,
        }

    async def set_settings(self, capacity: int, enabled: bool) -> dict[str, Any]:
        await self._db.migrate()
        if not isinstance(capacity, int) or isinstance(capacity, bool):
            raise CapacityInvalid("capacity 必须是整数。")
        if not _MIN_CAPACITY <= capacity <= _MAX_CAPACITY:
            raise CapacityInvalid(
                f"capacity 必须在 {_MIN_CAPACITY}..{_MAX_CAPACITY} 之间。"
            )
        await self._db.execute(
            "INSERT INTO queue_capacity_settings (id, capacity, enabled, updated_at)"
            " VALUES (1, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET capacity = excluded.capacity,"
            " enabled = excluded.enabled, updated_at = excluded.updated_at",
            (capacity, 1 if enabled else 0, utc_now()),
        )
        return await self.get_settings()

    async def _queue_count(self, day: str) -> int:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM reading_queue WHERE queue_date = ?"
            " AND status != 'removed'",
            (day,),
        )
        return int(row["n"]) if row is not None else 0

    # -- offer（加入的唯一守门入口） ----------------------------------------------

    async def offer(self, item_ref: str, segment: str | None = None) -> dict[str, Any]:
        """想加入今日队列：未满（或未启用）→ 正常加入；已满 → 候选进
        待确认区（pending_choice），返回 outcome=overflow。"""
        await self._db.migrate()
        validate_item_ref(item_ref)
        settings = await self.get_settings()
        day = utc_now()[:10]
        queue_count = await self._queue_count(day)
        if settings["enabled"] and queue_count >= settings["capacity"]:
            existing = await self._db.fetch_one(
                "SELECT id FROM queue_overflow_candidates"
                " WHERE item_ref = ? AND status = 'pending_choice'",
                (item_ref,),
            )
            if existing is not None:
                row = await self._candidate_row(str(existing["id"]))
                return {**row, "outcome": "already_pending"}
            count = await self._db.fetch_one(
                "SELECT COUNT(*) AS n FROM queue_overflow_candidates"
                " WHERE status = 'pending_choice'"
            )
            if count is not None and int(count["n"]) >= _MAX_PENDING_CHOICES:
                raise CapacityInvalid(
                    f"待确认区已满（{_MAX_PENDING_CHOICES}）：请先裁决已有候选。"
                )
            candidate_id = f"qcap-{uuid.uuid4().hex}"
            await self._db.execute(
                "INSERT INTO queue_overflow_candidates (id, item_ref, queue_date,"
                " created_at, status) VALUES (?, ?, ?, ?, 'pending_choice')",
                (candidate_id, item_ref, day, utc_now()),
            )
            row = await self._candidate_row(candidate_id)
            return {
                **row,
                "outcome": "overflow",
                "capacity": settings["capacity"],
                "note": "队列已满：候选进入待确认区，替换或暂不加入由你决定。",
            }
        try:
            row, outcome = await self._queue.add_item(item_ref, segment)
        except (QueueInvalid, QueueItemDone, QueueItemNotFound):
            raise
        return {**row, "outcome": outcome}

    async def _candidate_row(self, candidate_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT c.id, c.item_ref, c.queue_date, c.created_at, c.status,"
            " c.resolved_at, c.resolved_action, se.title AS projection_title"
            " FROM queue_overflow_candidates c"
            " LEFT JOIN search_entries se ON se.entry_ref = substr(c.item_ref, 5)"
            " WHERE c.id = ?",
            (candidate_id,),
        )
        if row is None:
            raise CapacityCandidateNotFound(candidate_id)
        return {
            "id": str(row["id"]),
            "itemRef": str(row["item_ref"]),
            "queueDate": str(row["queue_date"]),
            "createdAt": str(row["created_at"]),
            "status": str(row["status"]),
            "resolvedAt": row["resolved_at"],
            "resolvedAction": row["resolved_action"],
            "title": row["projection_title"],
        }

    # -- 待确认区 ------------------------------------------------------------------

    async def list_pending(self) -> dict[str, Any]:
        await self._db.migrate()
        settings = await self.get_settings()
        day = utc_now()[:10]
        rows = await self._db.fetch_all(
            "SELECT c.id, c.item_ref, c.queue_date, c.created_at, c.status,"
            " c.resolved_at, c.resolved_action, se.title AS projection_title"
            " FROM queue_overflow_candidates c"
            " LEFT JOIN search_entries se ON se.entry_ref = substr(c.item_ref, 5)"
            " WHERE c.status = 'pending_choice'"
            " ORDER BY c.created_at ASC, c.rowid ASC"
        )
        return {
            "capacity": settings["capacity"],
            "enabled": settings["enabled"],
            "queueCount": await self._queue_count(day),
            "items": [
                {
                    "id": str(row["id"]),
                    "itemRef": str(row["item_ref"]),
                    "queueDate": str(row["queue_date"]),
                    "createdAt": str(row["created_at"]),
                    "status": str(row["status"]),
                    "title": row["projection_title"],
                }
                for row in rows
            ],
        }

    async def resolve_replace(self, candidate_id: str, replaced_item_id: str) -> dict[str, Any]:
        """裁决「替换」：移除用户指定的队列行，加入候选；候选标记
        replaced_in（裁决记账，绝不复活）。"""
        await self._db.migrate()
        candidate = await self._candidate_row(candidate_id)
        if candidate["status"] != "pending_choice":
            raise CapacityCandidateNotFound(candidate_id)
        await self._queue.remove_item(replaced_item_id)  # 404 if gone
        row, outcome = await self._queue.add_item(candidate["itemRef"])
        await self._db.execute(
            "UPDATE queue_overflow_candidates SET status = 'replaced_in',"
            " resolved_at = ?, resolved_action = ? WHERE id = ?",
            (utc_now(), f"replace:{replaced_item_id}", candidate_id),
        )
        return {
            "candidate": {**candidate, "status": "replaced_in"},
            "addedItem": row,
            "addedOutcome": outcome,
            "removedItemId": replaced_item_id,
        }

    async def resolve_dismiss(self, candidate_id: str) -> dict[str, Any]:
        """裁决「暂不加入」（幂等：已裁决 → 404，不留歧义）。"""
        await self._db.migrate()
        candidate = await self._candidate_row(candidate_id)
        if candidate["status"] != "pending_choice":
            raise CapacityCandidateNotFound(candidate_id)
        await self._db.execute(
            "UPDATE queue_overflow_candidates SET status = 'dismissed',"
            " resolved_at = ?, resolved_action = 'dismiss' WHERE id = ?",
            (utc_now(), candidate_id),
        )
        return {**candidate, "status": "dismissed"}
