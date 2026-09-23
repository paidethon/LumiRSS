"""N015 来源分时静音 —— 每周循环静音窗口的校验、存储与判定。

窗口形态：``[{"days": [0-6…], "start": "HH:MM", "end": "HH:MM"}]``

- days：星期集合，0=周日 … 6=周六（与 JS ``Date.getDay()`` 对齐，
  便于 Web 端同形展示）；子集校验、去重排序、不允许空；
- start/end：``HH:MM`` 严格格式；``end < start`` 表示跨越午夜；
  ``start == end`` 拒绝（空窗口）；
- 每来源 ≤ 7 个窗口。

生效面（与 hiddenUntil/showFrom 完全一致的消费点）：通用时间线显示
过滤（source_overrides.filter_timeline_items）。抓取、搜索投影、阅读、
已读/收藏不受影响——服务端照常索引（测试固定该负向契约）。

时区口径：服务器本地墙钟（与 mail_digest 的「未配置 → 服务器本地」
回退语义一致）。hiddenUntil/showFrom 是绝对 UTC 时刻；周循环窗口必须
落在某个墙钟上，这里取服务器本地并如实文档化。
"""

import json
from datetime import datetime
from typing import Any

from lumirss.util import utc_now

MAX_WINDOWS_PER_FEED = 7
_TIME_CHARS = 5


class MuteWindowsInvalid(ValueError):
    """窗口定义非法（路由层映射 422）。"""


def _parse_hhmm(value: Any, field: str) -> tuple[int, int]:
    if not isinstance(value, str) or len(value) != _TIME_CHARS or value[2] != ":":
        raise MuteWindowsInvalid(f"{field} 必须是 HH:MM 格式。")
    hh, mm = value[:2], value[3:]
    if not (hh.isdigit() and mm.isdigit()):
        raise MuteWindowsInvalid(f"{field} 必须是 HH:MM 格式。")
    hour, minute = int(hh), int(mm)
    if hour > 23 or minute > 59:
        raise MuteWindowsInvalid(f"{field} 时刻越界（HH 00-23，MM 00-59）。")
    return hour, minute


def validate_windows(raw: Any) -> list[dict[str, Any]] | None:
    """校验并归一化窗口列表（None/[] → None；非法 raise，路由映射 422）。"""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise MuteWindowsInvalid("muteWindows 必须是数组。")
    if len(raw) > MAX_WINDOWS_PER_FEED:
        raise MuteWindowsInvalid(f"每来源最多 {MAX_WINDOWS_PER_FEED} 个窗口。")
    cleaned: list[dict[str, Any]] = []
    for window in raw:
        if not isinstance(window, dict):
            raise MuteWindowsInvalid("每个窗口必须是对象。")
        unknown = set(window) - {"days", "start", "end"}
        if unknown:
            raise MuteWindowsInvalid(f"窗口含未知键：{sorted(unknown)}")
        days = window.get("days")
        if not isinstance(days, list) or not days:
            raise MuteWindowsInvalid("days 必须是非空数组（0=周日 … 6=周六）。")
        clean_days: list[int] = []
        for day in days:
            if not isinstance(day, int) or isinstance(day, bool) or not 0 <= day <= 6:
                raise MuteWindowsInvalid("days 必须是 0-6 的整数（0=周日 … 6=周六）。")
            if day not in clean_days:
                clean_days.append(day)
        start = _parse_hhmm(window.get("start"), "start")
        end = _parse_hhmm(window.get("end"), "end")
        if start == end:
            raise MuteWindowsInvalid("start 与 end 不能相同（空窗口）。")
        cleaned.append(
            {
                "days": sorted(clean_days),
                "start": f"{start[0]:02d}:{start[1]:02d}",
                "end": f"{end[0]:02d}:{end[1]:02d}",
            }
        )
    return cleaned or None


def load_windows(raw_json: str) -> list[dict[str, Any]]:
    """存储的 JSON 文本 → 已验证窗口列表（损坏 raise ValueError）。"""
    parsed = json.loads(raw_json)
    windows = validate_windows(parsed)
    if windows is None:
        raise ValueError("muteWindows 存储为空。")
    return windows


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def window_hit(window: dict[str, Any], local_now: datetime) -> bool:
    """单个窗口是否命中给定本地墙钟（end<start 表示跨午夜）。

    跨午夜窗口拆两段归属：``start..24:00`` 归 days 中的当天；
    ``00:00..end`` 归「昨天在 days 里」的次日。"""
    # JS getDay() 对齐：0=周日；Python weekday()：0=周一 … 6=周日。
    js_day = (local_now.weekday() + 1) % 7
    now_minutes = local_now.hour * 60 + local_now.minute
    start = _minutes(str(window["start"]))
    end = _minutes(str(window["end"]))
    days = window["days"]
    if start < end:
        return js_day in days and start <= now_minutes < end
    # 跨午夜：start..24:00 段按当天归属；00:00..end 段按「昨天」归属。
    return (now_minutes >= start and js_day in days) or (
        now_minutes < end and (js_day + 6) % 7 in days
    )


def any_window_hit(windows: list[dict[str, Any]] | None, local_now: datetime) -> bool:
    if not windows:
        return False
    return any(window_hit(window, local_now) for window in windows)


async def set_mute_windows(
    db: Any, feed_url: str, raw: Any
) -> list[dict[str, Any]] | None:
    """设置/清除某来源的分时静音窗口（保留同行的其它覆盖维度）。

    None = 清除；非法定义 raise（路由映射 422，零写入）。"""
    windows = validate_windows(raw)
    await db.migrate()
    payload = (
        json.dumps(windows, ensure_ascii=False, separators=(",", ":"))
        if windows
        else None
    )
    row = await db.fetch_one(
        "SELECT feed_url FROM source_overrides WHERE feed_url = ?",
        (feed_url,),
    )
    if row is None:
        if not windows:
            return None
        await db.execute(
            "INSERT INTO source_overrides (feed_url, hidden_until, show_from, stale_alert_hours, extract_policy, mute_windows_json, updated_at) VALUES (?, NULL, NULL, NULL, 'rss', ?, ?)",
            (feed_url, payload, utc_now()),
        )
        return windows
    await db.execute(
        "UPDATE source_overrides SET mute_windows_json = ?, updated_at = ? WHERE feed_url = ?",
        (payload, utc_now(), feed_url),
    )
    return windows
