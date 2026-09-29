"""NEW-283 简报截稿窗口 —— 周期简报的时区 + 截止点 + 迟到分类。

- 每用户单行配置（IANA 时区 + 当地墙钟 'HH:MM' 截止点 + 周期天数）；
- 边界计算显式时区化：now → 用户时区墙钟 → 与截止点比较 → 当前窗口
  [start_utc, cutoff_utc) 全部换算回 UTC 存储/比较，绝不假设服务器
  本地时区；跨时区断言（上海 18:00 ≠ UTC 18:00）由测试锁定；
- 迟到分类：published_at >= cutoff_utc → 'late'（属下一期）。迟到条目
  进本期必须显式 pullBack=True（用户手动调回），系统绝不静默改写
  窗口归属。

per-user：配置在 per-user 库，A 的窗口对 B 不可见。
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from lumirss.new281_briefings import BriefingInvalid
from lumirss.storage import Database
from lumirss.util import utc_now

_PERIOD_DAYS = (1, 7)


def clean_timezone(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise BriefingInvalid("timezone 不能为空（IANA 名称，如 Asia/Shanghai）。")
    name = raw.strip()
    try:
        ZoneInfo(name)
    except Exception as exc:  # noqa: BLE001 — ZoneInfo 的失败形态不固定
        raise BriefingInvalid(f"未知时区：{name}。") from exc
    return name


def clean_cutoff_time(raw: Any) -> str:
    if not isinstance(raw, str):
        raise BriefingInvalid("cutoffTime 必须是 'HH:MM' 墙钟字符串。")
    parts = raw.strip().split(":")
    if len(parts) != 2:
        raise BriefingInvalid("cutoffTime 必须是 'HH:MM'。")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise BriefingInvalid("cutoffTime 必须是 'HH:MM'。") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise BriefingInvalid("cutoffTime 必须是 00:00..23:59。")
    return f"{hour:02d}:{minute:02d}"


def clean_period_days(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw not in _PERIOD_DAYS:
        raise BriefingInvalid("periodDays 必须是 1（日报）或 7（周报）。")
    return raw


def _zone(timezone: str) -> ZoneInfo:
    return ZoneInfo(timezone)


def window_bounds(
    *, timezone: str, cutoff_time: str, period_days: int, now_utc: datetime
) -> dict[str, Any]:
    """当前「最近一个已截稿窗口」的边界（全部 UTC ISO）。

    截稿点语义：期次 = 两次截稿点之间的文章。任一时刻，最近一个已
    到来的截稿点 cutoff_point = min(今日截稿点, now 之前的最近截稿)：

    - 用户时区 now < 今日截稿点 → cutoff_point = 昨日（上期）截稿点；
    - now >= 今日截稿点 → cutoff_point = 今日截稿点。

    当前窗口 = [cutoff_point - 周期, cutoff_point)；截稿点之后发布的
    文章（>= cutoff_point）即「迟到」，属于下一期（起点 = cutoff_point）。
    墙钟构造用 ZoneInfo fold 规则（与 mail_digest 同口径），绝不假设
    服务器本地时区。
    """
    zone = _zone(timezone)
    hour, minute = (int(part) for part in cutoff_time.split(":"))
    local_now = now_utc.astimezone(zone)
    cutoff_local = local_now.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if local_now < cutoff_local:
        window_end = cutoff_local - timedelta(days=period_days)
    else:
        window_end = cutoff_local
    window_start = window_end - timedelta(days=period_days)
    return {
        "startUtc": window_start.astimezone(UTC).isoformat(timespec="seconds"),
        "cutoffUtc": window_end.astimezone(UTC).isoformat(timespec="seconds"),
        "nextWindowStartUtc": window_end.astimezone(UTC).isoformat(
            timespec="seconds"
        ),
    }


def classify_published(
    published_at: str, *, cutoff_utc: str
) -> str:
    """'in'（本窗口内）或 'late'（截稿点之后 → 下一期）。"""
    return "late" if published_at >= cutoff_utc else "in"


class BriefingWindowStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT timezone, cutoff_time, period_days, updated_at"
            " FROM briefing_windows WHERE id = 'default'"
        )
        if row is None:
            return None
        bounds = window_bounds(
            timezone=str(row["timezone"]),
            cutoff_time=str(row["cutoff_time"]),
            period_days=int(row["period_days"]),
            now_utc=datetime.now(UTC),
        )
        return {
            "timezone": str(row["timezone"]),
            "cutoffTime": str(row["cutoff_time"]),
            "periodDays": int(row["period_days"]),
            "updatedAt": str(row["updated_at"]),
            **bounds,
        }

    async def put(
        self, *, timezone: Any, cutoff_time: Any, period_days: Any
    ) -> dict[str, Any]:
        zone = clean_timezone(timezone)
        cutoff = clean_cutoff_time(cutoff_time)
        days = clean_period_days(period_days)
        await self._db.migrate()
        now = utc_now()
        existing = await self._db.fetch_one(
            "SELECT id FROM briefing_windows WHERE id = 'default'"
        )
        if existing is None:
            await self._db.execute(
                "INSERT INTO briefing_windows (id, timezone, cutoff_time,"
                " period_days, updated_at) VALUES ('default', ?, ?, ?, ?)",
                (zone, cutoff, days, now),
            )
        else:
            await self._db.execute(
                "UPDATE briefing_windows SET timezone = ?, cutoff_time = ?,"
                " period_days = ?, updated_at = ? WHERE id = 'default'",
                (zone, cutoff, days, now),
            )
        result = await self.get()
        assert result is not None  # 刚写入
        return result

    async def delete(self) -> bool:
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT id FROM briefing_windows WHERE id = 'default'"
        )
        if existing is None:
            return False
        await self._db.execute(
            "DELETE FROM briefing_windows WHERE id = 'default'"
        )
        return True
