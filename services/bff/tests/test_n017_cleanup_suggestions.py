"""N017 来源清理建议 — suggestion math + explicit-only apply.

Proves the suggestion fixtures (yield over trailing 28 days from the
search projection × per-feed read recency): recently-read feeds are
excluded, long-unread high-yield feeds are listed (mute at ≥3× the
stale threshold, else demote), and unknown read history stays honestly
unknown. Apply mutates ONLY the explicitly selected feeds (mute via the
source-overrides channel, demote via the move-to-category control
path); nothing auto-runs on GET and there is no auto-unsubscribe.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest


def _run(coroutine):
    return asyncio.run(coroutine)


def _iso(seconds_ago: float) -> str:
    moment = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_projection(db, feed_url: str, count: int, published_iso: str) -> None:
    async def _seed():
        for i in range(count):
            await db.execute(
                "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1789660000)",
                (
                    f"{feed_url}#{i}",
                    f"{feed_url}#{i}",
                    feed_url,
                    "源",
                    "条目",
                    "",
                    "",
                    "",
                    published_iso,
                ),
            )

    _run(_seed())


def _seed_read(db, feed_url: str, read_iso: str) -> None:
    async def _seed():
        await db.execute(
            "INSERT INTO feed_read_stats (feed_url, last_read_at, read_total) VALUES (?, ?, 3) ON CONFLICT(feed_url) DO UPDATE SET last_read_at = excluded.last_read_at",
            (feed_url, read_iso),
        )

    _run(_seed())


def _subs(*urls: str):
    return [
        SimpleNamespace(
            feed_url=url,
            title=f"源 {i}",
            stream_id=f"feed/{i}",
            subscription_ref=f"s{i}",
            category_id=None,
            category_label=None,
        )
        for i, url in enumerate(urls)
    ]


@pytest.fixture()
def db(client):
    return client.app.state.db


def test_suggestion_math(client, db):
    from lumirss.source_cleanup import build_suggestions

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # 高产 + 100 天未读（≥3×30d）→ mute
    _seed_projection(db, "https://a.example/rss", 12, now)  # 3 条/周
    _seed_read(db, "https://a.example/rss", _iso(100 * 86400))
    # 高产 + 40 天未读（<3×30d）→ demote
    _seed_projection(db, "https://b.example/rss", 8, now)  # 2 条/周
    _seed_read(db, "https://b.example/rss", _iso(40 * 86400))
    # 最近读过 → 不建议
    _seed_projection(db, "https://c.example/rss", 12, now)
    _seed_read(db, "https://c.example/rss", _iso(2 * 86400))
    # 高产但无已读记录 → 入选但 lastReadAt=null（诚实未知，不谎称从未读）
    _seed_projection(db, "https://d.example/rss", 16, now)

    result = _run(build_suggestions(db, _subs("https://a.example/rss", "https://b.example/rss", "https://c.example/rss", "https://d.example/rss")))
    by_url = {item["feedUrl"]: item for item in result["items"]}
    assert "https://c.example/rss" not in by_url, "最近读过的来源绝不入选"
    assert by_url["https://a.example/rss"]["suggestion"] == "mute"
    assert by_url["https://a.example/rss"]["weeklyYield"] == 3.0
    assert by_url["https://b.example/rss"]["suggestion"] == "demote"
    assert by_url["https://b.example/rss"]["lastReadAt"] is not None
    assert by_url["https://d.example/rss"]["lastReadAt"] is None
    assert "本服务器没有记录" in by_url["https://d.example/rss"]["basis"]


def test_low_yield_feeds_are_excluded(client, db):
    from lumirss.source_cleanup import build_suggestions

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_projection(db, "https://quiet.example/rss", 1, now)
    _seed_read(db, "https://quiet.example/rss", _iso(120 * 86400))
    result = _run(
        build_suggestions(db, _subs("https://quiet.example/rss"), min_weekly_yield=1.0)
    )
    assert result["items"] == [], "低产来源（<1 条/周）不值得建议"


def test_suggestions_route_read_only(client, db):
    """GET 不产生任何写副作用（无覆盖行、无 move 调用）。"""

    class SpyControl:
        def __init__(self):
            self.moves = 0

        async def list_subscriptions(self):
            return _subs("https://a.example/rss")

        async def move_to_new_category(self, *args):
            self.moves += 1

    spy = SpyControl()
    client.app.state.freshrss_control_adapter = spy
    try:
        _seed_projection(db, "https://a.example/rss", 12, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        _seed_read(db, "https://a.example/rss", _iso(100 * 86400))
        response = client.get("/api/v1/sources/cleanup-suggestions")
        assert response.status_code == 200
        assert response.json()["items"]
        assert spy.moves == 0, "建议只读：绝不自动执行"
        rows = _run(
            db.fetch_all("SELECT feed_url FROM source_overrides WHERE hidden_until IS NOT NULL", ())
        )
        assert rows == [], "建议只读：绝不写覆盖"
    finally:
        client.app.state.freshrss_control_adapter = None


def test_apply_mute_touches_only_selected(client, db):
    from lumirss.source_overrides import SourceOverrideStore

    class SpyControl:
        async def list_subscriptions(self):
            return _subs("https://a.example/rss", "https://b.example/rss")

    client.app.state.freshrss_control_adapter = SpyControl()
    try:
        response = client.post(
            "/api/v1/sources/cleanup-suggestions/apply",
            json={"feedUrls": ["https://a.example/rss"], "action": "mute"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["applied"] == 1
        # 只选中项被静音
        muted = _run(
            db.fetch_all(
                "SELECT feed_url FROM source_overrides WHERE hidden_until IS NOT NULL", ()
            )
        )
        assert [row["feed_url"] for row in muted] == ["https://a.example/rss"]
        # 未选中项无任何行
        other = _run(
            SourceOverrideStore(db).get_override("https://b.example/rss")
        )
        assert other is None
    finally:
        client.app.state.freshrss_control_adapter = None


def test_apply_demote_uses_move_channel(client):
    class SpyControl:
        def __init__(self):
            self.moves: list[tuple[str, str]] = []

        async def list_subscriptions(self):
            return _subs("https://a.example/rss")

        async def move_to_new_category(self, stream_id, label):
            self.moves.append((stream_id, label))

    spy = SpyControl()
    client.app.state.freshrss_control_adapter = spy
    try:
        response = client.post(
            "/api/v1/sources/cleanup-suggestions/apply",
            json={
                "feedUrls": ["https://a.example/rss"],
                "action": "demote_category",
                "targetCategoryLabel": "低优先级",
            },
        )
        assert response.status_code == 200
        assert response.json()["applied"] == 1
        assert spy.moves == [("feed/0", "低优先级")]
    finally:
        client.app.state.freshrss_control_adapter = None


def test_apply_rejects_unsubscribed_and_bad_action(client):
    class SpyControl:
        async def list_subscriptions(self):
            return _subs("https://a.example/rss")

    client.app.state.freshrss_control_adapter = SpyControl()
    try:
        unknown = client.post(
            "/api/v1/sources/cleanup-suggestions/apply",
            json={"feedUrls": ["https://ghost.example/rss"], "action": "mute"},
        )
        assert unknown.status_code == 200
        assert unknown.json()["items"][0]["error"] == "not_subscribed"
        bad = client.post(
            "/api/v1/sources/cleanup-suggestions/apply",
            json={"feedUrls": ["https://a.example/rss"], "action": "unsubscribe"},
        )
        assert bad.status_code == 400, "不存在自动退订动作（稳定拒绝）"
        no_label = client.post(
            "/api/v1/sources/cleanup-suggestions/apply",
            json={"feedUrls": ["https://a.example/rss"], "action": "demote_category"},
        )
        assert no_label.status_code == 400
    finally:
        client.app.state.freshrss_control_adapter = None


def test_record_feed_read_projects_last_read_at(client, db):
    from lumirss.source_cleanup import record_feed_read

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_projection(db, "https://a.example/rss", 1, now)
    _run(record_feed_read(db, "https://a.example/rss#0"))
    _run(record_feed_read(db, "https://a.example/rss#0"))
    row = _run(
        db.fetch_one("SELECT last_read_at, read_total FROM feed_read_stats WHERE feed_url = ?", ("https://a.example/rss",))
    )
    assert row is not None
    assert row["read_total"] == 2
    # 投影未命中的 ref 诚实跳过（不报错、不编造）
    _run(record_feed_read(db, "https://missing.example/rss#9"))
    missing = _run(
        db.fetch_one("SELECT feed_url FROM feed_read_stats WHERE feed_url = ?", ("https://missing.example/rss",))
    )
    assert missing is None
