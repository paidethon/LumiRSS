"""F21 个人术语本 — CRUD/搜索/同词多义。"""


def test_f21_glossary_crud_and_search(client):
    created = client.post(
        "/api/v1/glossary",
        json={"term": "RAG", "definition": "检索增强生成：先检索资料再生成回答。"},
    )
    assert created.status_code == 201, created.text
    # 同词不同含义可并存
    second = client.post(
        "/api/v1/glossary",
        json={"term": "RAG", "definition": "另一含义的同名词目。"},
    )
    assert second.status_code == 201
    found = client.get("/api/v1/glossary?q=RAG").json()["items"]
    assert len(found) == 2
    # 修改
    updated = client.patch(
        f"/api/v1/glossary/{created.json()['id']}",
        json={"term": "RAG", "definition": "修订后的定义。"},
    )
    assert updated.json()["definition"] == "修订后的定义。"
    # 删除
    assert client.delete(f"/api/v1/glossary/{created.json()['id']}").status_code == 204
    assert client.get("/api/v1/glossary?q=检索增强").json()["items"] == []


def test_f21_glossary_validation(client):
    assert (
        client.post(
            "/api/v1/glossary", json={"term": "", "definition": "x"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/glossary", json={"term": "t", "definition": "  "}
        ).status_code
        == 400
    )
