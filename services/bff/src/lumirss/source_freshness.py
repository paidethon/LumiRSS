"""N014 自适应低活跃建议 —— 从派生投影计算 per-feed 更新间隔画像。

口径（全部来自 search_entries 派生投影，可重建；投影未覆盖的订阅
诚实缺席，不猜测）：

- 窗口：trailing 8 周（56 天），``weeks`` 是建议依据的一部分；
- yield（条目/周）：窗口内条目数 / 8；
- medianGapDays：相邻条目「发布间隔」的中位数（天）。间隔样本 =
  窗口内相邻对 + 「窗口前最后一条 → 窗口内第一条」的跨窗口间隔；
  窗口内零条目但历史有条目 → 以窗口长度（56 天）为观察间隔下界
  （整窗无事发生，间隔只会更长——诚实下界，不是猜测）；
  从未有条目的订阅 → 无法建立 cadence 画像 → 不进建议（basis
  unknown ≠ 超期，F001 的 stale 端点才是「超期」语义的家）。

建议规则：yield < 0.5 且 medianGapDays > 14 → 建议「降低刷新频率」。

诚实边界（接受建议的语义）：FreshRSS greader API 不暴露 per-feed
刷新频率（freshrss_control 无 ttl/timing 能力，已核实）；FreshRSS 的
调度粒度由实例 CRON_MIN 决定。因此「应用」= 在 Lumi 侧记录
``refreshAdvisory=accepted``（一个已记录的决定，来源详情呈现为
「已接受低频建议」），绝不伪装成已改变抓取行为；逐源频率需在
FreshRSS 原生界面调整（/api/v1/freshrss/native-url 提供可达坐标）。
"""

from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

TRAILING_WEEKS = 8
MIN_YIELD = 0.5
MIN_GAP_DAYS = 14.0

SUGGESTED_LABEL = "降低刷新频率"
SCHEDULING_NOTE = (
    "FreshRSS 的抓取调度粒度由实例 CRON_MIN 决定，greader API 不提供"
    " per-feed 刷新频率；接受建议只在 Lumi 侧记录决定，逐源频率需在"
    " FreshRSS 原生界面调整。"
)


def compute_suggestions(
    rows: list[Any], *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """投影行（feed_url, published_at）→ 低活跃建议列表。

    ``rows`` 是一次有界查询的结果（published_at >= 窗口起点的全部行，
    外加各 feed 的全部历史行——见调用方的查询）；纯函数，测试友好。
    """
    moment = now or datetime.now(UTC)
    window_days = TRAILING_WEEKS * 7
    cutoff = moment - timedelta(days=window_days)

    by_feed: dict[str, list[datetime]] = {}
    for row in rows:
        parsed = _parse(row["published_at"])
        if parsed is None:
            continue
        by_feed.setdefault(str(row["feed_url"]), []).append(parsed)

    suggestions: list[dict[str, Any]] = []
    for feed_url, stamps in by_feed.items():
        stamps.sort()
        in_window = [ts for ts in stamps if ts >= cutoff]
        weekly_yield = len(in_window) / TRAILING_WEEKS
        gaps = _gap_samples(stamps, in_window, cutoff, window_days)
        if not gaps:
            continue  # 无法建立 cadence 画像（从未有条目在窗口附近）→ 不建议
        median_gap_days = median(gaps)
        if weekly_yield >= MIN_YIELD or median_gap_days <= MIN_GAP_DAYS:
            continue
        suggestions.append(
            {
                "feedUrl": feed_url,
                "currentPattern": "默认",
                "suggested": SUGGESTED_LABEL,
                "basis": {
                    "weeks": TRAILING_WEEKS,
                    "yield": round(weekly_yield, 4),
                    "medianGapDays": round(median_gap_days, 2),
                },
            }
        )
    suggestions.sort(key=lambda item: -item["basis"]["medianGapDays"])
    return suggestions


def _gap_samples(
    stamps: list[datetime],
    in_window: list[datetime],
    cutoff: datetime,
    window_days: int,
) -> list[float]:
    """间隔样本（天）：窗口内相邻对 + 跨窗口首对 + 零条目时的窗口下界。"""
    if not in_window:
        # 整个窗口零条目：若历史有条目，观察间隔 ≥ 窗口长度（诚实下界）。
        return [float(window_days)] if stamps else []
    gaps: list[float] = []
    # 「窗口前最后一条 → 窗口内第一条」的跨窗口间隔。
    previous = [ts for ts in stamps if ts < cutoff]
    if previous:
        gaps.append((in_window[0] - previous[-1]).total_seconds() / 86400.0)
    for earlier, later in zip(in_window, in_window[1:], strict=False):
        gaps.append((later - earlier).total_seconds() / 86400.0)
    return gaps


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
