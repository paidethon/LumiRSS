"""F12 订阅收件量概览 — 口径与未知值语义测试。

- 投影覆盖的订阅：publishedCount/lastPublishedAt 来自窗口聚合；
- 投影未覆盖的订阅：publishedCount=null（投影落后 ≠ 没有新内容），
  绝不冒充 0；
- days 越界收敛到 [1,30]。
"""

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
                "2026-09-17T10:00:00Z",
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
                "2026-01-01T00:00:00Z",
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
    assert covered["lastPublishedAt"] == "2026-09-17T10:00:00Z"
    assert covered["lastSyncedAt"] is not None
    uncovered = items["https://uncovered.example.com/rss"]
    assert uncovered["publishedCount"] is None, "投影未覆盖 → 未知，不是 0"
    assert uncovered["lastSyncedAt"] is None


def test_volume_days_clamped(client):
    _install_adapter(["https://x.example.com/rss"])
    response = client.get("/api/v1/sources/volume?days=999")
    assert response.status_code == 200
    assert response.json()["days"] == 30
