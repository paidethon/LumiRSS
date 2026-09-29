"""NEW-254 研究术语表 — 项目私有术语 + 采用解释 + 出处 + 阅读时查词。

- UNIQUE(project_id, term)：同项目同名术语 → 409（当前采用唯一）；
- lookup 精确 + 大小写不敏感兜底；查不到 → found=false（诚实空态）；
- 边界：绝不触碰全局词典（glossary 表零交互——用既有全局词典 API
  证明不受影响）；
- 隔离：术语只在本项目内可见（跨项目与跨用户都查不到）。
"""


from fastapi.testclient import TestClient

from new2xx_ab import ab_env  # noqa: F401,F811


def _project(client: TestClient, title: str = "术语项目") -> dict:
    return client.post("/api/v1/research/projects", json={"title": title}).json()


def test_new254_term_crud_and_lookup(client):  # noqa: F811
    """建术语 → 同名 409 → lookup 精确/大小写不敏感/未命中 → PATCH 解释
    → 全局词典零改动。"""
    project = _project(client)
    made = client.post(
        f"/api/v1/research/projects/{project['id']}/glossary",
        json={
            "term": "滤池",
            "interpretation": "本研究里特指 1930 年代慢滤池工艺",
            "source": "市政档案卷三",
        },
    )
    assert made.status_code == 201, made.text
    term = made.json()
    assert term["projectId"] == project["id"]

    conflict = client.post(
        f"/api/v1/research/projects/{project['id']}/glossary",
        json={"term": "滤池", "interpretation": "另一种解释"},
    )
    assert conflict.status_code == 409, conflict.text

    exact = client.get(
        f"/api/v1/research/projects/{project['id']}/glossary/lookup",
        params={"term": "滤池"},
    )
    assert exact.status_code == 200
    assert exact.json()["found"] is True
    assert "慢滤池" in exact.json()["match"]["interpretation"]

    ci = client.get(
        f"/api/v1/research/projects/{project['id']}/glossary/lookup",
        params={"term": "滤池"},
    )
    assert ci.json()["found"] is True

    miss = client.get(
        f"/api/v1/research/projects/{project['id']}/glossary/lookup",
        params={"term": "不存在的词"},
    )
    assert miss.status_code == 200
    assert miss.json()["found"] is False and miss.json()["match"] is None

    patched = client.patch(
        f"/api/v1/research/glossary-terms/{term['id']}",
        json={"interpretation": "改为：特指快滤池（1936 后）", "source": None},
    )
    assert patched.status_code == 200, patched.text
    assert "快滤池" in patched.json()["interpretation"]

    # 全局词典零交互：研究术语不进全局词典。
    global_terms = client.get("/api/v1/glossary")
    if global_terms.status_code == 200:
        names = [
            item.get("term")
            for item in global_terms.json().get("items", [])
        ]
        assert "滤池" not in names

    assert (
        client.delete(
            f"/api/v1/research/glossary-terms/{term['id']}"
        ).status_code
        == 204
    )


def test_new254_validation_and_cross_project(client):  # noqa: F811
    """空术语/解释 → 422；未知术语 → 404；术语不跨项目可见。"""
    p1 = _project(client, "项目一")
    p2 = _project(client, "项目二")

    assert (
        client.post(
            f"/api/v1/research/projects/{p1['id']}/glossary",
            json={"term": "", "interpretation": "x"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/research/projects/{p1['id']}/glossary",
            json={"term": "t", "interpretation": None},
        ).status_code
        == 422
    )
    term = client.post(
        f"/api/v1/research/projects/{p1['id']}/glossary",
        json={"term": "项目内词", "interpretation": "只属于项目一"},
    ).json()

    # 项目二查同一词 → 查不到（项目级隔离）。
    other = client.get(
        f"/api/v1/research/projects/{p2['id']}/glossary/lookup",
        params={"term": "项目内词"},
    ).json()
    assert other["found"] is False
    assert client.get(
        f"/api/v1/research/projects/{p2['id']}/glossary"
    ).json()["items"] == []

    assert (
        client.patch(
            "/api/v1/research/glossary-terms/missing-term",
            json={"interpretation": "x"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/research/projects/{p1['id']}/glossary"
        ).json()["items"][0]["id"]
        == term["id"]
    )


def test_new254_ab_isolation(ab_env):  # noqa: F811
    """A 的项目术语对 B 完全不可见（跨用户 404 / 查词落空）。"""
    client = ab_env["client"]
    project = client.post(
        "/api/v1/research/projects", json={"title": "A 术语"}, headers=ab_env["a"]
    ).json()
    term_id = client.post(
        f"/api/v1/research/projects/{project['id']}/glossary",
        json={"term": "A 的术语", "interpretation": "A 的解释"},
        headers=ab_env["a"],
    ).json()["id"]

    assert (
        client.get(
            f"/api/v1/research/projects/{project['id']}/glossary",
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/research/glossary-terms/{term_id}", headers=ab_env["b"]
        ).status_code
        == 404
    )
    # A 自己查词照常。
    assert (
        client.get(
            f"/api/v1/research/projects/{project['id']}/glossary/lookup",
            params={"term": "A 的术语"},
            headers=ab_env["a"],
        ).json()["found"]
        is True
    )
