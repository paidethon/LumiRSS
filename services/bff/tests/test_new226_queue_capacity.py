"""NEW-226 队列容量上限（服务端）。

- 设置（1..100 + 启用开关；未设置时诚实返回 null + 说明）；
- offer 守门：未满正常走既有 N041 加入语义（created/duplicate/
  resurrected）；已满 → 候选进待确认区（pending_choice），绝不自动
  顶掉任何行；
- 裁决：replace（指定被替换行 → 移除 + 加入）与 dismiss（暂不加入）
  都是显式动作；重复裁决 → 404；
- A/B 每用户隔离。
"""

from fastapi.testclient import TestClient

from new2xx_ab import ab_env, seed_entry  # noqa: F811


def _set_capacity(client: TestClient, headers: dict, capacity: int, enabled: bool = True):
    return client.put(
        "/api/v1/queue/capacity",
        json={"capacity": capacity, "enabled": enabled},
        headers=headers,
    )


def test_settings_default_and_update(ab_env):  # noqa: F811
    client = ab_env["client"]
    default = client.get("/api/v1/queue/capacity", headers=ab_env["a"])
    assert default.status_code == 200
    body = default.json()
    assert body["capacity"] is None and body["enabled"] is False
    assert body["note"]

    updated = _set_capacity(client, ab_env["a"], 2)
    assert updated.status_code == 200, updated.text
    assert updated.json()["capacity"] == 2 and updated.json()["enabled"] is True

    out_of_bounds = _set_capacity(client, ab_env["a"], 0)
    # pydantic ge=1 先拦（invalid_request）；store 层是第二道 422。
    assert out_of_bounds.status_code == 422
    big = _set_capacity(client, ab_env["a"], 101)
    assert big.status_code == 422

    # 关闭开关后不限容量。
    disabled = _set_capacity(client, ab_env["a"], 2, enabled=False)
    assert disabled.json()["enabled"] is False


def test_offer_overflows_when_full_then_replace(ab_env):  # noqa: F811
    client = ab_env["client"]
    refs = [seed_entry(ab_env, "a", f"q{i}", title=f"文{i}") for i in range(4)]
    _set_capacity(client, ab_env["a"], 2)

    first = client.post(
        "/api/v1/queue/capacity/offer", json={"itemRef": refs[0]},
        headers=ab_env["a"],
    )
    assert first.status_code == 201, first.text
    assert first.json()["outcome"] == "created"
    second = client.post(
        "/api/v1/queue/capacity/offer", json={"itemRef": refs[1]},
        headers=ab_env["a"],
    )
    assert second.json()["outcome"] == "created"

    # 满：第三篇 → overflow（待确认区），绝不自动顶掉。
    overflow = client.post(
        "/api/v1/queue/capacity/offer", json={"itemRef": refs[2]},
        headers=ab_env["a"],
    )
    assert overflow.status_code == 200, overflow.text
    assert overflow.json()["outcome"] == "overflow"
    assert overflow.json()["status"] == "pending_choice"
    assert "由你决定" in overflow.json()["note"]
    candidate_id = overflow.json()["id"]

    # 同一篇再次 offer → already_pending（幂等，不重复占位）。
    again = client.post(
        "/api/v1/queue/capacity/offer", json={"itemRef": refs[2]},
        headers=ab_env["a"],
    )
    assert again.json()["outcome"] == "already_pending"

    pending = client.get("/api/v1/queue/capacity/pending", headers=ab_env["a"])
    assert pending.status_code == 200
    body = pending.json()
    assert body["queueCount"] == 2
    assert [item["id"] for item in body["items"]] == [candidate_id]

    # 队列里现有行的 id（为 replace 用）。
    queue = client.get("/api/v1/queue/today", headers=ab_env["a"]).json()
    victim_id = queue["items"][0]["id"]

    # 裁决「替换」：移除 victim，加入候选。
    replaced = client.post(
        f"/api/v1/queue/capacity/pending/{candidate_id}/replace",
        json={"replacedItemId": victim_id},
        headers=ab_env["a"],
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["removedItemId"] == victim_id
    assert replaced.json()["addedItem"]["itemRef"] == refs[2]

    after = client.get("/api/v1/queue/today", headers=ab_env["a"]).json()
    active_refs = {item["itemRef"] for item in after["items"]}
    assert active_refs == {refs[1], refs[2]}
    # 候选已裁决：再 replace/dismiss → 404。
    assert (
        client.post(
            f"/api/v1/queue/capacity/pending/{candidate_id}/dismiss",
            headers=ab_env["a"],
        ).status_code
        == 404
    )


def test_offer_dismiss_path(ab_env):  # noqa: F811
    client = ab_env["client"]
    refs = [seed_entry(ab_env, "a", f"d{i}", title=f"d{i}") for i in range(3)]
    _set_capacity(client, ab_env["a"], 1)
    client.post("/api/v1/queue/capacity/offer", json={"itemRef": refs[0]},
                headers=ab_env["a"])
    overflow = client.post(
        "/api/v1/queue/capacity/offer", json={"itemRef": refs[1]},
        headers=ab_env["a"],
    )
    candidate_id = overflow.json()["id"]
    dismissed = client.post(
        f"/api/v1/queue/capacity/pending/{candidate_id}/dismiss",
        headers=ab_env["a"],
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"
    # 暂不加入：队列仍只有 1 条，候选不再出现在待确认区。
    queue = client.get("/api/v1/queue/today", headers=ab_env["a"]).json()
    assert len(queue["items"]) == 1
    pending = client.get("/api/v1/queue/capacity/pending", headers=ab_env["a"])
    assert pending.json()["items"] == []


def test_validation_and_ab_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    bad_ref = client.post(
        "/api/v1/queue/capacity/offer", json={"itemRef": "nope"},
        headers=ab_env["a"],
    )
    assert bad_ref.status_code == 422

    # B：无设置、无候选、无队列（A 的容量守门对 B 无影响）。
    b_settings = client.get("/api/v1/queue/capacity", headers=ab_env["b"])
    assert b_settings.json()["capacity"] is None
    b_pending = client.get("/api/v1/queue/capacity/pending", headers=ab_env["b"])
    assert b_pending.json()["items"] == []
    assert b_pending.json()["queueCount"] == 0
    # B 直接裁决 A 的候选 id → 404（不泄露存在性）。
    assert (
        client.post(
            "/api/v1/queue/capacity/pending/qcap-nope/dismiss",
            headers=ab_env["b"],
        ).status_code
        == 404
    )
