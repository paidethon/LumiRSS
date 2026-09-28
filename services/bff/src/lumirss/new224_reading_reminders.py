"""NEW-224 阅读预约清单 —— 为特定文章设置一次性阅读预约。

诚实边界：

- 提示面**只在应用内**：``GET due`` 是唯一到期面（客户端轮询），
  无推送 / 无邮件 / 无后台任务——本模块没有任何出站通道；
- 一次性：提醒触发（due 首次被读到）记 ``reminded_at``，之后仍是
  active 直到用户显式「完成」或「取消」；绝不自动消失；
- 改期（reschedule）与取消（cancel）都是显式 set 语义；取消幂等。
"""

import uuid
from datetime import datetime
from typing import Any

from lumirss.itemref import InvalidItemRef, parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_ACTIVE = 100
_MAX_NOTE = 200
_STATUSES = ("active", "done", "cancelled")


class ReminderInvalid(Exception):
    """预约载荷非法（时间格式/超限）——422 invalid_reading_reminder。"""


class ReminderNotFound(Exception):
    """预约不存在——404 reading_reminder_not_found。"""


def validate_remind_at(value: str) -> str:
    """RFC3339/ISO 时间戳（BFF 全库统一 UTC ISO 字符串）。"""
    if not isinstance(value, str) or not value.strip():
        raise ReminderInvalid("remindAt 必须是 ISO 时间戳字符串。")
    clean = value.strip()
    try:
        datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReminderInvalid(f"remindAt 不是合法时间戳：{clean}") from exc
    return clean


def validate_note(note: str | None) -> str | None:
    if note is None:
        return None
    if not isinstance(note, str):
        raise ReminderInvalid("note 必须是字符串或 null。")
    clean = note.strip()
    if not clean:
        return None
    if len(clean) > _MAX_NOTE:
        raise ReminderInvalid(f"note 最长 {_MAX_NOTE} 字符。")
    return clean


def validate_item_ref(item_ref: str) -> str:
    try:
        parse_item_ref(item_ref)
    except InvalidItemRef as exc:
        raise ReminderInvalid(f"itemRef 不合法：{exc}") from exc
    return item_ref


class ReminderStore:
    """Persistence for reading_reminders."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _view(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "itemRef": str(row["item_ref"]),
            "remindAt": str(row["remind_at"]),
            "note": row["note"],
            "status": str(row["status"]),
            "createdAt": str(row["created_at"]),
            "remindedAt": row["reminded_at"],
            "updatedAt": str(row["updated_at"]),
            "title": row["projection_title"],
        }

    _SELECT = (
        "SELECT r.id, r.item_ref, r.remind_at, r.note, r.status, r.created_at,"
        " r.reminded_at, r.updated_at, se.title AS projection_title"
        " FROM reading_reminders r"
        " LEFT JOIN search_entries se ON se.entry_ref = substr(r.item_ref, 5)"
    )

    async def _row(self, reminder_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            self._SELECT + " WHERE r.id = ?", (reminder_id,)
        )
        if row is None:
            raise ReminderNotFound(reminder_id)
        return self._view(row)

    async def create(
        self, item_ref: str, remind_at: str, note: str | None = None
    ) -> dict[str, Any]:
        await self._db.migrate()
        validate_item_ref(item_ref)
        clean_at = validate_remind_at(remind_at)
        clean_note = validate_note(note)
        active = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM reading_reminders WHERE status = 'active'"
        )
        if active is not None and int(active["n"]) >= _MAX_ACTIVE:
            raise ReminderInvalid(f"活跃预约上限 {_MAX_ACTIVE} 条。")
        reminder_id = f"rrem-{uuid.uuid4().hex}"
        now = utc_now()
        await self._db.execute(
            "INSERT INTO reading_reminders (id, item_ref, remind_at, note,"
            " status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'active', ?, ?)",
            (reminder_id, item_ref, clean_at, clean_note, now, now),
        )
        return await self._row(reminder_id)

    async def list_reminders(
        self, include_cancelled: bool = False
    ) -> dict[str, Any]:
        await self._db.migrate()
        where = ""
        if not include_cancelled:
            where = " WHERE r.status != 'cancelled'"
        rows = await self._db.fetch_all(
            self._SELECT + where + " ORDER BY r.remind_at ASC, r.rowid ASC"
        )
        now = utc_now()
        items = [self._view(row) for row in rows]
        for item in items:
            item["due"] = (
                item["status"] == "active" and str(item["remindAt"]) <= now
            )
        return {
            "items": items,
            "serverNow": now,
            "channel": "in-app",
            "note": "预约只在应用内提示（due 列表），没有推送或邮件。",
        }

    async def reschedule(self, reminder_id: str, remind_at: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._row(reminder_id)
        if row["status"] != "active":
            raise ReminderInvalid(f"预约已是 {row['status']}，不能改期。")
        clean_at = validate_remind_at(remind_at)
        await self._db.execute(
            "UPDATE reading_reminders SET remind_at = ?, updated_at = ?"
            " WHERE id = ?",
            (clean_at, utc_now(), reminder_id),
        )
        return await self._row(reminder_id)

    async def cancel(self, reminder_id: str) -> dict[str, Any]:
        """取消（幂等：已取消原样返回；done → 422）。"""
        await self._db.migrate()
        row = await self._row(reminder_id)
        if row["status"] == "done":
            raise ReminderInvalid("预约已完成，不能再取消。")
        if row["status"] != "cancelled":
            await self._db.execute(
                "UPDATE reading_reminders SET status = 'cancelled',"
                " updated_at = ? WHERE id = ?",
                (utc_now(), reminder_id),
            )
        return await self._row(reminder_id)

    async def complete(self, reminder_id: str) -> dict[str, Any]:
        """用户显式完成（读到点了）。"""
        await self._db.migrate()
        row = await self._row(reminder_id)
        if row["status"] == "cancelled":
            raise ReminderInvalid("预约已取消，不能标记完成。")
        if row["status"] != "done":
            await self._db.execute(
                "UPDATE reading_reminders SET status = 'done',"
                " updated_at = ? WHERE id = ?",
                (utc_now(), reminder_id),
            )
        return await self._row(reminder_id)

    async def delete(self, reminder_id: str) -> None:
        """物理删除一条预约（housekeeping；取消用 cancel）。"""
        await self._db.migrate()
        await self._row(reminder_id)  # 404 when missing
        await self._db.execute(
            "DELETE FROM reading_reminders WHERE id = ?", (reminder_id,)
        )

    async def due(self) -> dict[str, Any]:
        """到期面（应用内轮询）：active 且 remind_at ≤ now。
        首次被读到时记 reminded_at（一次性触达标记；状态不变）。"""
        await self._db.migrate()
        now = utc_now()
        rows = await self._db.fetch_all(
            self._SELECT
            + " WHERE r.status = 'active' AND r.remind_at <= ?"
            " ORDER BY r.remind_at ASC",
            (now,),
        )
        items = []
        for row in rows:
            if row["reminded_at"] is None:
                await self._db.execute(
                    "UPDATE reading_reminders SET reminded_at = ? WHERE id = ?",
                    (now, str(row["id"])),
                )
            view = self._view(row)
            view["remindedAt"] = view["remindedAt"] or now
            items.append(view)
        return {
            "serverNow": now,
            "items": items,
            "channel": "in-app",
            "note": "到时只在应用内提示。",
        }


__all__ = [
    "ReminderInvalid",
    "ReminderNotFound",
    "ReminderStore",
]
