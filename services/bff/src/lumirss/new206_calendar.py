"""NEW-206 来源阅读日历 —— 按真实发表日期的 per-feed 月历（只读投影）。

口径与诚实边界：

- 日历完全来自派生投影 search_entries 的 ``published_at``（feedparser
  解析出的**发表日期**，不是抓取时间）；投影可再生成，删除无损失；
- 「没有发文」与「抓取资料缺失」严格区分（:func:`build_calendar`）：
  该来源在投影中**一行都没有** → ``coverage='no_projection_data'``
  （可能是还没同步过/投影被清理——资料缺失 ≠ 当月没发文）；有行但
  当月无条目 → 正常空日历（``coverage='projection'``，days 为空）；
- 消费 NEW-210：来源处于抓取停机计划 → ``fetchPaused=true``（日历
  数据可能滞后于上游，如实标注）；
- 只读：本模块零写入（负向契约由测试固定：数据库逐字节不变）。
"""

from typing import Any

from lumirss.storage import Database

MONTH_RE_MIN, MONTH_RE_MAX = "0000-01", "9999-12"
_DAY_SAMPLE_LIMIT = 5
_ROWS_LIMIT = 1000
_DAY_KEY_LEN = 10  # YYYY-MM-DD


def validate_month(value: Any) -> str:
    """YYYY-MM 校验（严格两位月；非法 raise ValueError → 422）。"""
    text = str(value or "").strip()
    if len(text) != 7 or text[4] != "-":
        raise ValueError("month 必须是 YYYY-MM 格式。")
    year, month = text[:4], text[5:]
    if not (year.isdigit() and month.isdigit()):
        raise ValueError("month 必须是 YYYY-MM 格式。")
    if not (MONTH_RE_MIN <= text <= MONTH_RE_MAX) or not 1 <= int(month) <= 12:
        raise ValueError("month 越界（01-12 月）。")
    return text


def month_bounds(month: str) -> tuple[str, str]:
    """[month 起点, 下月起点) 的 Z 串边界（与 published_at 同形比较）。"""
    from datetime import date

    year, month_num = int(month[:4]), int(month[5:])
    first = date(year, month_num, 1)
    nxt = date(year + 1, 1, 1) if month_num == 12 else date(year, month_num + 1, 1)
    return (
        first.strftime("%Y-%m-%dT00:00:00Z"),
        nxt.strftime("%Y-%m-%dT00:00:00Z"),
    )


def build_calendar(rows: list[Any], month: str) -> dict[str, Any]:
    """投影行 → 月历视图（纯函数，测试友好）。

    ``rows`` 是 (entry_ref, title, published_at) 元组序列（当月界内，
    升序由查询保证；越界行被诚实忽略并计数）。"""
    start, end = month_bounds(month)
    days: dict[str, dict[str, Any]] = {}
    total = 0
    out_of_window = 0
    for entry_ref, title, published_at in rows:
        stamp = str(published_at)
        if not (start <= stamp < end):
            out_of_window += 1
            continue
        total += 1
        day_key = stamp[:_DAY_KEY_LEN]
        bucket = days.setdefault(day_key, {"count": 0, "sample": []})
        bucket["count"] += 1
        if len(bucket["sample"]) < _DAY_SAMPLE_LIMIT:
            bucket["sample"].append(
                {
                    "entryRef": str(entry_ref),
                    "title": str(title or ""),
                    "publishedAt": stamp,
                }
            )
    return {
        "month": month,
        "days": [
            {"date": day_key, **bucket} for day_key, bucket in sorted(days.items())
        ],
        "totalEntries": total,
        "outOfWindowRows": out_of_window,
        "sampleLimitPerDay": _DAY_SAMPLE_LIMIT,
        "basis": "projection",
    }


async def feed_month_calendar(
    db: Database, feed_url: str, month: str
) -> dict[str, Any]:
    """查询投影 → 月历 + 覆盖面判定（只读）。"""
    from lumirss.new210_pause import PausePlanStore

    await db.migrate()
    coverage_row = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM search_entries WHERE feed_url = ?",
        (feed_url,),
    )
    coverage = (
        "projection"
        if coverage_row is not None and int(coverage_row["n"]) > 0
        else "no_projection_data"
    )
    if coverage == "projection":
        start, end = month_bounds(month)
        rows = await db.fetch_all(
            "SELECT entry_ref, title, published_at FROM search_entries"
            " WHERE feed_url = ? AND published_at >= ? AND published_at < ?"
            " ORDER BY published_at ASC LIMIT ?",
            (feed_url, start, end, _ROWS_LIMIT),
        )
        calendar = build_calendar(
            [(row["entry_ref"], row["title"], row["published_at"]) for row in rows],
            month,
        )
    else:
        calendar = build_calendar([], month)
    paused = feed_url in await PausePlanStore(db).paused_feed_urls()
    return {
        **calendar,
        "feedUrl": feed_url,
        "coverage": coverage,
        "fetchPaused": paused,
        "note": (
            (
                "该来源在投影中暂无任何条目：可能是尚未同步或投影被清理"
                "（资料缺失 ≠ 当月没有发文）。"
                if coverage == "no_projection_data"
                else "日历按真实发表日期（投影口径）；当日超过 5 条时展示"
                "前 5 条样本。"
            )
            + ("（该来源抓取暂停中，数据可能滞后。）" if paused else "")
        ),
    }
