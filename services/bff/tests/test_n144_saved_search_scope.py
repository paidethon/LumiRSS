"""N144 按检索范围收藏 — 保存视图的检索范围（工作区 + 内容类型）。

- 保存时携带 workspaceId/contentTypes → 原样回读（reopen 恢复范围）；
- 工作区被删除后 → scopeBroken=true 诚实标注（视图本身保留）；
- 解除关联只清 workspace_id，内容类型范围保留；
- 指向不存在工作区的保存 → 400；非法内容类型 → 400。
"""

import asyncio

import pytest


@pytest.fixture()
def scope_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    from fastapi.testclient import TestClient

    from lumirss.main import app

    with TestClient(app) as test_client:
        yield test_client


def _create_workspace(client, name):
    response = client.post("/api/v1/workspaces", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def _create_view(client, **overrides):
    body = {"name": "我的检索", "query": "rust"}
    body.update(overrides)
    return client.post("/api/v1/search/views", json=body)


def _delete_workspace(app, workspace_id):
    async def run():
        from lumirss.user_scope import user_context

        db = app.state.db
        with user_context(app.state.owner_id):
            await db.migrate()
            await db.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))

    asyncio.run(run())


def test_save_with_scope_and_reopen_restores_it(scope_client):
    workspace_id = _create_workspace(scope_client, "深度阅读")
    created = _create_view(
        scope_client,
        workspaceId=workspace_id,
        contentTypes=["rss", "bookmark"],
    )
    assert created.status_code == 201
    body = created.json()
    assert body["workspaceId"] == workspace_id
    assert body["contentTypes"] == ["rss", "bookmark"]
    assert body["scopeBroken"] is False

    # reopen 路径 = 列表回读，范围字段原样还原。
    listing = scope_client.get("/api/v1/search/views").json()["items"]
    saved = next(v for v in listing if v["id"] == body["id"])
    assert saved["workspaceId"] == workspace_id
    assert saved["contentTypes"] == ["rss", "bookmark"]
    assert saved["scopeBroken"] is False


def test_legacy_views_keep_scope_fields_null(scope_client):
    created = _create_view(scope_client)
    assert created.status_code == 201
    assert created.json()["workspaceId"] is None
    assert created.json()["contentTypes"] is None
    assert created.json()["scopeBroken"] is False


def test_broken_workspace_flagged_honestly(scope_client):
    from lumirss.main import app

    workspace_id = _create_workspace(scope_client, "会消失的工作区")
    view = _create_view(scope_client, workspaceId=workspace_id).json()

    _delete_workspace(app, workspace_id)
    listing = scope_client.get("/api/v1/search/views").json()["items"]
    saved = next(v for v in listing if v["id"] == view["id"])
    assert saved["scopeBroken"] is True  # 诚实标注，不静默清理
    assert saved["workspaceId"] == workspace_id
    assert saved["contentTypes"] is None or isinstance(saved["contentTypes"], list)


def test_unlink_clears_workspace_keeps_content_types(scope_client):
    workspace_id = _create_workspace(scope_client, "范围工作区")
    view = _create_view(
        scope_client,
        workspaceId=workspace_id,
        contentTypes=["clip"],
    ).json()

    unlinked = scope_client.post(f"/api/v1/search/views/{view['id']}/scope/unlink")
    assert unlinked.status_code == 200
    body = unlinked.json()["view"]
    assert body["workspaceId"] is None
    assert body["contentTypes"] == ["clip"]
    assert body["scopeBroken"] is False

    # 幂等：无工作区关联时再次 unlink 仍成功。
    again = scope_client.post(f"/api/v1/search/views/{view['id']}/scope/unlink")
    assert again.status_code == 200


def test_scope_validation(scope_client):
    # 指向不存在的工作区 → 400（与「保存后被删」的 scopeBroken 两回事）。
    missing = _create_view(scope_client, workspaceId="no-such-workspace")
    assert missing.status_code == 400
    assert missing.json()["error"]["type"] == "workspace_not_found"
    # 非法内容类型 → 400（store 白名单）。
    bad_types = _create_view(scope_client, contentTypes=["rss", "pdf"])
    assert bad_types.status_code == 400
    # 内容类型必须是数组 → 422（契约层类型校验）。
    bad_shape = _create_view(scope_client, contentTypes="rss")
    assert bad_shape.status_code == 422

    unlinked_missing = scope_client.post(
        "/api/v1/search/views/nope/scope/unlink"
    )
    assert unlinked_missing.status_code == 404
