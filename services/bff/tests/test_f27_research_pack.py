"""F27 工作区研究包导出 — Markdown + manifest 边界测试。"""


def test_f27_research_pack_markdown_and_manifest(client):
    created = client.post(
        "/api/v1/workspaces",
        json={"name": "研究包工作区", "description": "范围说明"},
    ).json()
    entry_ref = "e1.MDAwNjU5ZTA3YWFlZTI0ZA"
    client.post(
        "/api/v1/workspaces/read-later/items", json={"itemRef": f"rss:{entry_ref}"}
    )
    # 成员加入该工作区（通过工作区 items 端点）
    client.post(
        f"/api/v1/workspaces/{created['id']}/items",
        json={"itemRef": f"rss:{entry_ref}"},
    )

    response = client.post(
        f"/api/v1/workspaces/{created['id']}/research-pack",
        json={"title": "我的研究包", "includeNotes": True},
    )
    assert response.status_code == 200, response.text
    text = response.text
    assert text.startswith("# 我的研究包（研究包）")
    assert "```json" in text  # manifest 内嵌
    assert '"kind": "lumirss-research-pack"' in text
    # 不包含服务器路径/令牌
    assert "/home/" not in text
    assert "token" not in text.lower()


def test_f27_missing_workspace_404(client):
    response = client.post(
        "/api/v1/workspaces/ws-does-not-exist/research-pack", json={}
    )
    assert response.status_code == 404
