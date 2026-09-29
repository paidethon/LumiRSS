"""NEW-211 标签合并向导 —— 多源→单目标原子合并、引用同步、可撤销台账。

验收：预览真实计数（绑定/重叠/受影响文章/引用数）；apply 单事务完成
（源标签消失、绑定改指、同义词 canonical 改指、组成员释放）；台账可查、
24h 内按 id 撤销（重建源标签 + 原样恢复绑定，含被折叠的重复绑定）；
重复撤销 404（记录已删）；源名被重建占用 409；校验失败 422；A/B 隔离。
"""

import asyncio

from lumirss.new213_tag_groups import TagGroupStore
from lumirss.new214_tag_synonyms import TagSynonymStore
from lumirss.tags import TagStore
from new21x_isolation import seed_library_item

run = asyncio.run

UUID_1 = "11111111-1111-4111-8111-111111111111"
UUID_2 = "22222222-2222-4222-8222-222222222222"
UUID_3 = "33333333-3333-4333-8333-333333333333"
UUID_4 = "44444444-4444-4444-8444-444444444444"


def _seed_tag(client, name: str, items: list[str]) -> int:
    app = client.app
    store = TagStore(app.state.db)
    for item in items:
        run(store.attach(item, name))
    rows = run(app.state.db.fetch_all("SELECT id, name FROM tags WHERE name = ?", (name,)))
    return int(rows[0]["id"])


def test_new211_preview_apply_and_atomic_reference_sync(client):
    for uuid in (UUID_1, UUID_2, UUID_3, UUID_4):
        seed_library_item(client, uuid)
    client.post("/api/v1/tags/assign", json={"itemRef": f"library:{UUID_1}", "name": "旧标签一"})
    client.post("/api/v1/tags/assign", json={"itemRef": f"library:{UUID_2}", "name": "旧标签一"})
    client.post("/api/v1/tags/assign", json={"itemRef": f"library:{UUID_2}", "name": "目标标签"})
    client.post("/api/v1/tags/assign", json={"itemRef": f"library:{UUID_3}", "name": "旧标签二"})
    app = client.app
    tags = run(app.state.db.fetch_all("SELECT id, name FROM tags ORDER BY name"))
    tag_id = {t["name"]: int(t["id"]) for t in tags}
    src1, src2, target = tag_id["旧标签一"], tag_id["旧标签二"], tag_id["目标标签"]

    # 引用面：同义词指向源名 + 互斥组包含源标签
    synonym = run(TagSynonymStore(app.state.db).create("别名一", "旧标签一"))
    assert synonym["canonical"] == "旧标签一"
    group = run(TagGroupStore(app.state.db).create("状态组", ["旧标签一", "目标标签"]))

    # 预览：真实计数（源一 2 条绑定其中 1 条与目标重复；受影响文章去重）
    preview = client.post(
        "/api/v1/tags/merge-wizard/preview",
        json={"sourceIds": [src1, src2], "targetId": target},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["affectedArticles"] == 3
    assert body["references"] == {"synonyms": 1, "groupMemberships": 1}
    by_source = {s["tagId"]: s for s in body["sources"]}
    assert by_source[src1]["bindings"] == 2 and by_source[src1]["overlaps"] == 1
    assert by_source[src1]["willMove"] == 1
    assert by_source[src2]["bindings"] == 1

    # 校验：目标在源列表 → 422
    bad = client.post(
        "/api/v1/tags/merge-wizard/preview",
        json={"sourceIds": [src1, target], "targetId": target},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "invalid_merge_wizard"
    missing = client.post(
        "/api/v1/tags/merge-wizard/preview",
        json={"sourceIds": [src1, 999999], "targetId": target},
    )
    assert missing.status_code == 422

    # 应用：原子合并 + 引用同步
    applied = client.post(
        "/api/v1/tags/merge-wizard/apply",
        json={"sourceIds": [src1, src2], "targetId": target},
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    log_id = result["logId"]
    assert result["synonymsSynced"] == 1
    assert result["groupMembershipsReleased"] == 1
    assert {s["name"] for s in result["mergedSources"]} == {"旧标签一", "旧标签二"}
    names = {t["name"] for t in run(app.state.db.fetch_all("SELECT name FROM tags"))}
    assert names == {"目标标签"}
    target_items = run(
        app.state.db.fetch_all(
            "SELECT item_ref FROM item_tags WHERE tag_id = ? ORDER BY item_ref", (target,)
        )
    )
    assert len(target_items) == 3  # 2 + 1，重复已折叠
    assert run(
        TagSynonymStore(app.state.db).resolve_input("别名一")
    )["canonical"] == "目标标签"
    group_rows = run(
        app.state.db.fetch_all(
            "SELECT tag_id FROM new213_tag_group_members WHERE group_id = ?", (group["id"],)
        )
    )
    assert [int(r["tag_id"]) for r in group_rows] == [target]

    # 台账 + 撤销：重建源标签并原样恢复绑定（含折叠的重复）
    logs = client.get("/api/v1/tags/merge-wizard/logs").json()["items"]
    assert [log["logId"] for log in logs] == [log_id]
    undo = client.post(f"/api/v1/tags/merge-wizard/logs/{log_id}/undo")
    assert undo.status_code == 200, undo.text
    undone = undo.json()
    assert {s["name"] for s in undone["restoredSources"]} == {"旧标签一", "旧标签二"}
    restored = {
        s["name"]: s["restoredBindings"] for s in undone["restoredSources"]
    }
    assert restored["旧标签一"] == 2  # 含折叠的重复绑定，语义与合并前一致
    assert restored["旧标签二"] == 1
    names = {t["name"] for t in run(app.state.db.fetch_all("SELECT name FROM tags"))}
    assert names == {"旧标签一", "旧标签二", "目标标签"}

    # 重复撤销：记录已删 → 404
    again = client.post(f"/api/v1/tags/merge-wizard/logs/{log_id}/undo")
    assert again.status_code == 404
    assert again.json()["error"]["type"] == "merge_log_not_found"

    # 源名被重建占用 → 409：再次合并后手工重建同名源标签
    # （undo 重建的源标签是新 id —— 重新读取后再合并）
    tags_after = run(app.state.db.fetch_all("SELECT id, name FROM tags"))
    tag_id_after = {t["name"]: int(t["id"]) for t in tags_after}
    second = client.post(
        "/api/v1/tags/merge-wizard/apply",
        json={"sourceIds": [tag_id_after["旧标签二"]], "targetId": target},
    )
    assert second.status_code == 200
    second_log = second.json()["logId"]
    client.post("/api/v1/tags/assign", json={"itemRef": f"library:{UUID_4}", "name": "旧标签二"})
    blocked = client.post(f"/api/v1/tags/merge-wizard/logs/{second_log}/undo")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["type"] == "merge_undo_conflict"


def test_new211_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：B 的合并台账对 A 不可见，合并只动 B 自己的标签。"""
    from new21x_isolation import build_two_user_client, isolated_auth_env, make_bookmark

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        member_ref = make_bookmark(client, member, "乙的书签")
        member_tag = client.post(
            "/api/v1/tags/assign",
            json={"itemRef": member_ref, "name": "乙的标签"},
            headers=member,
        )
        assert member_tag.status_code == 201, member_tag.text
        owner_ref = make_bookmark(client, owner, "甲的书签")
        owner_tag = client.post(
            "/api/v1/tags/assign",
            json={"itemRef": owner_ref, "name": "甲的标签"},
            headers=owner,
        )
        assert owner_tag.status_code == 201, owner_tag.text

        # B 在自己域内做一次合并：新建目标 → 合并
        member_ref2 = make_bookmark(client, member, "乙的书签二")
        client.post(
            "/api/v1/tags/assign",
            json={"itemRef": member_ref2, "name": "乙的目标"},
            headers=member,
        )
        member_tags = {
            t["name"]: t["id"] for t in client.get("/api/v1/tags", headers=member).json()["items"]
        }
        merged = client.post(
            "/api/v1/tags/merge-wizard/apply",
            json={"sourceIds": [member_tags["乙的标签"]], "targetId": member_tags["乙的目标"]},
            headers=member,
        )
        assert merged.status_code == 200, merged.text
        log_id = merged.json()["logId"]

        # A 看不到 B 的台账，也撤不掉 B 的合并
        assert client.get("/api/v1/tags/merge-wizard/logs", headers=owner).json()["items"] == []
        assert (
            client.post(f"/api/v1/tags/merge-wizard/logs/{log_id}/undo", headers=owner).status_code
            == 404
        )
        # A 自己的标签未被 B 的合并波及
        owner_names = {
            t["name"] for t in client.get("/api/v1/tags", headers=owner).json()["items"]
        }
        assert owner_names == {"甲的标签"}
        # B 自己仍可撤销
        assert (
            client.post(f"/api/v1/tags/merge-wizard/logs/{log_id}/undo", headers=member).status_code
            == 200
        )
