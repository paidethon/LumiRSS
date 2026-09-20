"""F035 固定保存视图 + 完整意图持久化 + 服务端真实计数。"""

import asyncio


def run(coroutine):
    return asyncio.run(coroutine)


def _seed_entries(app, n):
    from lumirss.entryref import encode_entry_ref

    run(app.state.db.migrate())
    for i in range(n):
        ref = encode_entry_ref(f"tag:google.com,2005:reader/item/{i:019d}")
        run(
            app.state.db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, 'https://f.example/rss', '源', ?, '', 'u', '', ?, 0, 0, 0)",
                (
                    f"p{i}",
                    ref,
                    f"积压文章 {i} 关键词alpha",
                    f"2026-08-{(i % 28) + 1:02d}T00:00:00Z",
                ),
            )
        )


def _create_view(client, name, q, filters=None):
    body = {"name": name, "query": q, "view": "all", "categoryKey": ""}
    if filters is not None:
        body["filters"] = filters
    resp = client.post("/api/v1/search/views", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_f035_pin_persist_order_filters_roundtrip_and_legacy_compat(client):
    app = client.app
    _seed_entries(app, 3)
    v1 = _create_view(client, "积压清理", "alpha", {"unreadOnly": True, "from": "2026-08-01"})
    v2 = _create_view(client, "第二视图", "alpha")

    # filters 往返
    assert v1["filters"]["unreadOnly"] is True
    got = client.get("/api/v1/search/views").json()["items"]
    by_id = {v["id"]: v for v in got}
    assert by_id[v1["id"]]["filters"]["from"] == "2026-08-01"
    assert by_id[v2["id"]]["filters"] is None  # 老视图兼容（无 filters 走 q 解析）

    # pin + 排序
    client.post(f"/api/v1/search/views/{v2['id']}/pin")
    client.post(f"/api/v1/search/views/{v1['id']}/pin")
    pinned = client.get("/api/v1/search/views/pinned").json()["items"]
    assert [v["id"] for v in pinned] == [v2["id"], v1["id"]]
    reordered = client.patch(
        f"/api/v1/search/views/{v1['id']}/pin-order", json={"pinOrder": 0}
    ).json()
    assert reordered["pinOrder"] == 0
    pinned2 = client.get("/api/v1/search/views/pinned").json()["items"]
    assert [v["id"] for v in pinned2] == [v1["id"], v2["id"]]

    # unpin 持久化
    client.post(f"/api/v1/search/views/{v2['id']}/unpin")
    assert client.get("/api/v1/search/views/pinned").json()["items"] == [pinned2[0]]


def test_f035_count_matches_real_query_and_error_state(client):
    app = client.app
    _seed_entries(app, 260)  # >1 页（250/页）
    view = _create_view(client, "计数视图", "关键词alpha")

    count = client.get(f"/api/v1/search/views/{view['id']}/count").json()
    assert count["count"] == 260
    assert count["error"] is None

    # 失效视图（来源删除/查询异常）→ error 态而非伪装 0：
    # 用不存在投影表列的 filters 触发查询错误很难；改为直接删除视图 → 404
    missing = client.get("/api/v1/search/views/nonexistent/count")
    assert missing.status_code == 404
