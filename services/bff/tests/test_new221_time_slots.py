"""NEW-221 分时段阅读队列（服务端）。

- 时段 CRUD + 成员归属（partial UNIQUE：一篇文章同时只有一个待读时段）；
- 打开时段 = 接续视图 + last_opened_at 记账（GET 恒无副作用）；
- 顺延是显式用户决策：必须指定目标时段；原行转 carried 保留轨迹；
- A/B 每用户隔离（alice 的时段对 bob 完全不可见）；
- 载荷校验（空名/超长名/非法 itemRef/删除非空时段）。
"""

from fastapi.testclient import TestClient
from pytest import mark

from new2xx_ab import ab_env, seed_entry  # noqa: F401


def _create(client: TestClient, headers: dict, name: str):
    return client.post("/api/v1/queue/slots", json={"name": name}, headers=headers)


def _add(client: TestClient, headers: dict, slot_id: str, item_ref: str):
    return client.post(
        f"/api/v1/queue/slots/{slot_id}/items",
        json={"itemRef": item_ref},
        headers=headers,
    )


# ---- happy path ---------------------------------------------------------------


def test_create_assign_open_resume_and_done(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "s1", title="通勤文")
    made = _create(client, ab_env["a"], "通勤")
    assert made.status_code == 201, made.text
    slot = made.json()
    assert slot["name"] == "通勤" and slot["pendingCount"] == 0

    added = _add(client, ab_env["a"], slot["id"], ref)
    assert added.status_code == 201, added.text
    assert added.json()["status"] == "pending"

    opened = client.post(f"/api/v1/queue/slots/{slot['id']}/open", headers=ab_env["a"])
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["resume"]["pendingCount"] == 1
    assert body["resume"]["nextItemRef"] == ref
    assert body["resume"]["nextTitle"] == "通勤文"
    assert body["lastOpenedAt"] is not None
    assert body["pendingCount"] == 1 and body["doneCount"] == 0

    # GET 详情无副作用：last_opened_at 不变。
    before = client.get(f"/api/v1/queue/slots/{slot['id']}", headers=ab_env["a"]).json()
    detail = client.get(f"/api/v1/queue/slots/{slot['id']}", headers=ab_env["a"]).json()
    assert detail["lastOpenedAt"] == before["lastOpenedAt"]

    item_id = detail["items"][0]["id"]
    done = client.post(
        f"/api/v1/queue/slot-items/{item_id}/done", json={"done": True},
        headers=ab_env["a"],
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done" and done.json()["doneAt"]

    # set 语义：取消完成回到 pending。
    undone = client.post(
        f"/api/v1/queue/slot-items/{item_id}/done", json={"done": False},
        headers=ab_env["a"],
    )
    assert undone.json()["status"] == "pending"


def test_carry_over_is_explicit_and_leaves_trail(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "c1", title="未读完")
    morning = _create(client, ab_env["a"], "通勤").json()
    evening = _create(client, ab_env["a"], "晚间").json()
    _add(client, ab_env["a"], morning["id"], ref)

    moved = client.post(
        f"/api/v1/queue/slots/{morning['id']}/carry-over",
        json={"targetSlotId": evening["id"]},
        headers=ab_env["a"],
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["moved"] == 1

    # 原时段：无 pending；carried 轨迹保留。
    src = client.get(f"/api/v1/queue/slots/{morning['id']}", headers=ab_env["a"]).json()
    assert src["pendingCount"] == 0
    assert src["items"][0]["status"] == "carried"
    assert src["items"][0]["carriedToSlot"] == evening["id"]

    # 目标时段：pending 接续。
    dst = client.get(f"/api/v1/queue/slots/{evening['id']}", headers=ab_env["a"]).json()
    assert dst["pendingCount"] == 1 and dst["items"][-1]["itemRef"] == ref

    # 不能顺延到原时段。
    self_target = client.post(
        f"/api/v1/queue/slots/{morning['id']}/carry-over",
        json={"targetSlotId": morning["id"]},
        headers=ab_env["a"],
    )
    assert self_target.status_code == 422


def test_delete_slot_blocked_while_pending(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "d1")
    slot = _create(client, ab_env["a"], "午休").json()
    _add(client, ab_env["a"], slot["id"], ref)
    blocked = client.delete(f"/api/v1/queue/slots/{slot['id']}", headers=ab_env["a"])
    assert blocked.status_code == 422
    item_id = client.get(
        f"/api/v1/queue/slots/{slot['id']}", headers=ab_env["a"]
    ).json()["items"][0]["id"]
    client.post(
        f"/api/v1/queue/slot-items/{item_id}/done", json={"done": True},
        headers=ab_env["a"],
    )
    # done 成员不挡删除（历史行随时段一起清理）。
    ok = client.delete(f"/api/v1/queue/slots/{slot['id']}", headers=ab_env["a"])
    assert ok.status_code == 204


# ---- 冲突与唯一归属 --------------------------------------------------------------


def test_pending_ref_unique_across_slots(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "u1")
    s1 = _create(client, ab_env["a"], "时段一").json()
    s2 = _create(client, ab_env["a"], "时段二").json()
    assert _add(client, ab_env["a"], s1["id"], ref).status_code == 201
    cross = _add(client, ab_env["a"], s2["id"], ref)
    assert cross.status_code == 409
    assert cross.json()["error"]["type"] == "queue_slot_item_conflict"
    # 同时段重复 = 幂等 200。
    dup = _add(client, ab_env["a"], s1["id"], ref)
    assert dup.status_code == 200 and dup.json()["outcome"] == "duplicate"
    # 完成后可再次加入其他时段。
    item_id = client.get(
        f"/api/v1/queue/slots/{s1['id']}", headers=ab_env["a"]
    ).json()["items"][0]["id"]
    client.post(
        f"/api/v1/queue/slot-items/{item_id}/done", json={"done": True},
        headers=ab_env["a"],
    )
    assert _add(client, ab_env["a"], s2["id"], ref).status_code == 201


# ---- 校验 ---------------------------------------------------------------------


def test_validation_bounds(ab_env):  # noqa: F811
    client = ab_env["client"]
    assert _create(client, ab_env["a"], "  ").status_code == 422
    assert _create(client, ab_env["a"], "名" * 61).status_code == 422
    slot = _create(client, ab_env["a"], "晚间").json()
    bad_ref = _add(client, ab_env["a"], slot["id"], "not-a-ref")
    assert bad_ref.status_code == 422
    assert bad_ref.json()["error"]["type"] == "invalid_queue_slot"
    missing = client.post(
        f"/api/v1/queue/slots/{slot['id']}/open", headers=ab_env["b"]
    )
    # 存在的时段对另一用户 = 404（不泄露存在性）。
    assert missing.status_code == 404
    gone = client.post(
        "/api/v1/queue/slots/qslot-nope/open", headers=ab_env["a"]
    )
    assert gone.status_code == 404
    assert gone.json()["error"]["type"] == "queue_slot_not_found"


# ---- A/B 每用户隔离 ---------------------------------------------------------------


@mark.usefixtures("ab_env")
def test_ab_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref_a = seed_entry(ab_env, "a", "iso1", title="A 的文章")
    slot_a = _create(client, ab_env["a"], "A 的时段").json()
    _add(client, ab_env["a"], slot_a["id"], ref_a)

    # B 的列表为空：A 的时段完全不可见。
    b_list = client.get("/api/v1/queue/slots", headers=ab_env["b"])
    assert b_list.status_code == 200
    assert b_list.json()["slots"] == []
    # B 直接访问 A 的时段 → 404。
    assert client.get(
        f"/api/v1/queue/slots/{slot_a['id']}", headers=ab_env["b"]
    ).status_code == 404
    assert _add(
        client, ab_env["b"], slot_a["id"], ref_a
    ).status_code == 404
    # B 建同名时段互不影响。
    slot_b = _create(client, ab_env["b"], "A 的时段").json()
    assert slot_b["id"] != slot_a["id"]
    a_list = client.get("/api/v1/queue/slots", headers=ab_env["a"]).json()
    assert [s["id"] for s in a_list["slots"]] == [slot_a["id"]]
