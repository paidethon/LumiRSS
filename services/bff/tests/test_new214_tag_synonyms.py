"""NEW-214 标签同义词字典 —— 别名登记、唯一性、解析提示；原文零改写。

验收：canonical 必须是已存在标签（422）；alias==canonical 422；重复
别名 409；resolve 精确命中别名→规范标签、输入本身是标签名→直接返回、
前缀→候选集；删除 + 404；A/B 隔离（A 的字典对 B 不可见）。
"""

import asyncio

from lumirss.new214_tag_synonyms import TagSynonymStore
from lumirss.tags import TagStore

run = asyncio.run


def test_new214_synonym_crud_and_resolution(client):
    app = client.app
    store = TagStore(app.state.db)
    run(store.attach("library:11111111-1111-4111-8111-111111111111", "人工智能"))
    run(store.attach("library:22222222-2222-4222-8222-222222222222", "机器学习"))

    # 校验：规范标签必须存在 / 别名=规范名 / 空
    missing = client.post(
        "/api/v1/tag-synonyms", json={"alias": "AI", "canonical": "不存在的标签"}
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["type"] == "invalid_tag_synonym"
    same = client.post(
        "/api/v1/tag-synonyms", json={"alias": "人工智能", "canonical": "人工智能"}
    )
    assert same.status_code == 422

    created = client.post(
        "/api/v1/tag-synonyms", json={"alias": "AI", "canonical": "人工智能"}
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    # 重复别名（唯一）→ 409
    duplicate = client.post(
        "/api/v1/tag-synonyms", json={"alias": "ai", "canonical": "机器学习"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["type"] == "tag_synonym_conflict"

    listing = client.get("/api/v1/tag-synonyms").json()["items"]
    assert [(i["alias"], i["canonical"]) for i in listing] == [("AI", "人工智能")]

    # 解析提示：精确别名 → 规范标签；标签名直接返回；前缀 → 候选
    exact = client.get("/api/v1/tag-synonyms/resolve", params={"q": " ai "}).json()
    assert exact == {
        "input": "ai",
        "exact": True,
        "canonical": "人工智能",
        "suggestions": [],
    }
    itself = client.get("/api/v1/tag-synonyms/resolve", params={"q": "机器学习"}).json()
    assert itself["exact"] is True and itself["canonical"] == "机器学习"
    client.post("/api/v1/tag-synonyms", json={"alias": "ML", "canonical": "机器学习"})
    suggestions = client.get("/api/v1/tag-synonyms/resolve", params={"q": "机"}).json()
    assert suggestions["exact"] is False
    assert suggestions["suggestions"] == ["机器学习"]
    nothing = client.get("/api/v1/tag-synonyms/resolve", params={"q": "区块链"}).json()
    assert nothing["exact"] is False and nothing["suggestions"] == []

    # 删除 + 404
    assert client.delete(f"/api/v1/tag-synonyms/{entry['id']}").status_code == 204
    gone = client.delete(f"/api/v1/tag-synonyms/{entry['id']}")
    assert gone.status_code == 404
    after = client.get("/api/v1/tag-synonyms/resolve", params={"q": "AI"}).json()
    assert after["exact"] is False and after["suggestions"] == []

    # 原文零改写：本套件没有任何内容写路径——断言库中不存在内容表变更入口
    assert not hasattr(TagSynonymStore(app.state.db), "rewrite_content")


def test_new214_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：B 登记的别名对 A 不可见、不可删。"""
    from new21x_isolation import build_two_user_client, isolated_auth_env, make_bookmark

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        ref = make_bookmark(client, member, "乙的书签")
        client.post(
            "/api/v1/tags/assign",
            json={"itemRef": ref, "name": "标签甲乙"},
            headers=member,
        )
        created = client.post(
            "/api/v1/tag-synonyms",
            json={"alias": "乙的别名", "canonical": "标签甲乙"},
            headers=member,
        )
        assert created.status_code == 201, created.text
        entry_id = created.json()["id"]

        # A 看不到 B 的别名，删不掉，resolve 也不命中
        assert client.get("/api/v1/tag-synonyms", headers=owner).json()["items"] == []
        assert (
            client.delete(f"/api/v1/tag-synonyms/{entry_id}", headers=owner).status_code
            == 404
        )
        resolved = client.get(
            "/api/v1/tag-synonyms/resolve", params={"q": "乙的别名"}, headers=owner
        ).json()
        assert resolved["exact"] is False
        # B 自己仍可见、可用、可删
        assert [
            (i["alias"], i["canonical"])
            for i in client.get("/api/v1/tag-synonyms", headers=member).json()["items"]
        ] == [("乙的别名", "标签甲乙")]
        assert (
            client.delete(f"/api/v1/tag-synonyms/{entry_id}", headers=member).status_code
            == 204
        )
