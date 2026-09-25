"""E1: N047 快速筛除已收录链接（服务端）。

- canonical URL（url_normalize：host 小写、去尾斜杠、丢追踪参数）
  撞车 → 响应附 duplicateWarning（非阻断：条目已加入）；
- 不同 URL 即使标题相似也绝不提示（无标题相似度合并）；
- 「仍要加入」= 无操作（条目本来就已加入，warning 只提示）。
"""

import asyncio

from lumirss.entryref import encode_entry_ref


def run(coroutine):
    return asyncio.run(coroutine)


def _seed(
    app,
    item_id: str,
    *,
    url: str,
    title: str = "t",
    published_at: str = "2026-09-20T00:00:00Z",
):
    entry_ref = encode_entry_ref(item_id)
    run(
        app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url,"
            " feed_title, title, author, url, content_text, published_at, read,"
            " starred, fetched_at) VALUES (?, ?, 'https://f.example/rss', '源',"
            " ?, '', ?, 'c', ?, 0, 0, 0)",
            (item_id, entry_ref, title, url, published_at),
        )
    )
    return f"rss:{entry_ref}"


def test_n047_canonical_match_warns_and_insist_still_added(client):
    app = client.app
    run(app.state.db.migrate())
    # 队列已有 A：utm 追踪参数差异是同一 canonical。
    ref_a = _seed(app, "la", url="https://ex.com/post/1?utm_source=feed")
    client.post("/api/v1/queue/today/items", json={"itemRef": ref_a})

    # 加入 B：同 canonical（仅差追踪参数）→ 200（已加入）+ warning。
    ref_b = _seed(app, "lb", url="https://EX.com/post/1/")
    response = client.post("/api/v1/queue/today/items", json={"itemRef": ref_b})
    assert response.status_code == 201, response.text
    body = response.json()
    warning = body["duplicateWarning"]
    assert warning is not None
    assert warning["duplicateOf"]["ref"] == ref_a
    assert warning["duplicateOf"]["scope"] == "queue"
    # 非阻断：B 已真实在队列里（「仍要加入」= 接受提示即可）。
    view = client.get("/api/v1/queue/today").json()
    refs = {item["itemRef"] for item in view["items"]}
    assert ref_a in refs and ref_b in refs


def test_n047_different_content_never_merged(client):
    app = client.app
    run(app.state.db.migrate())
    ref_a = _seed(app, "da", url="https://ex.com/post/1", title="同一标题")
    client.post("/api/v1/queue/today/items", json={"itemRef": ref_a})
    # 标题完全相同但 URL 不同 → 绝不提示（无标题相似度合并）。
    ref_c = _seed(app, "dc", url="https://ex.com/post/2", title="同一标题")
    response = client.post("/api/v1/queue/today/items", json={"itemRef": ref_c})
    assert response.status_code == 201
    assert response.json()["duplicateWarning"] is None


def test_n047_workspace_add_warns_on_queue_collision(client):
    app = client.app
    run(app.state.db.migrate())
    ref_a = _seed(app, "wa", url="https://ex.com/article/9")
    client.post("/api/v1/queue/today/items", json={"itemRef": ref_a})

    workspace = client.post(
        "/api/v1/workspaces", json={"name": "收录测试"}
    ).json()
    ref_b = _seed(app, "wb", url="https://ex.com/article/9?fbclid=x")
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/items",
        json={"itemRef": ref_b},
    )
    assert response.status_code == 201, response.text
    warning = response.json()["duplicateWarning"]
    assert warning is not None
    assert warning["duplicateOf"]["ref"] == ref_a
    assert warning["duplicateOf"]["scope"] == "queue"


def test_n047_no_url_or_no_candidates_no_warning(client):
    app = client.app
    run(app.state.db.migrate())
    # 投影无 URL（空 url 列）→ 无法归一化 → 不提示。
    ref_no_url = _seed(app, "nu", url="")
    response = client.post("/api/v1/queue/today/items", json={"itemRef": ref_no_url})
    assert response.status_code == 201
    assert response.json()["duplicateWarning"] is None
