"""N014 自适应低活跃建议 —— 建议计算、接受决定（纯记录）与诚实边界。

- 建议数学：trailing 8 周窗口，yield = 窗口条目/周；medianGapDays =
  相邻发布间隔中位数（跨窗口首对计入；整窗零条目 → 窗口长度为
  观察间隔下界；从未有条目 → 不建议）；
- 规则：yield < 0.5 且 medianGapDays > 14 → 建议；
- 应用语义：接受 = source_overrides.refresh_advisory='accepted'
  （一个已记录决定）——**不改变任何抓取行为**，响应携带诚实说明
  （FreshRSS 调度粒度由实例 CRON_MIN 决定，greader API 无 per-feed ttl）。
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from lumirss.main import app
from lumirss.source_freshness import (
    SCHEDULING_NOTE,
    compute_suggestions,
)
from lumirss.storage import Database

FEED_URL = "https://sparse.example/rss"
ACTIVE_URL = "https://active.example/rss"
DEAD_URL = "https://ghost.example/rss"

NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)


def run(coroutine):
    return asyncio.run(coroutine)


def _row(feed_url: str, published_at: str):
    return {"feed_url": feed_url, "published_at": published_at}


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- 纯函数：建议数学 --------------------------------------------------------


def test_n014_sparse_feed_is_suggested_with_basis():
    # 8 周窗口内 2 条、间隔 30 天：yield=0.25，medianGapDays=30。
    rows = [_row(FEED_URL, _iso(40)), _row(FEED_URL, _iso(10))]
    suggestions = compute_suggestions(rows, now=NOW)
    assert len(suggestions) == 1
    item = suggestions[0]
    assert item["feedUrl"] == FEED_URL
    assert item["currentPattern"] == "默认"
    assert item["suggested"] == "降低刷新频率"
    assert item["basis"]["weeks"] == 8
    assert item["basis"]["yield"] == 0.25
    assert item["basis"]["medianGapDays"] == 30.0


def test_n014_active_feed_not_suggested():
    # 8 周 20 条（≈2.5/周）：yield 达标 → 绝不建议。
    rows = [_row(ACTIVE_URL, _iso(day)) for day in range(2, 56, 2)]
    assert compute_suggestions(rows, now=NOW) == []


def test_n014_zero_entries_in_window_uses_window_length_as_lower_bound():
    # 窗口内零条目但历史有条目：观察间隔下界 = 窗口长度（56 天）。
    rows = [_row(FEED_URL, _iso(90)), _row(FEED_URL, _iso(80))]
    suggestions = compute_suggestions(rows, now=NOW)
    assert len(suggestions) == 1
    assert suggestions[0]["basis"]["medianGapDays"] == 56.0
    assert suggestions[0]["basis"]["yield"] == 0.0


def test_n014_feed_without_any_entries_is_never_suggested():
    # 从未有条目：无法建立 cadence 画像 → 不进建议（unknown ≠ 超期）。
    assert compute_suggestions([_row(DEAD_URL, "")], now=NOW) == []
    assert compute_suggestions([], now=NOW) == []


def test_n014_short_gap_blocks_suggestion_even_with_low_yield():
    # yield 低（2 条）但间隔 3 天（活跃突发）→ 不建议（gap 口径保护）。
    rows = [_row(FEED_URL, _iso(6)), _row(FEED_URL, _iso(3))]
    assert compute_suggestions(rows, now=NOW) == []


# ---- 路由：建议端点 + 应用记录决定 -------------------------------------------


def _seed_projection(db: Database, feed_url: str, days_ago: list[float]):
    for idx, day in enumerate(days_ago):
        ref = f"{feed_url}#{idx}"
        run(
            db.execute(
                "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ref, ref, feed_url, "源", ref, "", "", "正文", _iso(day), 0, 0, 1789660000),
            )
        )


def _install_adapter(subscriptions):
    async def _list_subscriptions():
        return list(subscriptions)

    app.state.freshrss_adapter = SimpleNamespace(list_subscriptions=_list_subscriptions)


def test_n014_route_suggestion_and_apply_records_advisory(tmp_path):
    from fastapi.testclient import TestClient

    from lumirss.adapters.freshrss_control import Subscription
    from lumirss.source_overrides import SourceOverrideStore

    subscription = Subscription(
        stream_id="feed/11", title="Sparse", feed_url=FEED_URL
    )
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        run(app.state.db.migrate())
        _seed_projection(app.state.db, FEED_URL, [40, 10])
        _install_adapter([subscription])
        response = client.get("/api/v1/sources/freshness-suggestions")
        assert response.status_code == 200
        payload = response.json()
        # 诚实说明必须随建议一起返回（CRON_MIN 边界）。
        assert "CRON_MIN" in payload["schedulingNote"]
        assert payload["basis"].startswith("search_entries")
        items = [i for i in payload["items"] if i["feedUrl"] == FEED_URL]
        assert len(items) == 1
        item = items[0]
        assert item["currentPattern"] == "默认"
        assert item["suggested"] == "降低刷新频率"
        assert item["basis"]["weeks"] == 8
        assert item["refreshAdvisory"] is None
        assert item["subscriptionRef"]

        applied = client.post(
            "/api/v1/sources/freshness-suggestions/apply",
            json={"feedUrl": FEED_URL},
        )
        assert applied.status_code == 200
        body = applied.json()
        assert body["refreshAdvisory"] == "accepted"
        assert "CRON_MIN" in body["schedulingNote"]

        # 决定已入库并在建议列表与覆盖视图呈现（已接受低频建议）。
        override = run(SourceOverrideStore(app.state.db).get_override(FEED_URL))
        assert override is not None
        assert override["refreshAdvisory"] == "accepted"
        again = client.get("/api/v1/sources/freshness-suggestions")
        assert again.json()["items"][0]["refreshAdvisory"] == "accepted"

        # 幂等：重复接受不报错。
        repeat = client.post(
            "/api/v1/sources/freshness-suggestions/apply",
            json={"feedUrl": FEED_URL},
        )
        assert repeat.status_code == 200

        # 未订阅的来源 → 404（不为不存在的来源记决定）。
        missing = client.post(
            "/api/v1/sources/freshness-suggestions/apply",
            json={"feedUrl": "https://not-subscribed.example/rss"},
        )
        assert missing.status_code == 404
    app.state.freshrss_adapter = None


def test_n014_scheduling_note_names_the_real_boundary():
    # 诚实边界文案：明确 greader API 无 per-feed 刷新频率 + CRON_MIN 归属。
    assert "CRON_MIN" in SCHEDULING_NOTE
    assert "greader" in SCHEDULING_NOTE or "API" in SCHEDULING_NOTE
