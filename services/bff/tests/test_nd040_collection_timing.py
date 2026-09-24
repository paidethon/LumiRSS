"""N040 采集延迟解释 — source volume 的三时点块与最大环节提示。

- 三个时点各自来自真实来源：上游 published_at / FreshRSS
  crawlTimestampMsec（首次收录）/ Lumi 投影 fetched_at；
- FreshRSS 未提供收录时刻 → 该行为 null + 「未提供 by upstream」
  （诚实优于臆造）；
- latencyHint 指出最大缺口环节；数据不足 → null。
"""

import asyncio

from lumirss.main import app


def _install_adapter(feed_urls: list[str]):
    import types

    subs = [
        types.SimpleNamespace(stream_id=f"s{i}", feed_url=url, title=f"源 {i}")
        for i, url in enumerate(feed_urls)
    ]

    async def _list():
        return subs

    app.state.freshrss_adapter = types.SimpleNamespace(list_subscriptions=_list)


def test_three_timestamps_with_distinct_times(client):
    _install_adapter(["https://t.example/rss"])

    async def _seed():
        db = app.state.db
        await db.migrate()
        # 发布 09-01，FreshRSS 首次收录 09-02（+1d），Lumi 投影 09-04（+2d）
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at, crawled_at) VALUES ('i1','e1.aTE','https://t.example/rss','源','t','','','','2026-09-01T00:00:00Z',0,0, ?, ?)",
            (1789660000, "2026-09-02T00:00:00Z"),
        )
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at, crawled_at) VALUES ('i2','e1.aTI','https://t.example/rss','源','t2','','','','2026-09-03T00:00:00Z',0,0, ?, ?)",
            (1789660002, "2026-09-03T12:00:00Z"),
        )

    asyncio.run(_seed())
    body = client.get("/api/v1/sources/volume?days=7").json()
    item = next(i for i in body["items"] if i["feedUrl"] == "https://t.example/rss")
    timing = item["collectionTiming"]
    assert timing is not None
    assert timing["upstreamPublishedLatest"] == "2026-09-03T00:00:00Z"
    assert timing["freshrssFetchedLatest"] == "2026-09-03T12:00:00Z"
    assert "首次收录" in timing["freshrssFetchedBasis"], "口径诚实标注（非周期抓取）"
    assert timing["lumiProjectedLatest"] is not None
    assert timing["latencyHint"] is not None
    assert "上游发布" in timing["latencyHint"] or "收录" in timing["latencyHint"]


def test_missing_upstream_crawl_is_null_not_invented(client):
    _install_adapter(["https://n.example/rss"])

    async def _seed():
        db = app.state.db
        await db.migrate()
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at, crawled_at) VALUES ('i1','e1.aTE','https://n.example/rss','源','t','','','','2026-09-01T00:00:00Z',0,0, 1789660000, NULL)"
        )

    asyncio.run(_seed())
    body = client.get("/api/v1/sources/volume?days=7").json()
    timing = body["items"][0]["collectionTiming"]
    assert timing["freshrssFetchedLatest"] is None, "上游未提供 → null，不臆造"
    assert timing["freshrssFetchedBasis"] == "未提供 by upstream"
    assert timing["latencyHint"] is None, "缺中间时点 → 无法算环节，保持 null"


def test_unprojected_source_has_null_timing(client):
    _install_adapter(["https://empty.example/rss"])
    body = client.get("/api/v1/sources/volume?days=7").json()
    item = body["items"][0]
    assert item["collectionTiming"] is None
    assert item["publishedCount"] is None
