"""E1: N046 队列冲突合并（服务端）。

- 修订号：队列任何变更 +1；GET /queue/today 返回 revision；
- expectedRevision 落后 → 409 queue_revision_conflict（写入前发生，
  冲突绝不半途落库），冲突体带 currentRevision + 逐 ref
  {serverItem, yourItem} 差异提示；
- 按项合并：keep-mine（应用客户端 status/segment）/ keep-theirs
  （保持服务端现状）；**未提及的行原样保留**（负向契约）。
"""

import asyncio

from lumirss.entryref import encode_entry_ref


def run(coroutine):
    return asyncio.run(coroutine)


def _seed(app, item_id, *, published_at):
    entry_ref = encode_entry_ref(item_id)
    run(
        app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url,"
            " feed_title, title, author, url, content_text, published_at, read,"
            " starred, fetched_at) VALUES (?, ?, 'https://f.example/rss', '源',"
            " 't', '', 'u', 'c', ?, 0, 0, 0)",
            (item_id, entry_ref, published_at),
        )
    )
    return f"rss:{entry_ref}"


def _generate(client):
    response = client.post("/api/v1/queue/today/generate", json={"timeBudgetMinutes": 60})
    assert response.status_code == 201, response.text
    return response.json()


def test_n046_revision_bumps_and_conflict_detection(client):
    app = client.app
    run(app.state.db.migrate())
    for i in range(3):
        _seed(app, f"c{i}", published_at=f"2026-09-2{0 + i}-01T00:00:00Z")
    body = _generate(client)
    revision = body["revision"]
    assert revision >= 1
    items = body["items"]
    assert len(items) == 3

    # 变更 → 修订号 +1。
    done_response = client.post(
        f"/api/v1/queue/today/items/{items[0]['id']}/done", json={"done": True}
    )
    assert done_response.status_code == 200
    view = client.get("/api/v1/queue/today").json()
    assert view["revision"] == revision + 1

    # 陈旧设备（仍持旧 revision）做重排 → 409 + 差异提示。
    stale = client.put(
        "/api/v1/queue/today/order",
        json={
            "order": [items[1]["id"], items[0]["id"], items[2]["id"]],
            "expectedRevision": revision,  # 已落后
            "clientItems": [
                {"id": item["id"], "itemRef": item["itemRef"], "status": "pending", "segment": None}
                for item in items
            ],
        },
    )
    assert stale.status_code == 409, stale.text
    error = stale.json()["error"]
    assert error["type"] == "queue_revision_conflict"
    assert error["currentRevision"] == revision + 1
    conflicts = error["conflicts"]
    # 只有真正分歧的 ref 进冲突清单（未分歧行不算冲突）。
    assert len(conflicts) == 1
    # 冲突体给出 serverItem（服务端现状，含 done 行）与 yourItem
    # （客户端视图）。
    done_conflict = conflicts[0]
    assert done_conflict["ref"] == items[0]["itemRef"]
    assert done_conflict["serverItem"]["status"] == "done"
    assert done_conflict["yourItem"]["status"] == "pending"

    # 冲突未落库：重排没有生效（position 不变）。
    view = client.get("/api/v1/queue/today").json()
    by_id = {item["id"]: item["position"] for item in view["items"]}
    assert by_id == {item["id"]: item["position"] for item in items}

    # 新鲜 revision 重放 → 200。
    fresh = client.put(
        "/api/v1/queue/today/order",
        json={
            "order": [items[1]["id"], items[0]["id"], items[2]["id"]],
            "expectedRevision": view["revision"],
            "clientItems": [
                {"id": item["id"], "itemRef": item["itemRef"], "status": "pending", "segment": None}
                for item in items
            ],
        },
    )
    assert fresh.status_code == 200, fresh.text


def test_n046_per_item_merge_keeps_unmodified_intact(client):
    app = client.app
    run(app.state.db.migrate())
    for i in range(3):
        _seed(app, f"m{i}", published_at=f"2026-09-2{0 + i}-01T00:00:00Z")
    body = _generate(client)
    revision = body["revision"]
    items = body["items"]
    target_a = items[0]
    target_b = items[1]
    untouched = items[2]

    # 另一设备推进修订号：a 完成、b 移除。
    client.post(f"/api/v1/queue/today/items/{target_a['id']}/done", json={"done": True})
    client.delete(f"/api/v1/queue/today/items/{target_b['id']}")
    server_view = client.get("/api/v1/queue/today").json()
    current = server_view["revision"]

    # 本设备带着陈旧视图改 c 的分段 → 409。
    conflict = client.patch(
        f"/api/v1/queue/today/items/{untouched['id']}/segment",
        json={
            "segment": "晚间",
            "expectedRevision": revision,
            "clientItems": [
                {"id": i["id"], "itemRef": i["itemRef"], "status": "pending", "segment": None}
                for i in items
            ],
        },
    )
    assert conflict.status_code == 409
    conflicts = conflict.json()["error"]["conflicts"]
    refs_in_conflict = {c["ref"] for c in conflicts}
    assert target_a["itemRef"] in refs_in_conflict
    assert target_b["itemRef"] in refs_in_conflict

    # 按项合并：a keep-theirs（服务端 done 赢）；b keep-mine（本地要回
    # pending）；c（未提及）原样保留。
    merge = client.post(
        "/api/v1/queue/today/merge-conflicts",
        json={
            "expectedRevision": current,
            "resolutions": [
                {
                    "itemRef": target_a["itemRef"],
                    "action": "keep-theirs",
                },
                {
                    "itemRef": target_b["itemRef"],
                    "action": "keep-mine",
                    "clientItem": {
                        "id": target_b["id"],
                        "itemRef": target_b["itemRef"],
                        "status": "pending",
                        "segment": None,
                    },
                },
            ],
        },
    )
    assert merge.status_code == 200, merge.text
    merged_items = {item["itemRef"]: item for item in merge.json()["items"]}
    assert merged_items[target_a["itemRef"]]["status"] == "done"  # keep-theirs
    assert merged_items[target_b["itemRef"]]["status"] == "pending"  # keep-mine 复活
    assert merged_items[untouched["itemRef"]]["segment"] is None  # 未提及：原样
    # 合并整体只 bump 一次修订号。
    assert merge.json()["revision"] == current + 1

    # 合并后修订号已前进：同一 expectedRevision 重放 → 再 409。
    replay = client.post(
        "/api/v1/queue/today/merge-conflicts",
        json={
            "expectedRevision": current,
            "resolutions": [{"itemRef": target_a["itemRef"], "action": "keep-theirs"}],
        },
    )
    assert replay.status_code == 409


def test_n046_add_with_stale_revision_conflicts_before_write(client):
    app = client.app
    run(app.state.db.migrate())
    _seed(app, "a", published_at="2026-09-20T00:00:00Z")
    body = _generate(client)
    stale_revision = body["revision"]
    # 另一设备加入新条目（created → 修订 +1）。
    _seed(app, "mid", published_at="2026-09-19T00:00:00Z")
    bump = client.post(
        "/api/v1/queue/today/items",
        json={"itemRef": f"rss:{encode_entry_ref('mid')}"},
    )
    assert bump.status_code == 201

    response = client.post(
        "/api/v1/queue/today/items",
        json={
            "itemRef": f"rss:{encode_entry_ref('zz')}",
            "expectedRevision": stale_revision,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "queue_revision_conflict"
    # 新条目没有写入。
    view = client.get("/api/v1/queue/today").json()
    assert all(item["itemRef"] != f"rss:{encode_entry_ref('zz')}" for item in view["items"])
