"""N017 来源清理建议 — behavior stats × yield, apply only on confirmation.

Stats come from the user's OWN data, never from FreshRSS-side behavior:

- read recency: FreshRSS exposes no per-entry read timestamps, so Lumi
  keeps a small derived projection (``feed_read_stats``, migration 0106)
  of its own read-write path. It starts empty on upgrade — the endpoint
  reports that basis honestly instead of guessing "never read";
- yield: entries per week over the trailing 28 days from the
  ``search_entries`` projection (published_at based, rebuildable).

A suggestion is advisory text only. NOTHING runs automatically: applying
happens exclusively through the explicit apply endpoint listing the
feeds the user confirmed (mute = hide from the timeline via the existing
source-overrides channel; demote = move to a named category via the
existing control-plane move).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from lumirss.util import utc_now

DEFAULT_MIN_WEEKLY_YIELD = 1.0
DEFAULT_STALE_DAYS = 30
_YIELD_WINDOW_DAYS = 28
_MUTE_MULTIPLIER = 3  # ≥3× the stale threshold → suggest mute, else demote
_MAX_SUGGESTIONS = 100


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def build_suggestions(
    db,
    subscriptions: list[Any],
    *,
    min_weekly_yield: float = DEFAULT_MIN_WEEKLY_YIELD,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> dict[str, Any]:
    """Read-only suggestion list; unknown data stays honestly unknown."""
    await db.migrate()
    since = (
        datetime.now(UTC) - timedelta(days=_YIELD_WINDOW_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = await db.fetch_all(
            "SELECT feed_url, COUNT(*) AS n FROM search_entries WHERE published_at >= ? GROUP BY feed_url",
            (since,),
        )
    except Exception:  # noqa: BLE001 — projection unavailable → no yield claims
        rows = []
    weekly = {
        str(row["feed_url"]): int(row["n"]) / (_YIELD_WINDOW_DAYS / 7)
        for row in rows
    }
    try:
        read_rows = await db.fetch_all(
            "SELECT feed_url, last_read_at FROM feed_read_stats", ()
        )
    except Exception:  # noqa: BLE001 — stats table unavailable → unknown reads
        read_rows = []
    last_read = {
        str(row["feed_url"]): str(row["last_read_at"]) for row in read_rows
    }

    now = datetime.now(UTC)
    stale_cutoff = timedelta(days=stale_days)
    items: list[dict[str, Any]] = []
    basis_note = (
        "lastReadAt 来自本服务器的已读记录（feed_read_stats，自该功能上线起累计）；"
        "缺失 ≠ 从未读过，只表示本服务器没有记录。"
    )
    for subscription in subscriptions:
        yield_value = weekly.get(subscription.feed_url, 0.0)
        if yield_value < min_weekly_yield:
            continue
        read_at = last_read.get(subscription.feed_url)
        if read_at is not None:
            read_dt = _parse_iso(read_at)
            if read_dt is None:
                read_at = None
            else:
                age = now - read_dt
                if age < stale_cutoff:
                    continue  # recently read → not a cleanup candidate
                days_stale = age.total_seconds() / 86400.0
        else:
            days_stale = None
        if days_stale is not None and days_stale >= stale_days * _MUTE_MULTIPLIER:
            suggestion = "mute"
        else:
            suggestion = "demote"
        items.append(
            {
                "feedUrl": subscription.feed_url,
                "title": subscription.title or subscription.feed_url,
                "lastReadAt": read_at,
                "weeklyYield": round(yield_value, 2),
                "suggestion": suggestion,
                "basis": (
                    f"最近 {stale_days} 天未读（距上次已读 {int(days_stale)} 天）"
                    if days_stale is not None
                    else basis_note
                ),
            }
        )
    items.sort(key=lambda item: -item["weeklyYield"])
    return {
        "items": items[:_MAX_SUGGESTIONS],
        "generatedAt": utc_now(),
        "basis": basis_note,
    }


async def record_feed_read(db, entry_ref: str) -> None:
    """Bump the per-feed read recency projection for one entry write.

    Best-effort by contract: the entry's feed is looked up in the
    search projection; a miss (projection behind, api_item refs) simply
    records nothing. Never raises into the entry write path."""
    import contextlib

    with contextlib.suppress(Exception):
        await db.migrate()
        row = await db.fetch_one(
            "SELECT feed_url FROM search_entries WHERE entry_ref = ?",
            (entry_ref,),
        )
        if row is None:
            return
        feed_url = str(row["feed_url"])
        now = utc_now()
        await db.execute(
            "INSERT INTO feed_read_stats (feed_url, last_read_at, read_total) VALUES (?, ?, 1) ON CONFLICT(feed_url) DO UPDATE SET last_read_at = excluded.last_read_at, read_total = feed_read_stats.read_total + 1",
            (feed_url, now),
        )
