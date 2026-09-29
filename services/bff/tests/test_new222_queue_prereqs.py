"""NEW-222 队列依赖关系（服务端）。

- 先读项设置（重复幂等 / 自指拒绝 / 成环拒绝 BFS）；
- met/unmet 逐条 basis（read / queue-done / slot-done / unread / unknown）；
- 建议性契约：unmet 只汇总提示，绝无阻止跳读的路径（View/Docstring
  即契约，无任何读取端点因依赖而拒绝）；
- A/B 每用户隔离 + 载荷校验。
"""

from fastapi.testclient import TestClient

from new2xx_ab import ab_env, seed_entry  # noqa: F401


def _add_prereq(client: TestClient, headers: dict, item_ref: str, prereq_ref: str):
    return client.post(
        "/api/v1/queue/prereqs",
        json={"itemRef": item_ref, "prereqRef": prereq_ref},
        headers=headers,
    )


def test_prereq_happy_and_met_basis(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref_a = seed_entry(ab_env, "a", "p1", title="前置", read=1)
    ref_b = seed_entry(ab_env, "a", "p2", title="本篇")
    made = _add_prereq(client, ab_env["a"], ref_b, ref_a)
    assert made.status_code == 201, made.text
    assert made.json()["outcome"] == "created"
    # 重复 = 幂等 200。
    dup = _add_prereq(client, ab_env["a"], ref_b, ref_a)
    assert dup.status_code == 200 and dup.json()["outcome"] == "duplicate"

    view = client.get(
        "/api/v1/queue/prereqs", params={"itemRef": ref_b}, headers=ab_env["a"]
    )
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["advisory"] is True
    assert body["unmetCount"] == 0
    assert body["prereqs"][0]["met"] is True
    assert body["prereqs"][0]["basis"] == "read"


def test_unmet_basis_variants(ab_env):  # noqa: F811
    client = ab_env["client"]
    unread = seed_entry(ab_env, "a", "u1", title="未读前置")
    target = seed_entry(ab_env, "a", "u2", title="目标")
    _add_prereq(client, ab_env["a"], target, unread)
    view = client.get(
        "/api/v1/queue/prereqs", params={"itemRef": target}, headers=ab_env["a"]
    ).json()
    assert view["unmetCount"] == 1
    assert view["prereqs"][0]["basis"] == "unread"

    # 前置进入今日队列并完成后 → queue-done。
    today = client.post(
        "/api/v1/queue/today/items", json={"itemRef": unread}, headers=ab_env["a"]
    )
    assert today.status_code == 201, today.text
    item_id = today.json()["id"]
    done = client.post(
        f"/api/v1/queue/today/items/{item_id}/done",
        json={"done": True},
        headers=ab_env["a"],
    )
    assert done.status_code == 200, done.text
    view = client.get(
        "/api/v1/queue/prereqs", params={"itemRef": target}, headers=ab_env["a"]
    ).json()
    assert view["prereqs"][0]["met"] is True
    assert view["prereqs"][0]["basis"] == "queue-done"


def test_self_and_cycle_rejected(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref_x = seed_entry(ab_env, "a", "x1")
    ref_y = seed_entry(ab_env, "a", "x2")
    self_dep = _add_prereq(client, ab_env["a"], ref_x, ref_x)
    assert self_dep.status_code == 422
    assert self_dep.json()["error"]["type"] == "invalid_queue_prereq"

    assert _add_prereq(client, ab_env["a"], ref_y, ref_x).status_code == 201
    # x→y 会成环（y 已依赖 x）。
    cycle = _add_prereq(client, ab_env["a"], ref_x, ref_y)
    assert cycle.status_code == 422
    assert "环" in cycle.json()["error"]["message"]


def test_validation_and_ab_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "iso-p", title="A 的材料")
    made = _add_prereq(client, ab_env["a"], ref, "rss:not-a-ref")
    assert made.status_code == 422

    # A 的依赖对 B 不可见（B 查同一材料 → 空视图）。
    b_view = client.get(
        "/api/v1/queue/prereqs", params={"itemRef": ref}, headers=ab_env["b"]
    )
    assert b_view.status_code == 200
    assert b_view.json()["prereqs"] == []
    assert b_view.json()["unmetCount"] == 0

    # A 的今日汇总不含 B 的队列成员。
    summary = client.get("/api/v1/queue/prereqs/today", headers=ab_env["b"])
    assert summary.status_code == 200
    assert summary.json()["itemsWithUnmet"] == []

    # 删除：不存在 → 404。
    gone = client.delete("/api/v1/queue/prereqs/qpre-nope", headers=ab_env["a"])
    assert gone.status_code == 404
    assert gone.json()["error"]["type"] == "queue_prereq_not_found"
