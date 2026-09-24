"""F12 订阅收件量概览 — 口径与未知值语义测试。

- 投影覆盖的订阅：publishedCount/lastPublishedAt 来自窗口聚合；
- 投影未覆盖的订阅：publishedCount=null（投影落后 ≠ 没有新内容），
  绝不冒充 0；
- days 越界收敛到 [1,30]。
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from lumirss.main import app


def _install_adapter(feed_urls: list[str]):
    subs = [
        SimpleNamespace(stream_id=f"s{i}", feed_url=url, title=f"源 {i}")
        for i, url in enumerate(feed_urls)
    ]

    async def _list():
        return subs

    app.state.freshrss_adapter = SimpleNamespace(list_subscriptions=_list)


def test_volume_counts_and_unknown_semantics(client, monkeypatch):
    _install_adapter(["https://covered.example.com/rss", "https://uncovered.example.com/rss"])
    db = app.state.db
    import asyncio

    # 窗口内/窗口外发布时间都相对 now 计算：硬编码日期会随真实时间
    # 滚出 days=7 窗口（时间炸弹），这里保证测试语义永远成立。
    now = datetime.now(UTC)
    in_window = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_window = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def _seed():
        await db.migrate()
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "i1",
                "e1.a",
                "https://covered.example.com/rss",
                "覆盖源",
                "A",
                "",
                "",
                "",
                in_window,
                0,
                0,
                1789660000,
            ),
        )
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "i2",
                "e1.b",
                "https://covered.example.com/rss",
                "覆盖源",
                "B",
                "",
                "",
                "",
                out_window,
                0,
                0,
                1789660001,
            ),
        )

    asyncio.run(_seed())

    response = client.get("/api/v1/sources/volume?days=7")
    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 7
    items = {item["feedUrl"]: item for item in body["items"]}
    covered = items["https://covered.example.com/rss"]
    assert covered["publishedCount"] == 1, "窗口外发布不计入"
    assert covered["lastPublishedAt"] == in_window
    assert covered["lastSyncedAt"] is not None
    uncovered = items["https://uncovered.example.com/rss"]
    assert uncovered["publishedCount"] is None, "投影未覆盖 → 未知，不是 0"
    assert uncovered["lastSyncedAt"] is None


def test_volume_days_clamped(client):
    _install_adapter(["https://x.example.com/rss"])
    response = client.get("/api/v1/sources/volume?days=999")
    assert response.status_code == 200
    assert response.json()["days"] == 30


def test_volume_daily_buckets_sparse_semantics(client, monkeypatch):
    """F024：daily=true 附按天分桶；窗口外日期不计；未覆盖源为 null。"""
    _install_adapter(["https://covered.example.com/rss", "https://uncovered.example.com/rss"])
    db = app.state.db
    import asyncio

    now = datetime.now(UTC)
    day_a = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    day_b = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    out_window = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def _seed():
        await db.migrate()
        for day, n in ((day_a, 3), (day_b, 1)):
            for i in range(n):
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"i-{day}-{i}",
                        f"e-{day}-{i}",
                        "https://covered.example.com/rss",
                        "覆盖源",
                        "A",
                        "",
                        "",
                        "",
                        f"{day}T10:0{i}:00Z",
                        0,
                        0,
                        1789660000 + i,
                    ),
                )
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "i-old",
                "e-old",
                "https://covered.example.com/rss",
                "覆盖源",
                "OLD",
                "",
                "",
                "",
                out_window,
                0,
                0,
                1789660009,
            ),
        )

    asyncio.run(_seed())

    default_response = client.get("/api/v1/sources/volume?days=30")
    assert default_response.status_code == 200
    assert default_response.json()["items"][0]["daily"] is None, "默认不带分桶"

    response = client.get("/api/v1/sources/volume?days=30&daily=true")
    assert response.status_code == 200
    items = {item["feedUrl"]: item for item in response.json()["items"]}
    covered = items["https://covered.example.com/rss"]
    assert covered["publishedCount"] == 4
    buckets = {bucket["date"]: bucket["count"] for bucket in covered["daily"]}
    assert buckets == {day_a: 3, day_b: 1}, "窗口外不计、按日聚合"
    uncovered = items["https://uncovered.example.com/rss"]
    assert uncovered["daily"] is None, "投影未覆盖 → 未知"
