"""F032/F034/F031 — 来源元数据（语言/未读警戒阈值/同步优先级）。

sentinel 语义：缺席=不改、null=清除、值=设置；三维度互不覆盖。
F034 的投影未读数随 volume 端点下发（未覆盖 → null 不冒充零）。"""

import asyncio

import pytest

from lumirss.main import app

FEED = "https://meta.example.com/rss"


@pytest.fixture()
def meta_client(client, monkeypatch):
    async def _install():
        db = app.state.db
        await db.migrate()
        subs = [
            type("S", (), {"stream_id": "s0", "feed_url": FEED, "title": "Meta 源"})()
        ]

        async def _list():
            return subs

        app.state.freshrss_adapter = type("A", (), {"list_subscriptions": staticmethod(_list)})()

    asyncio.run(_install())
    return client


def _put(client, body):
    return client.put("/api/v1/sources/overrides", json={"feedUrl": FEED, **body})


def test_metadata_sentinel_semantics(meta_client):
    response = _put(meta_client, {"language": "zh", "unreadAlertThreshold": 100, "syncPriority": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["language"] == "zh"
    assert body["unreadAlertThreshold"] == 100
    assert body["syncPriority"] == 1

    # 缺席维度不被覆盖
    response = _put(meta_client, {"language": "en"})
    body = response.json()
    assert body["language"] == "en"
    assert body["unreadAlertThreshold"] == 100
    assert body["syncPriority"] == 1

    # null 显式清除单维度
    response = _put(meta_client, {"syncPriority": None})
    body = response.json()
    assert body["syncPriority"] is None
    assert body["language"] == "en"


def test_metadata_validation(meta_client):
    assert _put(meta_client, {"language": "中文"}).status_code == 422
    assert _put(meta_client, {"unreadAlertThreshold": 0}).status_code == 422
    assert _put(meta_client, {"syncPriority": 5}).status_code == 422


def test_volume_carries_projected_unread(meta_client):
    db = app.state.db

    async def _seed():
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("i1", "e1", FEED, "Meta 源", "A", "", "", "", "2026-09-20T00:00:00Z", 0, 0, 1789660000),
        )
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("i2", "e2", FEED, "Meta 源", "B", "", "", "", "2026-09-21T00:00:00Z", 1, 0, 1789660001),
        )

    asyncio.run(_seed())
    response = meta_client.get("/api/v1/sources/volume?days=30&daily=true")
    assert response.status_code == 200
    items = {item["feedUrl"]: item for item in response.json()["items"]}
    assert items[FEED]["unreadProjected"] == 1, "未读=投影 read=0 计数"
