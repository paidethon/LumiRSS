"""N041 今日必读队列 + N042 分段 + N043 冻结快照 + N044 完成过滤（服务端）。

- N041：生成（未读+近期候选、预算粗估装填、诚实 basis）→ 修订式幂等
  （CRITICAL：再次 generate 绝不重排已确认队列；force 才重建且保留
  done、绝不复活 removed）→ 手动加入（重复幂等/done 409/removed 复活）
  → 移除/完成（set 语义）/重排持久化；
- N042：段标签（行级派生）+ 段顺序（meta JSON，服务端存储跨设备）+
  行菜单移动分段；
- N043：冻结快照不可变（冻结后新项绝不进入、消失 ref 原样返回由
  Web 呈现占位）+ 原始成员顺序 + 列表/校验/上限；
- N044：完成状态按条目身份记账在服务端；读取侧过滤不动任何记录
  （GET 恒返回 pending+done，重复读取状态不变）。
"""

import asyncio

from lumirss.entryref import encode_entry_ref


def run(coroutine):
    return asyncio.run(coroutine)


def _seed(
    app,
    item_id: str,
    *,
    read: int = 0,
    published_at: str,
    title: str = "t",
    content_text: str = "",
) -> str:
    """向 search_entries 投影插入一条未读条目；返回 rss:<entryRef>。"""
    entry_ref = encode_entry_ref(item_id)
    run(
        app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url,"
            " feed_title, title, author, url, content_text, published_at, read,"
            " starred, fetched_at) VALUES (?, ?, 'https://f.example/rss', '源',"
            " ?, '', 'u', ?, ?, ?, 0, 0)",
            (item_id, entry_ref, title, content_text, published_at, read),
        )
    )
    return f"rss:{entry_ref}"


def _generate(client, **json_extra):
    return client.post("/api/v1/queue/today/generate", json={"timeBudgetMinutes": 30, **json_extra})


def _items(body):
    return body["items"]


# ---- N041 生成 ----------------------------------------------------------------


def test_n041_generate_builds_from_unread_recency_under_budget(client):
    app = client.app
    run(app.state.db.migrate())
    # 新→旧：b1 最新；每条约 2 分钟（800 字符 / 400）。
    refs = {
        _seed(app, f"q{i}", published_at=f"2026-09-{20 - i:02d}T00:00:00Z",
              title=f"文{i}", content_text="字" * 800)
        for i in range(1, 4)
    }
    # 已读条目绝不进队列。
    _seed(app, "qread", published_at="2026-09-23T00:00:00Z", read=1)

    response = _generate(client, timeBudgetMinutes=5)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["generated"] is True
    assert body["basis"] == "unread+recency"
    assert body["budgetMinutes"] == 5
    assert body["queueDate"] == body["items"][0]["queueDate"]
    items = _items(body)
    assert len(items) == 2  # 预算 5 分钟，每条 2 分钟 → 装 2 条
    assert {item["itemRef"] for item in items} <= refs
    assert all(item["source"] == "budget" for item in items)
    assert all(item["status"] == "pending" for item in items)
    # 近期优先：最新发布的在前。
    assert items[0]["itemRef"].endswith(encode_entry_ref("q1"))
    # 估读来自投影（400 字符/分钟）。
    assert items[0]["estimateMinutes"] == 2


def test_n041_generate_again_returns_existing_queue_unchanged(client):
    """CRITICAL：后台刷新绝不重排已确认的队列（修订式幂等）。"""
    app = client.app
    run(app.state.db.migrate())
    for i in range(3):
        _seed(app, f"r{i}", published_at=f"2026-09-{20 - i:02d}T00:00:00Z",
              content_text="字" * 400)
    first = _generate(client).json()
    order_before = [item["id"] for item in _items(first)]

    # 确认后发生人为变化：完成一项、重排、手动加一项。
    done_id = order_before[0]
    assert client.post(f"/api/v1/queue/today/items/{done_id}/done", json={"done": True}).status_code == 200
    assert (
        client.put("/api/v1/queue/today/order", json={"order": list(reversed(order_before))}).status_code
        == 200
    )
    app_ref = _seed(app, "manual1", published_at="2026-09-23T00:00:00Z")
    added = client.post("/api/v1/queue/today/items", json={"itemRef": app_ref})
    assert added.status_code == 201

    again = _generate(client)
    assert again.status_code == 200
    body = again.json()
    assert body["generated"] is False
    items = _items(body)
    # 幂等：行集合与顺序原样（含手动项、done 状态），绝不重排。
    assert [item["id"] for item in items] == list(reversed(order_before)) + [added.json()["id"]]
    done_row = next(item for item in items if item["id"] == done_id)
    assert done_row["status"] == "done"


def test_n041_generate_force_rebuilds_but_keeps_done_never_revives_removed(client):
    app = client.app
    run(app.state.db.migrate())
    _seed(app, "f1", published_at="2026-09-20T00:00:00Z", content_text="字" * 400)
    _seed(app, "f2", published_at="2026-09-19T00:00:00Z", content_text="字" * 400)
    first = _generate(client).json()
    items = _items(first)
    done_id = items[0]["id"]

    # 完成 f1 → 手动加 f2 → 移除 f2。
    client.post(f"/api/v1/queue/today/items/{done_id}/done", json={"done": True})
    ref2 = f"rss:{encode_entry_ref('f2')}"
    added = client.post("/api/v1/queue/today/items", json={"itemRef": ref2}).json()
    assert client.delete(f"/api/v1/queue/today/items/{added['id']}").status_code == 204

    # force 重建：done（f1）保留且不重复装填；removed（f2）绝不复活；
    # 新未读 f3 进队列。
    _seed(app, "f3", published_at="2026-09-18T00:00:00Z", content_text="字" * 400)
    forced = client.post(
        "/api/v1/queue/today/generate?force=1", json={"timeBudgetMinutes": 30}
    )
    assert forced.status_code == 201
    body = forced.json()
    assert body["generated"] is True and body["force"] is True
    refs = [item["itemRef"] for item in _items(body)]
    statuses = {item["itemRef"]: item["status"] for item in _items(body)}
    assert ref2 not in refs  # removed 不复活
    assert refs.count(f"rss:{encode_entry_ref('f1')}") == 1  # done 保留、不重复
    assert statuses[f"rss:{encode_entry_ref('f1')}"] == "done"
    assert f"rss:{encode_entry_ref('f3')}" in refs


def test_n041_generate_empty_day_no_candidates(client):
    run(client.app.state.db.migrate())
    response = _generate(client)
    assert response.status_code == 201
    body = response.json()
    assert body["items"] == []
    assert body["generated"] is True


# ---- N041 手动加入 / 移除 / 完成 / 重排 -----------------------------------------


def test_n041_manual_add_duplicate_and_done_conflict(client):
    app = client.app
    run(app.state.db.migrate())
    ref = _seed(app, "m1", published_at="2026-09-20T00:00:00Z", title="手动文")

    created = client.post("/api/v1/queue/today/items", json={"itemRef": ref})
    assert created.status_code == 201
    item = created.json()
    assert item["source"] == "manual" and item["status"] == "pending"
    assert item["title"] == "手动文"

    duplicate = client.post("/api/v1/queue/today/items", json={"itemRef": ref})
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == item["id"]  # 幂等：同一行，不重排

    # done → 再加 → 409 queue_item_done（先取消完成）。
    client.post(f"/api/v1/queue/today/items/{item['id']}/done", json={"done": True})
    conflict = client.post("/api/v1/queue/today/items", json={"itemRef": ref})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["type"] == "queue_item_done"
    undone = client.post(f"/api/v1/queue/today/items/{item['id']}/done", json={"done": False})
    assert undone.status_code == 200
    assert undone.json()["status"] == "pending"  # set 语义

    # 非法 ref → 400 invalid_queue。
    bad = client.post("/api/v1/queue/today/items", json={"itemRef": "not-a-ref"})
    assert bad.status_code == 400
    assert bad.json()["error"]["type"] == "invalid_queue"


def test_n041_remove_then_readd_resurrects_at_tail(client):
    app = client.app
    run(app.state.db.migrate())
    ref1 = _seed(app, "x1", published_at="2026-09-20T00:00:00Z")
    ref2 = _seed(app, "x2", published_at="2026-09-19T00:00:00Z")
    first = client.post("/api/v1/queue/today/items", json={"itemRef": ref1}).json()
    second = client.post("/api/v1/queue/today/items", json={"itemRef": ref2}).json()

    assert client.delete(f"/api/v1/queue/today/items/{first['id']}").status_code == 204
    assert client.delete(f"/api/v1/queue/today/items/{first['id']}").status_code == 404
    view = client.get("/api/v1/queue/today").json()
    assert [item["id"] for item in _items(view)] == [second["id"]]  # removed 不出库门

    resurrected = client.post("/api/v1/queue/today/items", json={"itemRef": ref1})
    assert resurrected.status_code == 200
    assert resurrected.json()["id"] == first["id"]  # 同一行复活
    view = client.get("/api/v1/queue/today").json()
    assert [item["id"] for item in _items(view)] == [second["id"], first["id"]]  # 垫到队尾


def test_n041_manual_reorder_persisted(client):
    """N041 验收：手动重排持久化（服务端存储 → 跨设备）。"""
    app = client.app
    run(app.state.db.migrate())
    refs = [
        _seed(app, "o1", published_at="2026-09-20T00:00:00Z"),
        _seed(app, "o2", published_at="2026-09-19T00:00:00Z"),
        _seed(app, "o3", published_at="2026-09-18T00:00:00Z"),
    ]
    ids = [
        client.post("/api/v1/queue/today/items", json={"itemRef": ref}).json()["id"]
        for ref in refs
    ]
    reordered = client.put(
        "/api/v1/queue/today/order", json={"order": [ids[2], ids[0], ids[1]]}
    )
    assert reordered.status_code == 200
    assert [item["id"] for item in _items(reordered.json())] == [ids[2], ids[0], ids[1]]

    # 再读一次：持久化（不是响应内一次性）。
    again = client.get("/api/v1/queue/today").json()
    assert [item["id"] for item in _items(again)] == [ids[2], ids[0], ids[1]]
    # 未提及的 id 保持相对顺序垫后（契约）。
    partial = client.put("/api/v1/queue/today/order", json={"order": [ids[1]]})
    assert [item["id"] for item in _items(partial.json())] == [ids[1], ids[2], ids[0]]


def test_n041_generate_levels_and_workspace(client):
    app = client.app
    run(app.state.db.migrate())
    ref_in = _seed(app, "w1", published_at="2026-09-20T00:00:00Z", content_text="字" * 400)
    _seed(app, "w2", published_at="2026-09-19T00:00:00Z", content_text="字" * 400)
    created = client.post("/api/v1/workspaces", json={"name": "今日候选"})
    workspace_id = created.json()["id"]
    run(
        app.state.db.execute(
            "INSERT INTO workspace_items (workspace_id, item_ref, position, added_at)"
            " VALUES (?, ?, 1, '2026-09-20T00:00:00Z')",
            (workspace_id, ref_in),
        )
    )
    body = _generate(client, workspaceId=workspace_id, levels=["核心"]).json()
    refs = [item["itemRef"] for item in _items(body)]
    assert refs == [ref_in]  # 候选限定工作区成员
    # levels 诚实标注为已忽略（N020 未实现）。
    assert any("levels" in note for note in body["notes"])

    missing = _generate(client, workspaceId="ws-nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "workspace_not_found"


# ---- N042 分段 ----------------------------------------------------------------


def test_n042_segment_move_order_and_derived_groups(client):
    app = client.app
    run(app.state.db.migrate())
    refs = [
        _seed(app, "s1", published_at="2026-09-20T00:00:00Z"),
        _seed(app, "s2", published_at="2026-09-19T00:00:00Z"),
        _seed(app, "s3", published_at="2026-09-18T00:00:00Z"),
    ]
    items = []
    for ref in refs:
        items.append(client.post("/api/v1/queue/today/items", json={"itemRef": ref}).json())

    # 行菜单移动分段；新段名随行诞生。
    moved = client.patch(
        f"/api/v1/queue/today/items/{items[0]['id']}/segment", json={"segment": "晨读"}
    )
    assert moved.status_code == 200
    assert moved.json()["segment"] == "晨读"
    client.patch(f"/api/v1/queue/today/items/{items[1]['id']}/segment", json={"segment": "晚读"})

    view = client.get("/api/v1/queue/today").json()
    segments = {segment["name"]: [i["id"] for i in segment["items"]] for segment in view["segments"]}
    assert segments[None] == [items[2]["id"]]  # 未分组 = 隐式前置组
    assert segments["晨读"] == [items[0]["id"]]
    assert segments["晚读"] == [items[1]["id"]]

    # 段顺序持久化（服务端存储 → 跨设备一致）。
    ordered = client.put(
        "/api/v1/queue/today/segments", json={"order": ["晚读", "晨读"]}
    )
    assert ordered.status_code == 200
    names = [segment["name"] for segment in ordered.json()["segments"]]
    assert names == [None, "晚读", "晨读"]
    again = client.get("/api/v1/queue/today").json()
    assert [segment["name"] for segment in again["segments"]] == [None, "晚读", "晨读"]

    # 移回未分组（null）；段顺序 JSON 保留（呈现提示，不因清空丢序）。
    client.patch(
        f"/api/v1/queue/today/items/{items[0]['id']}/segment", json={"segment": None}
    )
    view = client.get("/api/v1/queue/today").json()
    assert view["segmentOrder"] == ["晚读", "晨读"]
    segments = {segment["name"]: [i["id"] for i in segment["items"]] for segment in view["segments"]}
    assert segments[None] == [items[0]["id"], items[2]["id"]]  # 组内按 position

    # 校验：空段名 / 越界 → 400 invalid_queue。
    bad = client.patch(
        f"/api/v1/queue/today/items/{items[0]['id']}/segment", json={"segment": "  "}
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["type"] == "invalid_queue"


# ---- N043 冻结快照 --------------------------------------------------------------


def test_n043_freeze_is_immutable_and_keeps_original_order(client):
    app = client.app
    run(app.state.db.migrate())
    refs = [
        _seed(app, "z1", published_at="2026-09-20T00:00:00Z"),
        _seed(app, "z2", published_at="2026-09-19T00:00:00Z"),
    ]
    items = []
    for ref in refs:
        items.append(client.post("/api/v1/queue/today/items", json={"itemRef": ref}).json())
    client.patch(
        f"/api/v1/queue/today/items/{items[1]['id']}/segment", json={"segment": "夜读"}
    )

    frozen = client.post("/api/v1/queue/today/freeze", json={"label": "早间批次"})
    assert frozen.status_code == 201
    snapshot = frozen.json()
    assert snapshot["itemCount"] == 2
    assert snapshot["queueDate"] == items[0]["queueDate"]

    # 冻结后：重排 + 新加入 + 完成一项 —— 冻结视图必须原样不变。
    client.put("/api/v1/queue/today/order", json={"order": [items[1]["id"], items[0]["id"]]})
    ref3 = _seed(app, "z3", published_at="2026-09-18T00:00:00Z")
    client.post("/api/v1/queue/today/items", json={"itemRef": ref3})
    client.post(f"/api/v1/queue/today/items/{items[0]['id']}/done", json={"done": True})

    detail = client.get(f"/api/v1/queue/snapshots/{snapshot['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["label"] == "早间批次"
    assert [item["itemRef"] for item in body["items"]] == [  # 原始成员顺序
        f"rss:{encode_entry_ref('z1')}",
        f"rss:{encode_entry_ref('z2')}",
    ]
    assert body["items"][1]["segment"] == "夜读"
    assert len(body["items"]) == 2  # 新加入的 z3 绝不进入冻结批次

    # 消失的条目：ref 原样返回（Web 用解析状态诚实呈现占位，服务端
    # 绝不复活、绝不补内容）。
    run(app.state.db.execute("DELETE FROM search_entries WHERE item_id = 'z2'"))
    after_delete = client.get(f"/api/v1/queue/snapshots/{snapshot['id']}").json()
    assert after_delete["items"][1]["itemRef"] == f"rss:{encode_entry_ref('z2')}"

    # 列表（新→旧）+ 删除 + 404。
    listed = client.get("/api/v1/queue/snapshots").json()["items"]
    assert [s["id"] for s in listed] == [snapshot["id"]]
    assert client.delete(f"/api/v1/queue/snapshots/{snapshot['id']}").status_code == 204
    assert (
        client.get(f"/api/v1/queue/snapshots/{snapshot['id']}").status_code == 404
    )


def test_n043_freeze_validation_and_unknown_snapshot(client):
    run(client.app.state.db.migrate())
    empty = client.post("/api/v1/queue/today/freeze", json={"label": "  "})
    assert empty.status_code == 400
    assert empty.json()["error"]["type"] == "invalid_queue"
    missing = client.get("/api/v1/queue/snapshots/qsnap-nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "queue_snapshot_not_found"


# ---- N044 只看未完成（读取侧过滤，服务端状态不受影响） ----------------------------


def test_n044_filter_is_read_side_only(client):
    """过滤永不删除记录：GET 恒返回 pending+done，重复读取状态不变。"""
    app = client.app
    run(app.state.db.migrate())
    refs = [
        _seed(app, "d1", published_at="2026-09-20T00:00:00Z"),
        _seed(app, "d2", published_at="2026-09-19T00:00:00Z"),
    ]
    items = []
    for ref in refs:
        items.append(client.post("/api/v1/queue/today/items", json={"itemRef": ref}).json())
    client.post(f"/api/v1/queue/today/items/{items[0]['id']}/done", json={"done": True})

    for _ in range(3):
        view = client.get("/api/v1/queue/today")
        assert view.status_code == 200
        statuses = {item["id"]: item["status"] for item in _items(view.json())}
        assert statuses == {items[0]["id"]: "done", items[1]["id"]: "pending"}

    # 完成按条目身份记账：再读 + 再生成（幂等）都不改状态。
    _generate(client)
    view = client.get("/api/v1/queue/today").json()
    statuses = {item["id"]: item["status"] for item in _items(view)}
    assert statuses[items[0]["id"]] == "done"
