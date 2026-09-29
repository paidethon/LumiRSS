"""NEW-212 标签改名影响图 —— 引用清单 + 确认后同步改写。

验收：影响图区分 willRewrite（同义词 canonical，名字键）与 autoFollow
（互斥组/绑定，id 键）并给出真实数量；应用后标签文字改变且同义词
canonical 同步改指新名、id 键引用自动跟随；同名冲突 422；A/B 隔离。
"""

import asyncio

from lumirss.new213_tag_groups import TagGroupStore
from lumirss.new214_tag_synonyms import TagSynonymStore
from lumirss.tags import TagStore

run = asyncio.run


def test_new212_impact_graph_and_synced_rename(client):
    app = client.app
    store = TagStore(app.state.db)
    run(store.attach("library:11111111-1111-4111-8111-111111111111", "周报"))
    run(store.attach("library:22222222-2222-4222-8222-222222222222", "周报"))
    run(store.attach("library:33333333-3333-4333-8333-333333333333", "日报"))
    tag_id = int(run(app.state.db.fetch_one("SELECT id FROM tags WHERE name = '周报'"))["id"])
    run(TagSynonymStore(app.state.db).create("weekly", "周报"))
    group = run(TagGroupStore(app.state.db).create("节奏组", ["周报", "日报"]))

    # 影响图（只读）：1 条同义词会改写；组 + 绑定自动跟随
    impact = client.post(
        "/api/v1/tags/rename-impact", json={"tagId": tag_id, "newName": "每周简报"}
    )
    assert impact.status_code == 200, impact.text
    body = impact.json()
    assert body["oldName"] == "周报" and body["newName"] == "每周简报"
    assert [w["alias"] for w in body["willRewrite"]] == ["weekly"]
    assert {a["kind"] for a in body["autoFollow"]} == {"group"}
    assert body["bindings"] == 2

    # 校验：新名已被其他标签占用 → 422
    run(store.attach("library:33333333-3333-4333-8333-333333333333", "占用名"))
    conflict = client.post(
        "/api/v1/tags/rename-impact", json={"tagId": tag_id, "newName": "占用名"}
    )
    assert conflict.status_code == 422
    assert conflict.json()["error"]["type"] == "invalid_tag"
    missing = client.post(
        "/api/v1/tags/rename-impact", json={"tagId": 999999, "newName": "不存在"}
    )
    assert missing.status_code == 422

    # 确认应用：改名 + 同义词同步；组（id 键）不动但继续跟随
    applied = client.post(
        "/api/v1/tags/rename-with-sync", json={"tagId": tag_id, "newName": "每周简报"}
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["synonymsRewritten"] == 1
    assert result["bindingsFollowed"] == 2
    names = {t["name"] for t in run(app.state.db.fetch_all("SELECT name FROM tags"))}
    assert "每周简报" in names and "周报" not in names
    synonym = run(
        app.state.db.fetch_one("SELECT canonical FROM new214_tag_synonyms WHERE alias = 'weekly'")
    )
    assert synonym["canonical"] == "每周简报"
    members = run(
        app.state.db.fetch_all(
            "SELECT tag_id FROM new213_tag_group_members WHERE group_id = ?", (group["id"],)
        )
    )
    assert len(members) == 2  # id 键引用原样保留
    resolved = run(TagSynonymStore(app.state.db).resolve_input("weekly"))
    assert resolved["canonical"] == "每周简报"


def test_new212_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：B 的同名标签改名不影响 A 的同名标签与引用。"""
    from new21x_isolation import build_two_user_client, isolated_auth_env, make_bookmark

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        for headers in (owner, member):
            ref = make_bookmark(client, headers, f"书签-{headers['cookie'][:6]}")
            created = client.post(
                "/api/v1/tags/assign",
                json={"itemRef": ref, "name": "共享名"},
                headers=headers,
            )
            assert created.status_code == 201, created.text

        # B 先垫一个额外标签，让「乙改名」的 id 在 A 的库里不存在
        member_ref2 = make_bookmark(client, member, "乙的垫高书签")
        client.post(
            "/api/v1/tags/assign",
            json={"itemRef": member_ref2, "name": "垫高标签"},
            headers=member,
        )
        member_tags = {
            t["name"]: t["id"] for t in client.get("/api/v1/tags", headers=member).json()["items"]
        }
        renamed = client.post(
            "/api/v1/tags/rename-with-sync",
            json={"tagId": member_tags["共享名"], "newName": "乙改名"},
            headers=member,
        )
        assert renamed.status_code == 200, renamed.text

        # A 的同名标签原样保留
        owner_names = {
            t["name"] for t in client.get("/api/v1/tags", headers=owner).json()["items"]
        }
        assert owner_names == {"共享名"}
        # A 也改不了 B 的标签：垫高标签 id=2 只存在于 B 的库，A 侧 422
        member_tags_now = {
            t["name"]: t["id"] for t in client.get("/api/v1/tags", headers=member).json()["items"]
        }
        assert (
            client.post(
                "/api/v1/tags/rename-with-sync",
                json={"tagId": member_tags_now["垫高标签"], "newName": "甲乱改"},
                headers=owner,
            ).status_code
            == 422
        )
