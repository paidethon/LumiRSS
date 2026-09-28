"""NEW-215 标签使用清理台 —— 三桶报告 + 删除保护。

验收：报告桶划分真实（有绑定 → inUse；仅被同义词/互斥组引用 →
referencedOnly；两者皆无 → unused）；删除仅引用标签未确认 → 整批 409
（绝不一键误删被规则依赖的标签）；确认后删除并同步清理引用；A/B 隔离。
"""

import asyncio

from lumirss.new213_tag_groups import TagGroupStore
from lumirss.new214_tag_synonyms import TagSynonymStore
from lumirss.tags import TagStore

run = asyncio.run

REF = "library:11111111-1111-4111-8111-111111111111"


def test_new215_buckets_and_protected_delete(client):
    app = client.app
    store = TagStore(app.state.db)
    run(store.attach(REF, "在用标签"))
    run(store.attach("library:22222222-2222-4222-8222-222222222222", "引用标签"))
    run(store.detach("library:22222222-2222-4222-8222-222222222222", "引用标签"))  # 保留标签行，清空绑定
    run(store.attach("library:33333333-3333-4333-8333-333333333333", "无主标签"))
    run(store.detach("library:33333333-3333-4333-8333-333333333333", "无主标签"))
    tag_ids = {
        str(r["name"]): int(r["id"])
        for r in run(app.state.db.fetch_all("SELECT id, name FROM tags"))
    }
    run(TagSynonymStore(app.state.db).create("引用别名", "引用标签"))
    run(TagGroupStore(app.state.db).create("引用组", ["引用标签", "在用标签"]))

    report = client.get("/api/v1/tags/cleanup/report").json()
    buckets = report["buckets"]
    by_name = {
        bucket: {e["name"] for e in entries} for bucket, entries in buckets.items()
    }
    assert by_name["inUse"] == {"在用标签"}
    assert by_name["referencedOnly"] == {"引用标签"}
    assert by_name["unused"] == {"无主标签"}
    referenced = buckets["referencedOnly"][0]
    assert referenced["references"]["synonyms"] == 1
    assert referenced["references"]["groupMemberships"] == 1

    # 保护：删除带引用的标签（混在批量里）→ 整批 409，标签全部保留
    blocked = client.post(
        "/api/v1/tags/cleanup/delete",
        json={"tagIds": [tag_ids["无主标签"], tag_ids["引用标签"]]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["type"] == "tag_cleanup_blocked"
    assert blocked.json()["error"]["tagId"] == tag_ids["引用标签"]
    remaining = {t["name"] for t in run(app.state.db.fetch_all("SELECT name FROM tags"))}
    assert remaining == {"在用标签", "引用标签", "无主标签"}

    # 只删无主标签 → OK
    ok = client.post(
        "/api/v1/tags/cleanup/delete", json={"tagIds": [tag_ids["无主标签"]]}
    )
    assert ok.status_code == 200, ok.text
    # 确认引用后删除引用标签 → 同步清理同义词与组成员
    acknowledged = client.post(
        "/api/v1/tags/cleanup/delete",
        json={"tagIds": [tag_ids["引用标签"]], "acknowledgeReferences": True},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    result = acknowledged.json()["deleted"][0]
    assert result["deletedSynonyms"] == 1
    assert result["deletedGroupMemberships"] == 1
    assert run(app.state.db.fetch_one("SELECT id FROM new214_tag_synonyms")) is None
    names = {t["name"] for t in run(app.state.db.fetch_all("SELECT name FROM tags"))}
    assert names == {"在用标签"}

    # 校验：不存在的标签 → 422
    bogus = client.post("/api/v1/tags/cleanup/delete", json={"tagIds": [999999]})
    assert bogus.status_code == 422


def test_new215_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：A 的清理报告看不到 B 的标签，也删不到 B 的标签。"""
    from new21x_isolation import build_two_user_client, isolated_auth_env, make_bookmark

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        member_ref = make_bookmark(client, member, "乙的孤儿书签")
        client.post(
            "/api/v1/tags/assign",
            json={"itemRef": member_ref, "name": "乙的孤儿标签"},
            headers=member,
        )
        member_tags = {
            t["name"]: t["id"] for t in client.get("/api/v1/tags", headers=member).json()["items"]
        }
        # B 删自己的
        deleted = client.post(
            "/api/v1/tags/cleanup/delete",
            json={"tagIds": [member_tags["乙的孤儿标签"]]},
            headers=member,
        )
        assert deleted.status_code == 200

        # B 重建同名标签后，A 侧完全不可见、删不到
        client.post(
            "/api/v1/tags/assign",
            json={"itemRef": member_ref, "name": "乙的孤儿标签"},
            headers=member,
        )
        member_tags = {
            t["name"]: t["id"] for t in client.get("/api/v1/tags", headers=member).json()["items"]
        }
        owner_report = client.get("/api/v1/tags/cleanup/report", headers=owner).json()
        all_owner_names = {
            e["name"] for bucket in owner_report["buckets"].values() for e in bucket
        }
        assert all_owner_names == set()
        assert (
            client.post(
                "/api/v1/tags/cleanup/delete",
                json={"tagIds": [member_tags["乙的孤儿标签"]]},
                headers=owner,
            ).status_code
            == 422
        )
        # B 自己仍可删
        assert (
            client.post(
                "/api/v1/tags/cleanup/delete",
                json={"tagIds": [member_tags["乙的孤儿标签"]]},
                headers=member,
            ).status_code
            == 200
        )
