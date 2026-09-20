"""F022 收件箱归类规则 —— 顺序、幂等、停用跳过、dry-run 不落库。"""

import asyncio


def run(coroutine):
    return asyncio.run(coroutine)


def _create_source(client, name="scripts"):
    resp = client.post("/api/v1/inbox/sources", json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ingest(client, source, guid, title, bearer=None):
    return client.post(
        f"/api/v1/inbox/ingest/{source['uuid']}",
        json={"guid": guid, "title": title, "content": "正文内容"},
        headers={"Authorization": f"Bearer {bearer or source['secret']}"},
    )


def _create_workspace(client, name):
    resp = client.post("/api/v1/workspaces", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_f022_first_match_priority_disabled_and_no_match(client):
    source = _create_source(client)
    ws_first = _create_workspace(client, "优先工作区")
    ws_second = _create_workspace(client, "次选工作区")

    # 两条都会命中的规则：priority 顺序决定只有第一条生效
    r1 = client.post(
        "/api/v1/inbox/rules",
        json={"field": "title", "operator": "contains", "value": "周报", "targetWorkspaceId": ws_first},
    )
    r2 = client.post(
        "/api/v1/inbox/rules",
        json={"field": "title", "operator": "contains", "value": "报", "targetWorkspaceId": ws_second},
    )
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["priority"] < r2.json()["priority"]

    ingested = _ingest(client, source, "g-1", "第九周报：AI 专栏")
    assert ingested.status_code == 200, ingested.text
    ref = ingested.json()["ref"]

    members = client.get(f"/api/v1/workspaces/{ws_first}/items").json()
    assert any(item["itemRef"] == ref for item in members.get("items", []))

    # 停用第一条后，新条目命中第二条
    client.patch(f"/api/v1/inbox/rules/{r1.json()['id']}", json={"enabled": False})
    ingested2 = _ingest(client, source, "g-2", "第十周报：AI 专栏")
    ref2 = ingested2.json()["ref"]
    members2 = client.get(f"/api/v1/workspaces/{ws_second}/items").json()
    assert any(item["itemRef"] == ref2 for item in members2.get("items", []))

    # 无匹配 → 不归类
    ingested3 = _ingest(client, source, "g-3", "无关标题")
    ref3 = ingested3.json()["ref"]
    m1 = client.get(f"/api/v1/workspaces/{ws_first}/items").json()
    m2 = client.get(f"/api/v1/workspaces/{ws_second}/items").json()
    assert all(item["itemRef"] != ref3 for item in m1.get("items", []))
    assert all(item["itemRef"] != ref3 for item in m2.get("items", []))


def test_f022_replay_guid_no_side_effect_and_move_up(client):
    source = _create_source(client)
    ws = _create_workspace(client, "归档")
    client.post(
        "/api/v1/inbox/rules",
        json={"field": "source", "operator": "equals", "value": "scripts", "targetWorkspaceId": ws},
    )
    first = _ingest(client, source, "same-guid", "标题一")
    assert first.status_code == 200
    assert first.json()["status"] == "created"
    replay = _ingest(client, source, "same-guid", "标题一")
    assert replay.status_code == 200
    assert replay.json()["status"] == "exists"
    ref = replay.json()["ref"]
    members = client.get(f"/api/v1/workspaces/{ws}/items").json()
    hits = [item for item in members.get("items", []) if item["itemRef"] == ref]
    assert len(hits) == 1  # 幂等：不重复触发副作用

    # 上下移：交换 priority（补第二条永不命中的规则以便交换）
    client.post(
        "/api/v1/inbox/rules",
        json={"field": "title", "operator": "equals", "value": "绝不出现的标题ZZZ", "targetWorkspaceId": ws},
    )
    rules = client.get("/api/v1/inbox/rules").json()["items"]
    assert len(rules) == 2
    moved = client.post(
        f"/api/v1/inbox/rules/{rules[0]['id']}/move", params={"direction": "down"}
    )
    assert moved.status_code == 200
    rules_after = client.get("/api/v1/inbox/rules").json()["items"]
    assert [r["id"] for r in rules_after] == [rules[1]["id"], rules[0]["id"]]

    # 删除
    assert client.delete(f"/api/v1/inbox/rules/{rules[0]['id']}").status_code == 204
    assert client.delete(f"/api/v1/inbox/rules/{rules[0]['id']}").status_code == 404


def test_f022_value_length_cap_and_dry_run_no_writes(client):
    source = _create_source(client)
    ws = _create_workspace(client, "预览区")

    # 畸形 value：>200 字 → 422
    too_long = client.post(
        "/api/v1/inbox/rules",
        json={"field": "title", "operator": "contains", "value": "x" * 201, "targetWorkspaceId": ws},
    )
    assert too_long.status_code == 422

    # dry-run 命中解释 + 不落库（无规则时 honest 未命中文案）
    client.post(
        "/api/v1/inbox/rules",
        json={"field": "title", "operator": "contains", "value": "速递", "targetWorkspaceId": ws},
    )
    before = client.get("/api/v1/inbox/rules").json()["items"]
    dry = client.post(
        "/api/v1/inbox/rules/dry-run",
        json={"field": "title", "value": "晚间速递", "source": "scripts"},
    )
    assert dry.status_code == 200
    assert dry.json()["matchedRule"] is not None
    assert "归入工作区" in dry.json()["explanation"]

    miss = client.post(
        "/api/v1/inbox/rules/dry-run",
        json={"field": "title", "value": "完全无关"},
    )
    assert miss.status_code == 200
    assert miss.json()["matchedRule"] is None
    assert "没有命中" in miss.json()["explanation"]

    after = client.get("/api/v1/inbox/rules").json()["items"]
    assert [r["id"] for r in after] == [r["id"] for r in before]  # dry-run 不落库

    # 停用规则不参与 dry-run
    rule_id = before[0]["id"]
    client.patch(f"/api/v1/inbox/rules/{rule_id}", json={"enabled": False})
    dry_disabled = client.post(
        "/api/v1/inbox/rules/dry-run",
        json={"field": "title", "value": "晚间速递"},
    )
    assert dry_disabled.json()["matchedRule"] is None
    _ = asyncio, source  # keep imports honest
