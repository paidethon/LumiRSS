"""NEW-229 阅读约定卡（服务端）。

诚实模型（本部署现实：业务数据按用户分库，无跨账户共享表面）：

- 创建方生成共持 pactKey；对方 join（携带同 key + 自己库内的材料
  ref）→ 各自库里一行对称约定；同 key 重复 join 幂等；
- 「双方独立确认」= 各自 confirm 自己的行；一方永远写不到另一方的库
  （B confirm A 的行 → 404）；
- 对方的确认状态诚实呈现为 counterpartVisibility =
  unavailable-cross-user，绝不伪造「对方已完成」；
- 归档/取消归档 set 语义；校验（空用户名/非法日期/非法 key）。
"""

from fastapi.testclient import TestClient

from new2xx_ab import ab_env, seed_entry  # noqa: F811


def test_create_join_and_independent_confirm(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref_a = seed_entry(ab_env, "a", "pact1", title="共读材料")
    ref_b = seed_entry(ab_env, "b", "pact1b", title="共读材料")

    created = client.post(
        "/api/v1/reading/pacts",
        json={"itemRef": ref_a, "deadline": "2026-10-15",
              "counterpartUsername": "bob", "materialTitle": "共读材料"},
        headers=ab_env["a"],
    )
    assert created.status_code == 201, created.text
    pact_a = created.json()
    assert pact_a["myStatus"] == "pending"
    assert pact_a["counterpartVisibility"] == "unavailable-cross-user"
    pact_key = pact_a["pactKey"]

    # 对方 join（同 key，自己的材料 ref）→ 自己库里一行对称约定。
    joined = client.post(
        "/api/v1/reading/pacts/join",
        json={"pactKey": pact_key, "itemRef": ref_b, "deadline": "2026-10-15",
              "counterpartUsername": "alice"},
        headers=ab_env["b"],
    )
    assert joined.status_code == 201, joined.text
    pact_b = joined.json()
    assert pact_b["pactKey"] == pact_key
    assert pact_b["id"] != pact_a["id"]  # 两行，两库

    # 双方独立确认：A 确认 A 的行。
    confirm_a = client.post(
        f"/api/v1/reading/pacts/{pact_a['id']}/confirm",
        json={"confirmed": True},
        headers=ab_env["a"],
    )
    assert confirm_a.status_code == 200
    assert confirm_a.json()["myStatus"] == "confirmed"
    assert confirm_a.json()["confirmedAt"] is not None
    # set 语义：可撤回。
    unconfirm_a = client.post(
        f"/api/v1/reading/pacts/{pact_a['id']}/confirm",
        json={"confirmed": False},
        headers=ab_env["a"],
    )
    assert unconfirm_a.json()["myStatus"] == "pending"
    # B 确认 B 的行（独立）。
    confirm_b = client.post(
        f"/api/v1/reading/pacts/{pact_b['id']}/confirm",
        json={"confirmed": True},
        headers=ab_env["b"],
    )
    assert confirm_b.json()["myStatus"] == "confirmed"
    # A 的视图仍只显示自己的状态；对方状态诚实不可见。
    listing_a = client.get("/api/v1/reading/pacts", headers=ab_env["a"])
    body = listing_a.json()
    assert body["counterpartVisibility"] == "unavailable-cross-user"
    assert body["items"][0]["myStatus"] == "pending"  # A 刚撤回
    assert "不可见" in body["note"]


def test_join_idempotent_and_cannot_touch_counterpart(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref_a = seed_entry(ab_env, "a", "pact2")
    created = client.post(
        "/api/v1/reading/pacts",
        json={"itemRef": ref_a, "deadline": "2026-11-01",
              "counterpartUsername": "bob"},
        headers=ab_env["a"],
    )
    pact_key = created.json()["pactKey"]
    pact_a_id = created.json()["id"]

    ref_b = seed_entry(ab_env, "b", "pact2b")
    first = client.post(
        "/api/v1/reading/pacts/join",
        json={"pactKey": pact_key, "itemRef": ref_b, "deadline": "2026-11-01",
              "counterpartUsername": "alice"},
        headers=ab_env["b"],
    )
    second = client.post(
        "/api/v1/reading/pacts/join",
        json={"pactKey": pact_key, "itemRef": ref_b, "deadline": "2026-11-01",
              "counterpartUsername": "alice"},
        headers=ab_env["b"],
    )
    assert second.status_code == 201  # 幂等（返回已有行）
    assert second.json()["id"] == first.json()["id"]

    # B 无法确认（或删除）A 库里的行：404，不泄露存在性。
    assert (
        client.post(
            f"/api/v1/reading/pacts/{pact_a_id}/confirm",
            json={"confirmed": True},
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    # B 的清单里没有 A 的行 id。
    b_list = client.get("/api/v1/reading/pacts", headers=ab_env["b"]).json()
    assert all(pact["id"] != pact_a_id for pact in b_list["items"])
    # 删除自己的行；A 的行不受影响。
    assert (
        client.delete(
            f"/api/v1/reading/pacts/{first.json()['id']}", headers=ab_env["b"]
        ).status_code
        == 204
    )
    assert (
        client.get("/api/v1/reading/pacts", headers=ab_env["a"]).json()["items"][0]["id"]
        == pact_a_id
    )


def test_archive_and_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "pact3")
    created = client.post(
        "/api/v1/reading/pacts",
        json={"itemRef": ref, "deadline": "2026-12-01",
              "counterpartUsername": "bob"},
        headers=ab_env["a"],
    )
    pact_id = created.json()["id"]

    archived = client.post(
        f"/api/v1/reading/pacts/{pact_id}/archive",
        json={"archived": True},
        headers=ab_env["a"],
    )
    assert archived.status_code == 200
    assert archived.json()["myStatus"] == "archived"
    # 归档后不能确认。
    confirm = client.post(
        f"/api/v1/reading/pacts/{pact_id}/confirm",
        json={"confirmed": True},
        headers=ab_env["a"],
    )
    assert confirm.status_code == 422
    # 默认清单排除 archived；显式包含可见。
    assert client.get("/api/v1/reading/pacts", headers=ab_env["a"]).json()["items"] == []
    with_archived = client.get(
        "/api/v1/reading/pacts", params={"includeArchived": "true"},
        headers=ab_env["a"],
    ).json()
    assert with_archived["items"][0]["myStatus"] == "archived"

    # 校验：空用户名 / 非法日期 / 非法 key / 非法 ref。
    bad_user = client.post(
        "/api/v1/reading/pacts",
        json={"itemRef": ref, "deadline": "2026-12-01", "counterpartUsername": "  "},
        headers=ab_env["a"],
    )
    assert bad_user.status_code == 422
    assert bad_user.json()["error"]["type"] == "invalid_reading_pact"
    bad_deadline = client.post(
        "/api/v1/reading/pacts",
        json={"itemRef": ref, "deadline": "soon", "counterpartUsername": "bob"},
        headers=ab_env["a"],
    )
    assert bad_deadline.status_code == 422
    bad_key = client.post(
        "/api/v1/reading/pacts/join",
        json={"pactKey": "short", "itemRef": ref, "deadline": "2026-12-01",
              "counterpartUsername": "alice"},
        headers=ab_env["b"],
    )
    assert bad_key.status_code == 422
