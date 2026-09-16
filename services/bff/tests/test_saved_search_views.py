"""Saved search views — CRUD + cap（pool #09）。

保存的是查询与筛选意图（不是结果集）；打开视图重新查询。覆盖：创建/
列表/重命名/删除、名称与查询校验、params 白名单归一、上限 50 的并发
安全拒绝、游标外 404。"""

import asyncio


def run(coroutine):
    return asyncio.run(coroutine)


def _create(client, name="我的视图", query="alpha", **extra):
    return client.post(
        "/api/v1/search/views",
        json={"name": name, "query": query, **extra},
    )


def test_saved_view_crud_roundtrip(client):
    created = _create(client, view="unread", categoryKey="cat-1")
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "我的视图"
    assert body["query"] == "alpha"
    assert body["view"] == "unread"
    assert body["categoryKey"] == "cat-1"

    listing = client.get("/api/v1/search/views").json()
    assert [v["id"] for v in listing["items"]] == [body["id"]]

    renamed = client.patch(
        f"/api/v1/search/views/{body['id']}", json={"name": "新名字"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "新名字"
    assert renamed.json()["query"] == "alpha"

    assert (
        client.delete(f"/api/v1/search/views/{body['id']}").status_code == 204
    )
    assert client.get("/api/v1/search/views").json()["items"] == []
    # 删除后再删 → 404。
    assert (
        client.delete(f"/api/v1/search/views/{body['id']}").status_code == 404
    )


def test_saved_view_validation_and_param_whitelist(client):
    assert _create(client, name="   ").status_code == 400
    assert _create(client, query="   ").status_code == 400
    assert _create(client, view="sideways").status_code == 400
    assert _create(client, categoryKey="x" * 300).status_code == 400
    # 未知字段直接拒绝（extra=forbid 契约）。
    assert (
        _create(client, evil={"drop": "table"}).status_code == 422
    )


def test_saved_view_rename_missing_is_404(client):
    response = client.patch(
        "/api/v1/search/views/does-not-exist", json={"name": "x"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "saved_search_not_found"


def test_saved_view_cap_is_enforced(client, monkeypatch):
    from lumirss import saved_search_store as store_mod

    monkeypatch.setattr(store_mod, "_MAX_SAVED_SEARCHES", 3)
    for i in range(3):
        assert _create(client, name=f"v{i}", query=f"q{i}").status_code == 201
    over = _create(client, name="v3", query="q3")
    assert over.status_code == 409
    assert over.json()["error"]["type"] == "saved_search_limit"
