"""N116 汇编只读分享包测试 —— 自包含静态 HTML（无脚本、无秘密）。

- 文件可构建：text/html attachment、单文件、零 <script>；
- 内容：分节标题 + 条目标题/摘录 + 来源标注 + 隐私提示；
- 引文策略：绝对 http(s) 引文恒为真链接；应用内路由引文仅在配置
  LUMIRSS_PUBLIC_URL 后拼公开绝对链接（单元覆盖无基底分支）；
- 隐私硬断言：无 cookie/token/绝对本地路径；includeNotes=true →
  422（固定 false 契约）；笔记绝不进包。
"""

import pytest


@pytest.fixture()
def compiled_workspace(client):
    """一个带 2 个 library 成员的工作区 + 一条标题匹配的私人工作区笔记
    （compile 的 notes 通道会拾取它——分享包必须绝不携带）。"""
    created = client.post("/api/v1/workspaces", json={"name": "N116 分享"})
    workspace_id = created.json()["id"]
    refs = []
    for index in range(2):
        ref = client.post(
            "/api/v1/library/bookmarks",
            json={
                "url": f"https://source.example/n116-{index}",
                "title": f"来源条目{index}",
            },
        ).json()["ref"]
        client.post(f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": ref})
        refs.append(ref)
    note = client.post(
        "/api/v1/library/notes",
        json={
            "title": "来源条目0",
            "contentMd": "私人笔记0——绝不进分享包",
            "workspaceId": workspace_id,
        },
    )
    assert note.status_code == 201
    section = client.post(
        f"/api/v1/workspaces/{workspace_id}/sections", json={"title": "背景"}
    ).json()
    for ref in refs:
        client.post(
            f"/api/v1/workspaces/{workspace_id}/sections/{section['id']}/items",
            json={"itemRef": ref},
        )
    return workspace_id, refs


def _export(client, workspace_id: str, json_body: dict | None = None):
    return client.post(
        f"/api/v1/workspaces/{workspace_id}/share-package",
        json=json_body if json_body is not None else {},
    )


def test_share_package_builds_self_contained_html(client, compiled_workspace):
    workspace_id, _refs = compiled_workspace
    response = _export(client, workspace_id)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "attachment" in response.headers["content-disposition"]
    html = response.text
    # 自包含：无脚本、无外链静态资源。
    assert "<script" not in html.lower()
    assert "<link" not in html.lower()
    # 内容齐全：分节 + 条目 + 来源标注 + 隐私提示。
    assert "背景" in html
    assert "来源条目0" in html
    assert "来源标注" in html
    assert "导出内容包含私人摘录" in html
    # 私人笔记绝不进包（includeNotes 固定 false）。
    assert "私人笔记" not in html
    # 无 cookie / token / 绝对本地路径。
    lowered = html.lower()
    for forbidden in ("set-cookie", "cookie:", "token", "/home/", "/tmp/", "lumi.sqlite", "secrets"):
        assert forbidden not in lowered, forbidden


def test_share_package_public_urls_are_linked(client, compiled_workspace):
    workspace_id, _refs = compiled_workspace
    # 绝对 http(s) 引文（library 外链）本来就是公开 URL → 恒为真链接。
    html = _export(client, workspace_id).text
    assert 'href="https://source.example/n116-0"' in html


def test_share_package_app_route_needs_public_base(
    client, compiled_workspace, monkeypatch
):
    """应用内路由引文：未配置公开基底 → 单元口径诚实为 None。"""
    from lumirss.workspace_share import _citation_href

    assert _citation_href("/reader?entry=e1", "") is None
    assert (
        _citation_href("/reader?entry=e1", "https://rss.example.com")
        == "https://rss.example.com/reader?entry=e1"
    )
    assert _citation_href("https://a.example/x", "") == "https://a.example/x"
    assert _citation_href("javascript:alert(1)", "https://rss.example.com") is None


def test_share_package_include_notes_is_fixed_false(client, compiled_workspace):
    workspace_id, _refs = compiled_workspace
    response = _export(client, workspace_id, {"includeNotes": True})
    assert response.status_code == 422


def test_share_package_unknown_workspace_404(client):
    response = client.post("/api/v1/workspaces/ws-nope/share-package", json={})
    assert response.status_code == 404
