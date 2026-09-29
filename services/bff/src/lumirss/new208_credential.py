"""NEW-208 来源认证到期提醒 —— 到期日语义的存储、分类与续期。

用户为「访问凭据会过期的来源」主动登记到期日；系统只存**提醒元
数据**（到期日 + 备注 + 续期计数），到点在来源运维台提醒。安全属性
由构造保证：

- schema 没有凭据字段（见迁移 0143 注释）——没有可泄的凭据；
- 响应永不回显任何凭据形态的数据；更新引导指向**受控入口**
  （RSSHub 凭据库 / FreshRSS 原生界面），本模块不承载凭据读写；
- 备注是有界自由文本（≤200），供用户写「找谁续」这类元信息。

分类（:func:`classify_expiry`，today 可注入）：
- ``overdue``：expires_on < today（已过期）；
- ``due_soon``：0 ≤ (expires_on - today) ≤ 提前量（缺省 14 天）；
- ``later``：更远。

dismiss 是 set 语义（active → dismissed，行保留）；renew 更新到期日
并使 dismissed 行重新激活（续期 = 新周期开始，提醒应再次可见）。
"""

import re
import uuid as _uuid
from datetime import UTC, date, datetime
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_NOTE = 200
MAX_SOURCE_LABEL = 120
DEFAULT_UPCOMING_DAYS = 14
MAX_UPCOMING_DAYS = 90

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 更新引导：到期凭据的受控入口（只给坐标，绝不给凭据读写能力）。
UPDATE_ENTRY_RSSHUB = "rsshub-credentials"
UPDATE_ENTRY_FRESHRSS = "freshrss-native"


class CredentialReminderInvalid(ValueError):
    """提醒元数据非法（日期/长度），路由层映射 422。"""


def parse_iso_date(value: Any, field: str = "expiresOn") -> str:
    """严格 YYYY-MM-DD 校验（非法 raise → 422）。返回原串。"""
    text = str(value or "").strip()
    if not _DATE_RE.match(text):
        raise CredentialReminderInvalid(f"{field} 必须是 YYYY-MM-DD 日期。")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise CredentialReminderInvalid(f"{field} 不是有效日期。") from exc
    return text


def classify_expiry(
    expires_on: str, *, today: str | None = None, upcoming_days: int = DEFAULT_UPCOMING_DAYS
) -> str:
    """到期日 → overdue | due_soon | later（纯函数，today 可注入）。"""
    day = date.fromisoformat(expires_on)
    anchor = date.fromisoformat(today) if today else datetime.now(UTC).date()
    delta = (day - anchor).days
    if delta < 0:
        return "overdue"
    if delta <= upcoming_days:
        return "due_soon"
    return "later"


def _row_to_reminder(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "feedUrl": str(row["feed_url"]),
        "sourceLabel": row["source_label"],
        "expiresOn": str(row["expires_on"]),
        "note": row["note"],
        "status": str(row["status"]),
        "renewedCount": int(row["renewed_count"]),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


class CredentialReminderStore:
    """SQL 唯一入口；inline literal at each execute site（repo 约定）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        feed_url: str,
        expires_on: str,
        source_label: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        clean_label = (source_label or "").strip() or None
        if clean_label and len(clean_label) > MAX_SOURCE_LABEL:
            raise CredentialReminderInvalid(
                f"sourceLabel 过长（≤{MAX_SOURCE_LABEL} 字符）。"
            )
        clean_note = (note or "").strip() or None
        if clean_note and len(clean_note) > MAX_NOTE:
            raise CredentialReminderInvalid(f"note 过长（≤{MAX_NOTE} 字符）。")
        clean_url = feed_url.strip()
        if not clean_url:
            raise CredentialReminderInvalid("feedUrl 不能为空。")
        reminder_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO new208_credential_reminders"
            " (id, feed_url, source_label, expires_on, note, status,"
            "  renewed_count, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 'active', 0, ?, ?)",
            (reminder_id, clean_url, clean_label, expires_on, clean_note, now, now),
        )
        return {
            "id": reminder_id,
            "feedUrl": clean_url,
            "sourceLabel": clean_label,
            "expiresOn": expires_on,
            "note": clean_note,
            "status": "active",
            "renewedCount": 0,
            "createdAt": now,
            "updatedAt": now,
        }

    async def list_reminders(
        self, *, include_dismissed: bool = False
    ) -> list[dict[str, Any]]:
        await self._db.migrate()
        if include_dismissed:
            rows = await self._db.fetch_all(
                "SELECT id, feed_url, source_label, expires_on, note, status,"
                " renewed_count, created_at, updated_at"
                " FROM new208_credential_reminders"
                " ORDER BY expires_on ASC, id ASC LIMIT 200",
                (),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, feed_url, source_label, expires_on, note, status,"
                " renewed_count, created_at, updated_at"
                " FROM new208_credential_reminders WHERE status = 'active'"
                " ORDER BY expires_on ASC, id ASC LIMIT 200",
                (),
            )
        return [_row_to_reminder(row) for row in rows]

    async def get(self, reminder_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, feed_url, source_label, expires_on, note, status,"
            " renewed_count, created_at, updated_at"
            " FROM new208_credential_reminders WHERE id = ?",
            (reminder_id,),
        )
        return _row_to_reminder(row) if row is not None else None

    async def renew(self, reminder_id: str, expires_on: str) -> dict[str, Any]:
        """续期：更新到期日、dismissed → active（新周期提醒再次可见）、
        计数 +1。不存在 → CredentialReminderNotFound。"""
        row = await self.get(reminder_id)
        if row is None:
            raise CredentialReminderNotFound(reminder_id)
        await self._db.execute(
            "UPDATE new208_credential_reminders SET expires_on = ?,"
            " status = 'active', renewed_count = renewed_count + 1, updated_at = ?"
            " WHERE id = ?",
            (expires_on, utc_now(), reminder_id),
        )
        updated = await self.get(reminder_id)
        assert updated is not None
        return updated

    async def set_dismissed(self, reminder_id: str, dismissed: bool) -> dict[str, Any]:
        """dismiss / re-activate（set 语义，非 toggle）。"""
        row = await self.get(reminder_id)
        if row is None:
            raise CredentialReminderNotFound(reminder_id)
        status = "dismissed" if dismissed else "active"
        await self._db.execute(
            "UPDATE new208_credential_reminders SET status = ?, updated_at = ?"
            " WHERE id = ?",
            (status, utc_now(), reminder_id),
        )
        updated = await self.get(reminder_id)
        assert updated is not None
        return updated


class CredentialReminderNotFound(Exception):
    """提醒不存在 —— 404 credential_reminder_not_found。"""
