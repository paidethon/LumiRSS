"""NEW-258 研究大纲编排 — 章节 + 引文/笔记/小结素材 + Markdown 草稿。

- 章节/素材上移下移 + 跨章节分配（诚实标注：不是拖拽，边界返回
  moved=0）；quote 必须带出处（citation）；
- 草稿：带引用的 Markdown 只读生成，不落库不覆盖；
- 隔离：A 的大纲与草稿对 B 404。
"""


from fastapi.testclient import TestClient

from new2xx_ab import ab_env  # noqa: F401,F811


def _project(client: TestClient) -> dict:
    return client.post(
        "/api/v1/research/projects", json={"title": "大纲项目"}
    ).json()


def test_new258_outline_sections_items_and_draft(client):  # noqa: F811
    """两章 → 各放素材 → 上移下移 + 跨章分配 → 草稿含引用块。"""
    project = _project(client)
    base = f"/api/v1/research/projects/{project['id']}"

    s1 = client.post(f"{base}/outline-sections", json={"title": "第一章 背景"}).json()
    s2 = client.post(f"{base}/outline-sections", json={"title": "第二章 证据"}).json()
    assert s1["items"] == [] and s2["items"] == []

    quote = client.post(
        f"/api/v1/research/outline-sections/{s1['id']}/items",
        json={"kind": "quote", "content": "「滤池于 1934 年投产」", "citation": "市政档案卷三 p.12"},
    )
    assert quote.status_code == 201, quote.text
    note = client.post(
        f"/api/v1/research/outline-sections/{s1['id']}/items",
        json={"kind": "note", "content": "注意：年份另有 1935 说"},
    )
    assert note.status_code == 201
    summary = client.post(
        f"/api/v1/research/outline-sections/{s2['id']}/items",
        json={"kind": "summary", "content": "两说并存，倾向 1934"},
    )
    assert summary.status_code == 201

    # 素材上移下移；边界诚实 moved=0
    up = client.post(
        f"/api/v1/research/outline-items/{note.json()['id']}/move", json={"direction": "up"}
    )
    assert up.status_code == 200 and up.json()["moved"] == 1
    edge = client.post(
        f"/api/v1/research/outline-items/{note.json()['id']}/move", json={"direction": "down"}
    )
    assert edge.json()["moved"] == 1
    boundary = client.post(
        f"/api/v1/research/outline-items/{note.json()['id']}/move", json={"direction": "down"}
    )
    assert boundary.status_code == 200 and boundary.json()["moved"] == 0

    # 跨章节分配（summary 移到第一章）。
    assigned = client.post(
        f"/api/v1/research/outline-items/{summary.json()['id']}/assign",
        json={"targetSectionId": s1["id"]},
    )
    assert assigned.status_code == 200, assigned.text

    # 章节下移。
    moved_section = client.post(
        f"/api/v1/research/outline-sections/{s1['id']}/move", json={"direction": "down"}
    )
    assert moved_section.json()["moved"] == 1

    outline = client.get(f"{base}/outline").json()
    assert [sec["title"] for sec in outline["sections"]] == ["第二章 证据", "第一章 背景"]
    all_items = [i for sec in outline["sections"] for i in sec["items"]]
    assert len(all_items) == 3

    draft = client.get(f"{base}/outline-draft").json()
    assert draft["itemCount"] == 3
    assert "> 「滤池于 1934 年投产」" in draft["markdown"]
    assert "— 市政档案卷三 p.12" in draft["markdown"]
    assert "**小结**" in draft["markdown"]
    assert draft["markdown"].startswith("# 大纲项目")


def test_new258_validation_and_errors(client):  # noqa: F811
    """quote 无出处 → 422；坏 kind / 坏 direction / 同章分配 → 422；
    未知章节 → 404。"""
    project = _project(client)
    base = f"/api/v1/research/projects/{project['id']}"
    section = client.post(
        f"{base}/outline-sections", json={"title": "章节"}
    ).json()

    assert (
        client.post(
            f"/api/v1/research/outline-sections/{section['id']}/items",
            json={"kind": "quote", "content": "无出处引文"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/research/outline-sections/{section['id']}/items",
            json={"kind": "diagram", "content": "x"},
        ).status_code
        == 422
    )
    item = client.post(
        f"/api/v1/research/outline-sections/{section['id']}/items",
        json={"kind": "note", "content": "n"},
    ).json()
    assert (
        client.post(
            f"/api/v1/research/outline-items/{item['id']}/move", json={"direction": "left"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/research/outline-items/{item['id']}/assign",
            json={"targetSectionId": section["id"]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{base}/outline-items/{item['id']}/assign",
            json={"targetSectionId": "missing"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/research/outline-sections/{section['id']}"
        ).status_code
        == 204
    )
    assert client.get(f"{base}/outline").json()["sections"] == []


def test_new258_ab_isolation(ab_env):  # noqa: F811
    """A 的大纲/素材/草稿对 B 不可见。"""
    client = ab_env["client"]
    project = client.post(
        "/api/v1/research/projects", json={"title": "A 大纲"}, headers=ab_env["a"]
    ).json()
    section_id = client.post(
        f"/api/v1/research/projects/{project['id']}/outline-sections",
        json={"title": "A 章"},
        headers=ab_env["a"],
    ).json()["id"]

    assert (
        client.get(
            f"/api/v1/research/projects/{project['id']}/outline-draft",
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/research/outline-sections/{section_id}/items",
            json={"kind": "note", "content": "B 塞的"},
            headers=ab_env["b"],
        ).status_code
        == 404
    )
