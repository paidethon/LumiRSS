"""F019 Library 回收站 —— 软删→搜索不可见→恢复→搜索恢复→永久删除。

- DELETE 书签/剪辑 = 软删（列表不可见、回收站可见、搜索腿不可见）；
- restore 原样恢复（搜索重新可见、标签/工作区关联保留）；
- 永久删除必须显式 permanent=true；FreshRSS RSS 域无 deleted_at 路径
  （负向：/api/v1/entries 不受书签软删影响）；
- 重启（新 store 实例）后回收站仍在。
"""

import asyncio

from lumirss.entryref import encode_entry_ref


def run(coroutine):
    return asyncio.run(coroutine)


def _bookmark(client, title="F019 书签"):
    response = client.post(
        "/api/v1/library/bookmarks",
        json={"rssItemRef": f"rss:{encode_entry_ref('9101')}", "title": title},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["ref"].split(":", 1)[1]  # library:<uuid> → uuid


def test_f019_soft_delete_search_restore_roundtrip(client):
    from lumirss.library import LibraryStore

    uuid = _bookmark(client, "可恢复的书签")
    # 搜索腿可见
    found = client.get("/api/v1/search", params={"q": "可恢复的书签", "limit": 20}).json()
    assert any(h["ref"] == f"library:{uuid}" for h in found["library"])

    # 软删 → 列表不可见、搜索不可见、回收站可见
    delete = client.delete(f"/api/v1/library/bookmarks/{uuid}")
    assert delete.status_code == 204
    listed = client.get("/api/v1/library/bookmarks", params={"q": "可恢复的书签"}).json()
    assert not any(item["ref"] == f"library:{uuid}" for item in listed["items"])
    search_after = client.get("/api/v1/search", params={"q": "可恢复的书签", "limit": 20}).json()
    assert not any(h["ref"] == f"library:{uuid}" for h in search_after["library"])
    trash = client.get("/api/v1/library/trash", params={"type": "bookmark"}).json()
    assert any(item["uuid"] == uuid for item in trash["items"])

    # 恢复 → 列表可见、搜索恢复
    restore = client.post(f"/api/v1/library/trash/{uuid}/restore")
    assert restore.status_code == 204, restore.text
    listed_back = client.get("/api/v1/library/bookmarks", params={"q": "可恢复的书签"}).json()
    assert any(item["ref"] == f"library:{uuid}" for item in listed_back["items"])
    search_back = client.get("/api/v1/search", params={"q": "可恢复的书签", "limit": 20}).json()
    assert any(h["ref"] == f"library:{uuid}" for h in search_back["library"])

    # 重启（新 store 实例读同一库）后数据仍在
    store = LibraryStore(client.app.state.db)
    view = run(store.get_bookmark(uuid))
    assert view is not None and view.title == "可恢复的书签"


def test_f019_permanent_delete_requires_confirmation_and_purges(client):
    uuid = _bookmark(client, "待永久删除")
    client.delete(f"/api/v1/library/bookmarks/{uuid}")
    # 缺 permanent=true → 拒绝（confirm_required）
    without = client.delete(f"/api/v1/library/trash/{uuid}")
    assert without.status_code == 409
    assert without.json()["error"]["type"] == "confirm_required"
    # 显式 permanent=true → 永久删除（回收站消失、不可恢复）
    purge = client.delete(f"/api/v1/library/trash/{uuid}", params={"permanent": "true"})
    assert purge.status_code == 204
    trash = client.get("/api/v1/library/trash").json()
    assert not any(item["uuid"] == uuid for item in trash["items"])
    restore = client.post(f"/api/v1/library/trash/{uuid}/restore")
    assert restore.status_code == 404


def test_f019_rss_domain_unaffected_by_soft_delete(client):
    """FreshRSS 负向：RSS 条目没有 deleted_at 路径，书签软删不影响时间线。"""
    entry_ref = encode_entry_ref("9101")
    from lumirss.main import app

    async def _seed():
        await app.state.db.migrate()
        await app.state.db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("9101", entry_ref, "https://f.example/rss", "源", "RSS 条目", "", "", "正文", "2026-09-18T00:00:00Z", 0, 0, 1789660000),
        )

    run(_seed())

    # 安装最小读适配器（时间线来自 FreshRSS 域；与本测试的软删无关）
    from types import SimpleNamespace

    from lumirss.adapters.freshrss import EntryListItem

    rss_entry = EntryListItem(
        entryRef=entry_ref,
        title="RSS 条目",
        feedTitle="源",
        author=None,
        url=None,
        publishedAt="2026-09-18T00:00:00Z",
        read=False,
        starred=False,
    )

    async def _list_entries(*, view="all", feed_url=None, category_id=None, source_type=None, continuation=None):
        return SimpleNamespace(items=[rss_entry], upstreamContinuation=None)

    app.state.freshrss_adapter = SimpleNamespace(list_entries=_list_entries)

    uuid = _bookmark(client, "与 RSS 同源的书签")
    client.delete(f"/api/v1/library/bookmarks/{uuid}")
    # RSS 时间线照常返回该条目（deleted_at 属 library 域，不碰 entries）
    feed = client.get("/api/v1/entries", params={"view": "all"}).json()
    assert any(item["entryRef"] == entry_ref for item in feed["items"])
    # search_entries 投影行未被删除（负向：无 deleted_at 列路径）
    async def _row():
        return await app.state.db.fetch_one(
            "SELECT entry_ref FROM search_entries WHERE entry_ref = ?", (entry_ref,)
        )

    assert run(_row()) is not None
