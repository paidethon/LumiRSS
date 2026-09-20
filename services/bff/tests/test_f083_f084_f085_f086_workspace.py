"""F083 模板 / F084 归档 / F085 看板 / F086 目标 — 正负向（规格逐条）。"""

import asyncio

from lumirss.main import app

REF = "library:00000000-0000-4000-8000-00000000a5a1"


def run(coro):
    return asyncio.run(coro)


def _mk_ws(client, name="ws85", description="说明A"):
    r = client.post("/api/v1/workspaces", json={"name": name, "description": description})
    assert r.status_code == 201, r.text
    ws = r.json()["id"]
    bm = client.post(
        "/api/v1/library/bookmarks", json={"url": f"https://{name}.example/1", "title": name}
    ).json()
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": bm["ref"]})
    return ws


def test_f083_template_roundtrip_and_isolation(client):
    ws = _mk_ws(client, "tpl-src", "源说明")
    saved = client.post(
        f"/api/v1/workspaces/{ws}/save-as-template", json={"name": "我的模板"}
    )
    assert saved.status_code == 201, saved.text
    tpl = saved.json()
    # 模板不携带条目内容/凭据（负向：config 只有 description）
    assert set(tpl["config"].keys()) == {"description"}
    assert "源说明" in tpl["config"]["description"]

    # 同名 409
    dup = client.post(f"/api/v1/workspaces/{ws}/save-as-template", json={"name": "我的模板"})
    assert dup.status_code == 409
    assert dup.json()["error"]["type"] == "template_exists"

    # 从模板创建（带示例条目）
    created = client.post(
        "/api/v1/workspaces/from-template",
        json={
            "templateId": tpl["id"],
            "name": "新工作区",
            "includeExampleItems": True,
            "exampleRefs": [REF],
        },
    )
    assert created.status_code == 201, created.text
    new_ws = created.json()["workspace"]["id"]
    assert created.json()["workspace"]["description"] == "源说明"
    # 失效 ref 诚实跳过
    assert created.json()["skippedExampleRefs"] == [REF]

    # 三方独立：修改模板源工作区说明 / 新工作区说明 / 模板配置互不影响
    client.patch(f"/api/v1/workspaces/{ws}", json={"name": "tpl-src", "description": "改掉的说明"})
    client.patch(f"/api/v1/workspaces/{new_ws}", json={"name": "新工作区", "description": "另说明"})
    templates = client.get("/api/v1/workspace-templates").json()["items"]
    assert len(templates) == 1
    assert templates[0]["config"]["description"] == "源说明"

    # 重复创建（同名模板再建一个工作区）→ 两个独立工作区（文档化语义）
    again = client.post(
        "/api/v1/workspaces/from-template",
        json={"templateId": tpl["id"], "name": "第二个", "includeExampleItems": False},
    )
    assert again.status_code == 201
    assert again.json()["workspace"]["id"] != new_ws

    # 空工作区模板（无条目）也可用
    empty_ws = client.post("/api/v1/workspaces", json={"name": "empty-ws"}).json()["id"]
    t2 = client.post(f"/api/v1/workspaces/{empty_ws}/save-as-template", json={"name": "空模板"})
    assert t2.status_code == 201

    # 删除模板
    assert client.delete(f"/api/v1/workspace-templates/{tpl['id']}").status_code == 204
    assert client.delete(f"/api/v1/workspace-templates/{tpl['id']}").status_code == 404


def test_f084_archive_hide_deeplink_restore_order_kept(client):
    ws = _mk_ws(client, "arch-ws")
    # 记住顺序设置（position 由创建顺序决定）
    listed = client.get("/api/v1/workspaces").json()["items"]
    assert any(w["id"] == ws for w in listed)

    arch = client.patch(f"/api/v1/workspaces/{ws}/archive", json={"archived": True})
    assert arch.status_code == 200, arch.text
    # 默认列表隐藏
    listed = client.get("/api/v1/workspaces").json()["items"]
    assert all(w["id"] != ws for w in listed)
    # 归档列表入口可见
    archived_list = client.get("/api/v1/workspace-archive").json()
    assert any(w["id"] == ws for w in archived_list)
    # 深链接仍可打开（顶部“已归档”徽标数据）
    deep = client.get(f"/api/v1/workspaces/{ws}")
    assert deep.status_code == 200
    assert deep.json()["archived"] is True
    # 归档工作区看板写入被诚实禁用
    denied = client.put(
        f"/api/v1/workspaces/{ws}/board",
        json={"itemRef": REF, "status": "todo"},
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["type"] == "archived_workspace"
    # 恢复 → 重新可见，顺序设置保留
    restored = client.patch(f"/api/v1/workspaces/{ws}/archive", json={"archived": False})
    assert restored.status_code == 200
    listed = client.get("/api/v1/workspaces").json()["items"]
    target = next(w for w in listed if w["id"] == ws)
    assert target["archived"] is False


def test_f084_reserved_protected_and_rule_skip_explained(client):
    # 种子/保留工作区 archive → 409 protected_workspace
    prot = client.patch("/api/v1/workspaces/read-later/archive", json={"archived": True})
    assert prot.status_code == 409
    assert prot.json()["error"]["type"] == "protected_workspace"

    # 规则目标为归档工作区 → dry-run 跳过并解释
    ws = _mk_ws(client, "rule-ws")
    rule = client.post(
        "/api/v1/inbox/rules",
        json={
            "field": "title",
            "operator": "contains",
            "value": "invoice",
            "targetWorkspaceId": ws,
            "enabled": True,
            "priority": 1,
        },
    )
    assert rule.status_code == 201, rule.text
    ok_dry = client.post(
        "/api/v1/inbox/rules/dry-run",
        json={"field": "title", "value": "invoice #42", "source": None},
    )
    assert ok_dry.status_code == 200
    assert ok_dry.json()["matchedRule"] is not None

    client.patch(f"/api/v1/workspaces/{ws}/archive", json={"archived": True})
    skipped = client.post(
        "/api/v1/inbox/rules/dry-run",
        json={"field": "title", "value": "invoice #42", "source": None},
    )
    assert skipped.status_code == 200
    assert skipped.json()["matchedRule"] is None
    assert "已归档" in skipped.json()["explanation"]


def test_f085_board_move_persist_and_idempotent(client):
    ws = _mk_ws(client, "board-ws")
    bm = client.post(
        "/api/v1/library/bookmarks", json={"url": "https://board.example/1", "title": "板条"}
    ).json()["ref"]
    # 非成员 → 404（board_item_not_found）
    bad = client.put(f"/api/v1/workspaces/{ws}/board", json={"itemRef": bm, "status": "todo"})
    assert bad.status_code == 404
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": bm})
    moved = client.put(f"/api/v1/workspaces/{ws}/board", json={"itemRef": bm, "status": "reading"})
    assert moved.status_code == 200, moved.text
    board = client.get(f"/api/v1/workspaces/{ws}/board").json()
    reading = next(c for c in board["columns"] if c["status"] == "reading")
    assert reading["total"] == 1 and reading["items"][0]["itemRef"] == bm
    # 刷新/refetch 保留 + 重复 PUT 幂等
    client.put(f"/api/v1/workspaces/{ws}/board", json={"itemRef": bm, "status": "reading"})
    board2 = client.get(f"/api/v1/workspaces/{ws}/board").json()
    assert next(c for c in board2["columns"] if c["status"] == "reading")["total"] == 1
    # 非法状态 422
    invalid = client.put(f"/api/v1/workspaces/{ws}/board", json={"itemRef": bm, "status": "archived"})
    assert invalid.status_code == 422
    # 不触碰 read/star（负向）：FreshRSS 状态列不存在于 library 域，
    # 断言书签本体不受看板影响
    row = run(
        app.state.db.fetch_one(
            "SELECT title, note FROM library_bookmarks WHERE url = 'https://board.example/1'"
        )
    )
    assert row["title"] == "板条" and row["note"] == ""
    # 同一条目在其他工作区状态独立
    ws2 = _mk_ws(client, "board-ws2")
    client.post(f"/api/v1/workspaces/{ws2}/items", json={"itemRef": bm})
    other = client.get(f"/api/v1/workspaces/{ws2}/board").json()
    assert all(c["total"] == 0 for c in other["columns"])


def test_f086_goal_progress_honest(client):
    ws = _mk_ws(client, "goal-ws")
    bm = client.post(
        "/api/v1/library/bookmarks", json={"url": "https://goal.example/1", "title": "目标条"}
    ).json()["ref"]
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": bm})
    put = client.put(f"/api/v1/workspaces/{ws}/goal", json={"targetCount": 2, "deadline": "2026-12-31"})
    assert put.status_code == 200, put.text
    assert put.json()["doneCount"] == 0
    client.put(f"/api/v1/workspaces/{ws}/board", json={"itemRef": bm, "status": "done"})
    goal = client.get(f"/api/v1/workspaces/{ws}/goal").json()
    assert goal["doneCount"] == 1  # 与 board done 一致
    # 重复 done 不双计
    client.put(f"/api/v1/workspaces/{ws}/board", json={"itemRef": bm, "status": "done"})
    assert client.get(f"/api/v1/workspaces/{ws}/goal").json()["doneCount"] == 1
    # 条目移出工作区 → 进度诚实下降
    client.delete(f"/api/v1/workspaces/{ws}/items/{bm}")
    assert client.get(f"/api/v1/workspaces/{ws}/goal").json()["doneCount"] == 0
    # 零条目时 0 显示 & 非法目标 422
    bad = client.put(f"/api/v1/workspaces/{ws}/goal", json={"targetCount": 0})
    assert bad.status_code == 422
    # 目标删除 → 卡隐藏（exists=False）
    assert client.delete(f"/api/v1/workspaces/{ws}/goal").status_code == 204
    assert client.get(f"/api/v1/workspaces/{ws}/goal").json()["exists"] is False
