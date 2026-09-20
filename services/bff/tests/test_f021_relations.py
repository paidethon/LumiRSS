"""F021 手工关联内容 —— 双向查询、重复冲突、解除、跨域 ref 与 stale 标记。

纯手工元数据：全程无 AI 参与（不构造 provider，也不需要）。
"""

import asyncio
import uuid


def run(coroutine):
    return asyncio.run(coroutine)


def _seed_rss_entry(app, item_id: str, title: str) -> str:
    """在派生投影里放一条 RSS 条目，让 rss: ref 可解析（registry 先查
    search_entries；FreshRSS 不参与）。"""
    from lumirss.entryref import encode_entry_ref

    run(app.state.db.migrate())
    entry_ref = encode_entry_ref(item_id)
    run(
        app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, url, content_text, published_at, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                item_id,
                entry_ref,
                "https://example.test/feed.xml",
                "示例源",
                title,
                "https://example.test/a",
                f"{title} 的正文",
                "2026-09-01T00:00:00Z",
            ),
        )
    )
    return f"rss:{entry_ref}"


def _seed_bookmark(client) -> str:
    response = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.test/page", "title": "收藏页"},
    )
    assert response.status_code == 201, response.text
    return response.json()["ref"]


def test_f021_create_list_bidirectional_duplicate_and_self(client):
    app = client.app
    a = _seed_rss_entry(app, "item-a", "文章甲")
    b = _seed_rss_entry(app, "item-b", "文章乙")

    created = client.post(
        "/api/v1/relations",
        json={"srcRef": a, "dstRef": b, "note": "同一事件的两面"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["srcRef"] == a and body["dstRef"] == b
    assert body["stale"] is False

    # 双向：从任一端都能查到
    from_a = client.get("/api/v1/relations", params={"itemRef": a})
    from_b = client.get("/api/v1/relations", params={"itemRef": b})
    assert from_a.status_code == 200 and from_b.status_code == 200
    assert len(from_a.json()["items"]) == 1
    assert len(from_b.json()["items"]) == 1

    # 同向同备注 → 幂等（同一行）
    again = client.post(
        "/api/v1/relations",
        json={"srcRef": a, "dstRef": b, "note": "同一事件的两面"},
    )
    assert again.status_code == 201
    assert again.json()["id"] == body["id"]

    # 同向不同备注 → 409 relation_duplicate
    conflict = client.post(
        "/api/v1/relations",
        json={"srcRef": a, "dstRef": b, "note": "另一个说法"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["type"] == "relation_duplicate"

    # 反向允许（方向有意义）
    reverse = client.post(
        "/api/v1/relations", json={"srcRef": b, "dstRef": a}
    )
    assert reverse.status_code == 201

    # 自关联 → 422 invalid_relation
    self_ref = client.post("/api/v1/relations", json={"srcRef": a, "dstRef": a})
    assert self_ref.status_code == 422
    assert self_ref.json()["error"]["type"] == "invalid_relation"

    # 无 AI 参与：整个流程只触手工写入端点（无 provider 构造痕迹）
    assert app.state.summary_service is None


def test_f021_delete_and_cross_domain_refs(client):
    app = client.app
    rss_ref = _seed_rss_entry(app, "item-cross", "RSS 文章")
    lib_ref = _seed_bookmark(client)

    created = client.post(
        "/api/v1/relations",
        json={"srcRef": rss_ref, "dstRef": lib_ref, "note": "原文-收藏"},
    )
    assert created.status_code == 201, created.text
    relation_id = created.json()["id"]
    view = created.json()
    assert {view["src"]["domain"], view["dst"]["domain"]} == {"rss", "library"}

    # 解除
    deleted = client.delete(f"/api/v1/relations/{relation_id}")
    assert deleted.status_code == 204
    # 再解除 → 404
    missing = client.delete(f"/api/v1/relations/{relation_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "relation_not_found"
    assert client.get(
        "/api/v1/relations", params={"itemRef": rss_ref}
    ).json()["items"] == []


def test_f021_stale_marking_keeps_relation(client):
    app = client.app
    rss_ref = _seed_rss_entry(app, "item-stale", "会失效的文章")
    lib_ref = _seed_bookmark(client)
    created = client.post(
        "/api/v1/relations", json={"srcRef": rss_ref, "dstRef": lib_ref}
    )
    assert created.status_code == 201
    assert created.json()["stale"] is False

    # 目标被删除（RSS 条目失效 = 投影行被清）→ 关系保留但 stale:true
    run(
        app.state.db.execute(
            "DELETE FROM search_entries WHERE item_id = ?", ("item-stale",)
        )
    )
    listing = client.get("/api/v1/relations", params={"itemRef": lib_ref})
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["stale"] is True
    stale_end = items[0]["src"]
    assert stale_end["stale"] is True and stale_end["staleReason"] == "not_found"


def test_f021_graph_contains_manual_edges(client):
    app = client.app
    a = _seed_rss_entry(app, "item-g1", "图谱甲")
    b = _seed_rss_entry(app, "item-g2", "图谱乙")
    created = client.post("/api/v1/relations", json={"srcRef": a, "dstRef": b})
    assert created.status_code == 201

    graph = client.get("/api/v1/graph", params={"scope": "all"}).json()
    manual = [edge for edge in graph["edges"] if edge["kind"] == "manual"]
    assert manual and {manual[0]["src"], manual[0]["dst"]} == {a, b}
    _ = uuid  # keep import honest
