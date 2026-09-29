"""NEW-213 标签互斥组 —— 组 CRUD、冲突预览、批量选保留值解决。

验收：成员必须是已存在标签（422）；冲突 = 同一内容绑定 ≥2 组内标签
（服务端真实查询）；解决逐条指定 keep，其余组内绑定被拆下；keep 未
绑定在该内容上 → 整批拒绝 409（绝不盲拆）；A/B 隔离。
"""

import asyncio

from lumirss.tags import TagStore

run = asyncio.run

REF_A = "library:11111111-1111-4111-8111-111111111111"
REF_B = "library:22222222-2222-4222-8222-222222222222"


def test_new213_groups_conflicts_and_resolve(client):
    app = client.app
    store = TagStore(app.state.db)
    for name in ("热", "冷", "温"):
        run(store.attach(REF_A, name))
    run(store.attach(REF_B, "热"))
    # 校验：未知标签成员 → 422；成员 <2 → 422
    bad = client.post("/api/v1/tag-groups", json={"name": "温度", "members": ["热", "不存在"]})
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "invalid_tag_group"
    small = client.post("/api/v1/tag-groups", json={"name": "温度", "members": ["热"]})
    assert small.status_code == 422

    created = client.post("/api/v1/tag-groups", json={"name": "温度", "members": ["热", "冷", "温"]})
    assert created.status_code == 201, created.text
    group_id = created.json()["id"]

    listing = client.get("/api/v1/tag-groups").json()["items"]
    assert listing[0]["name"] == "温度"
    assert {m["name"] for m in listing[0]["members"]} == {"热", "冷", "温"}

    # 冲突预览：REF_A 绑了 3 个组内标签 → 冲突；REF_B 只有 1 个 → 不在列
    conflicts = client.get(f"/api/v1/tag-groups/{group_id}/conflicts").json()
    assert [item["ref"] for item in conflicts["items"]] == [REF_A]
    assert {t["name"] for t in conflicts["items"][0]["tags"]} == {"热", "冷", "温"}
    missing = client.get("/api/v1/tag-groups/999999/conflicts")
    assert missing.status_code == 404

    # 解决：keep=冷 → 热/温 从 REF_A 拆下；keep 未绑定 → 整批 409
    bad_keep = client.post(
        f"/api/v1/tag-groups/{group_id}/resolve",
        json={"resolutions": [{"ref": REF_A, "keep": "不存在的标签"}]},
    )
    assert bad_keep.status_code in (409, 422)
    unbound = client.post(
        f"/api/v1/tag-groups/{group_id}/resolve",
        json={
            "resolutions": [
                {"ref": REF_A, "keep": "冷"},
                {"ref": REF_B, "keep": "冷"},  # REF_B 没绑「冷」，无冲突
            ]
        },
    )
    assert unbound.status_code == 409
    assert unbound.json()["error"]["type"] == "tag_group_conflict"
    # 整批拒绝后 REF_A 仍绑着 3 个组内标签（无半拆状态）
    still = client.get(f"/api/v1/tag-groups/{group_id}/conflicts").json()
    assert len(still["items"]) == 1

    resolved = client.post(
        f"/api/v1/tag-groups/{group_id}/resolve",
        json={"resolutions": [{"ref": REF_A, "keep": "冷"}]},
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["resolved"][0]["kept"] == "冷"
    assert set(body["resolved"][0]["removed"]) == {"热", "温"}
    items = run(
        store.tags_for_item(REF_A)
    )
    assert [t["name"] for t in items] == ["冷"]
    # REF_B 未被波及
    assert [t["name"] for t in run(store.tags_for_item(REF_B))] == ["热"]

    # 组删除 → 成员行级联消失，标签本身不受影响
    assert client.delete(f"/api/v1/tag-groups/{group_id}").status_code == 204
    assert client.get("/api/v1/tag-groups").json()["items"] == []
    assert [t["name"] for t in run(store.tags_for_item(REF_A))] == ["冷"]


def test_new213_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：A 的互斥组看不到也解决不了 B 的标签冲突。"""
    from new21x_isolation import build_two_user_client, isolated_auth_env, make_bookmark

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        member_ref = make_bookmark(client, member, "乙的冲突书签")
        member_created = client.post(
            "/api/v1/tag-groups",
            json={"name": "乙的温度", "members": ["乙热", "乙冷"]},
            headers=member,
        )
        # B 还没有这些标签 → 422；先建标签再建组
        assert member_created.status_code == 422
        for name in ("乙热", "乙冷"):
            client.post(
                "/api/v1/tags/assign",
                json={"itemRef": member_ref, "name": name},
                headers=member,
            )
        member_created = client.post(
            "/api/v1/tag-groups",
            json={"name": "乙的温度", "members": ["乙热", "乙冷"]},
            headers=member,
        )
        assert member_created.status_code == 201
        group_id = member_created.json()["id"]

        # A 的组列表为空，也读不到 B 的组冲突
        assert client.get("/api/v1/tag-groups", headers=owner).json()["items"] == []
        assert (
            client.get(f"/api/v1/tag-groups/{group_id}/conflicts", headers=owner).status_code
            == 404
        )
        # B 自己可读、可删
        assert (
            client.get(f"/api/v1/tag-groups/{group_id}/conflicts", headers=member).status_code
            == 200
        )
        assert (
            client.delete(f"/api/v1/tag-groups/{group_id}", headers=owner).status_code == 404
        )
