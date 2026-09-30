"""NEW-393 提醒静默时段 —— 每用户一条的应用内提醒静默设置 + 结束汇总。

边界（硬规则）：

- 静默只影响**呈现**：静默期间事件照常落库（0314），不打扰；结束后
  以汇总摘要呈现窗口内的未读事件，展开即 0391/0392 的原始事件；
- start/end 是用户所选时区的墙钟 HH:MM；end < start = 跨午夜窗口；
  start = end 是空窗口，直接 422 拒绝，绝不静默解释成「全天」；
- time_zone 必须可被 ZoneInfo 解析（IANA 名），不合法 422——绝不
  静默回退服务器时区；
- 汇总只统计本人事件的未读集合（user_id 隔离），数字是真实计数，
  绝不编造「错过 N 条」。
"""

import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from lumirss.storage import Database
from lumirss.util import utc_now

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class QuietHoursInvalid(ValueError):
    """静默设置非法（422）。"""


def _clean_hhmm(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HHMM.match(value.strip()):
        raise QuietHoursInvalid(f"{field} 必须是 HH:MM（24 小时制）。")
    return value.strip()


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _in_window(now_minutes: int, start: int, end: int) -> bool:
    if start < end:
        return start <= now_minutes < end
    # end < start = 跨午夜
    return now_minutes >= start or now_minutes < end


def _window_start_iso(tz: ZoneInfo, start: int, now_local: datetime) -> str:
    """最近一次窗口开始时刻（含跨午夜回溯到昨天）的 ISO 表示。"""
    candidate = now_local.replace(
        hour=start // 60, minute=start % 60, second=0, microsecond=0
    )
    if candidate > now_local:
        from datetime import timedelta

        candidate -= timedelta(days=1)
    return candidate.isoformat(timespec="seconds")


async def get_quiet_hours(db: Database, user_id: str) -> dict[str, Any]:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT * FROM notification_quiet_hours WHERE user_id = ?", (user_id,)
    )
    if row is None:
        return {"enabled": False, "startHHMM": None, "endHHMM": None,
                "timeZone": None, "updatedAt": None}
    return {
        "enabled": bool(row["enabled"]),
        "startHHMM": str(row["start_hhmm"]),
        "endHHMM": str(row["end_hhmm"]),
        "timeZone": str(row["time_zone"]),
        "updatedAt": str(row["updated_at"]),
    }


async def set_quiet_hours(
    db: Database,
    user_id: str,
    *,
    start_hhmm: Any,
    end_hhmm: Any,
    time_zone: Any,
    enabled: bool,
) -> dict[str, Any]:
    start = _clean_hhmm(start_hhmm, "静默开始")
    end = _clean_hhmm(end_hhmm, "静默结束")
    if start == end:
        raise QuietHoursInvalid("静默开始与结束不能相同（空窗口）。")
    if not isinstance(time_zone, str) or not time_zone.strip():
        raise QuietHoursInvalid("时区不能为空。")
    tz_name = time_zone.strip()
    try:
        ZoneInfo(tz_name)
    except Exception as exc:  # noqa: BLE001 — ZoneInfoNotFoundError/ValueError
        raise QuietHoursInvalid(f"无法识别的时区：{tz_name}。") from exc
    await db.migrate()
    now = utc_now()
    existing = await db.fetch_one(
        "SELECT user_id FROM notification_quiet_hours WHERE user_id = ?",
        (user_id,),
    )
    if existing is None:
        await db.execute(
            "INSERT INTO notification_quiet_hours"
            " (user_id, start_hhmm, end_hhmm, time_zone, enabled, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, start, end, tz_name, 1 if enabled else 0, now),
        )
    else:
        await db.execute(
            "UPDATE notification_quiet_hours SET start_hhmm = ?, end_hhmm = ?,"
            " time_zone = ?, enabled = ?, updated_at = ? WHERE user_id = ?",
            (start, end, tz_name, 1 if enabled else 0, now, user_id),
        )
    return await get_quiet_hours(db, user_id)


async def quiet_summary(db: Database, user_id: str) -> dict[str, Any]:
    """静默窗口状态 + 窗口内未读事件汇总（真实计数）。"""
    await db.migrate()
    setting = await get_quiet_hours(db, user_id)
    now = datetime.now(UTC)
    in_quiet = False
    window_start_iso: str | None = None
    quiet_ends_at: str | None = None
    if setting["enabled"]:
        tz = ZoneInfo(str(setting["timeZone"]))
        start = _minutes(str(setting["startHHMM"]))
        end = _minutes(str(setting["endHHMM"]))
        now_local = now.astimezone(tz)
        now_minutes = now_local.hour * 60 + now_local.minute
        in_quiet = _in_window(now_minutes, start, end)
        window_start_iso = _window_start_iso(tz, start, now_local)
        # 结束时刻：窗口内 → 今天的 end；窗口外 → 下一次 end（仅展示口径）
        end_dt = now_local.replace(hour=end // 60, minute=end % 60,
                                   second=0, microsecond=0)
        if in_quiet and end_dt <= now_local:
            from datetime import timedelta

            end_dt += timedelta(days=1)
        quiet_ends_at = end_dt.isoformat(timespec="seconds")
    rows = await db.fetch_all(
        "SELECT kind, read_at, occurred_at FROM user_notifications WHERE user_id = ?",
        (user_id,),
    )
    by_kind: dict[str, int] = {}
    unread_total = 0
    unread_in_window = 0
    for row in rows:
        if row["read_at"] is None:
            unread_total += 1
            by_kind[str(row["kind"])] = by_kind.get(str(row["kind"]), 0) + 1
            if window_start_iso is not None and str(row["occurred_at"]) >= window_start_iso:
                unread_in_window += 1
    return {
        "enabled": setting["enabled"],
        "inQuiet": in_quiet,
        "quietEndsAt": quiet_ends_at if in_quiet else None,
        "windowStart": window_start_iso,
        "unreadTotal": unread_total,
        "unreadDuringWindow": unread_in_window,
        "byKind": by_kind,
        "note": (
            "静默期间事件照常记录，结束后在此汇总；展开即原始事件列表。"
            if in_quiet
            else "当前不在静默时段；汇总为最近静默窗口以来的未读事件。"
        ),
    }
