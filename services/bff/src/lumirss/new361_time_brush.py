"""NEW-361 时间范围刷选 —— 搜索命中分布上的可选区间。

语义（与 N145 同一口径，诚实简化）：
- 分布只由实际命中数据生成：逐桶计数来自与 GET /search 同一条过滤链
  的 SQL 聚合（GROUP BY 日前缀），空日补 0 只是为了直接渲染柱状——
  绝不伪造任何命中；
- 桶粒度按窗口宽度自动选择：≤92 天按日，更长按月（同一聚合链，仅
  substr 前缀不同）；
- 选定区间后「查看对应文章」复用既有 GET /search 的 from/to（本模块
  不另造第二条文章查询路径）。

per-user：search_entries 在 per-user 库（RoutingDatabase），聚合只
可能是本人条目；A 的分布对 B 不可见。
"""

import re
from datetime import date, timedelta
from typing import Any

from lumirss.search_index import split_terms

MAX_WINDOW_DAYS = 366
_MAX_DAY_BUCKETS = 92
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 同 GET /search 的聚合口径 = 基础词条过滤链（同义词扩展不参与，
# 与 N145/N149 一致——诚实简化而非隐藏）。
DAY_GRANULARITY = "day"
MONTH_GRANULARITY = "month"


class TimeBrushInvalid(ValueError):
    """区间参数非法（格式 / 顺序 / 超窗）→ 400。"""


def _parse_day(value: str | None, field: str) -> date:
    if value is None or not _DATE_RE.match(value):
        raise TimeBrushInvalid(f"{field} 必须是 YYYY-MM-DD 日期。")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TimeBrushInvalid(f"{field} 不是有效日期。") from exc


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def resolve_window(
    *, day_from_str: str, day_to_str: str
) -> tuple[str, str, str]:
    """校验并归一窗口，返回 (day_from, day_to_exclusive, granularity)。

    day_to 为排他上界（+1 天），与 _SQL_DIST_DAYS 的绑定口径一致。
    """
    day_from = _parse_day(day_from_str, "from")
    day_to = _parse_day(day_to_str, "to")
    if day_from > day_to:
        raise TimeBrushInvalid("from 不能晚于 to。")
    if (day_to - day_from).days + 1 > MAX_WINDOW_DAYS:
        raise TimeBrushInvalid(
            f"窗口最多 {MAX_WINDOW_DAYS} 天（如实拒绝，不静默截断）。"
        )
    if (day_to - day_from).days + 1 > _MAX_DAY_BUCKETS:
        return (
            day_from.isoformat(),
            (day_to + timedelta(days=1)).isoformat(),
            MONTH_GRANULARITY,
        )
    return (
        day_from.isoformat(),
        (day_to + timedelta(days=1)).isoformat(),
        DAY_GRANULARITY,
    )


async def brush_buckets(
    store: Any,
    *,
    terms: list[str],
    day_from: str,
    day_to: str,
    granularity: str,
    intitle_terms: list[str] | None = None,
    phrase: str | None = None,
    exclude_terms: list[str] | None = None,
    feed_url: str | None = None,
    category_id: str | None = None,
    unread_only: bool = False,
    starred_only: bool = False,
    published_from: str | None = None,
    published_to: str | None = None,
    has_summary: bool | None = None,
) -> dict[str, Any]:
    """窗口内逐桶实际命中计数（SQL 聚合，正文不出站；空桶补 0）。"""
    common: dict[str, Any] = dict(
        terms=terms,
        intitle_terms=intitle_terms,
        phrase=phrase,
        exclude_terms=exclude_terms,
        feed_url=feed_url,
        category_id=category_id,
        unread_only=unread_only,
        starred_only=starred_only,
        published_from=published_from,
        published_to=published_to,
        has_summary=has_summary,
    )
    if granularity == MONTH_GRANULARITY:
        start = date.fromisoformat(day_from)
        month_from = f"{start.year:04d}-{start.month:02d}"
        end_excl = date.fromisoformat(day_to)
        end_last = end_excl - timedelta(days=1)
        month_to_year, month_to_month = _shift_month(
            end_last.year, end_last.month, 1
        )
        rows = await store.distribution_months(
            **common, month_from=month_from, month_to=f"{month_to_year:04d}-{month_to_month:02d}"
        )
        by_key = {str(row["month"]): int(row["n"]) for row in rows}
        buckets: list[dict[str, Any]] = []
        year, month = start.year, start.month
        while (year, month) <= (end_last.year, end_last.month):
            key = f"{year:04d}-{month:02d}"
            buckets.append({"key": key, "count": by_key.get(key, 0)})
            year, month = _shift_month(year, month, 1)
    else:
        rows = await store.distribution_days(
            **common, day_from=day_from, day_to=day_to
        )
        by_key = {str(row["day"]): int(row["n"]) for row in rows}
        buckets = []
        cursor = date.fromisoformat(day_from)
        last = date.fromisoformat(day_to) - timedelta(days=1)
        while cursor <= last:
            key = cursor.isoformat()
            buckets.append({"key": key, "count": by_key.get(key, 0)})
            cursor += timedelta(days=1)
    total = sum(bucket["count"] for bucket in buckets)
    return {
        "buckets": buckets,
        "total": total,
        "granularity": granularity,
        "dayFrom": day_from,
        "dayTo": day_to,
    }


def terms_of(query: str) -> list[str]:
    """与 GET /search 相同的词条切分（4 词上限由调用侧沿用 service）。"""
    return split_terms(query)
