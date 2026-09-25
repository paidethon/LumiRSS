"""N108 跨工作区移动标签（工作区条目移动）测试。

- POST /workspaces/{id}/items/{ref}/move：成员关系移动，底层对象绝不
  复制（两个工作区解析同一个 ref）；
- 幂等：目标已有 → 默认 skip（duplicate=true）；onDuplicate=conflict →
  409 workspace_item_duplicate；
- keepInSource=true：双工作区同持（两行成员关系，同一 ref）；
- 源非成员 → 404；目标工作区不存在 → 404。
"""

import asyncio


def run(coroutine):
    return asyncio.run(coroutine)


async def _setup(client) -> tuple[str, str, str]:
    """两个工作区 + 一个共享底层对象的库条目。返回 (src, dst, ref)。"""
    from lumirss.library import LibraryStore

    db = client.app.state.db
    src = client.post("/api/v1/workspaces", json={"name": "源工作区"}).json()
    dst = client.post("/api/v1/workspaces", json={"name": "目标工作区"}).json()
    store = LibraryStore(db)
    view, _created = await store.create_url_bookmark(
        "https://example.com/move-me", "移动对象"
    )
    ref = view.ref
    response = client.post(
        f"/api/v1/workspaces/{src['id']}/items", json={"itemRef": ref}
    )
    assert response.status_code == 201, response.text
    return src["id"], dst["id"], ref


def test_move_semantics_and_no_object_duplication(client):
    src, dst, ref = _setup_sync(client)
    response = client.post(
        f"/api/v1/workspaces/{src}/items/{ref}/move",
        json={"targetWorkspaceId": dst},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["duplicate"] is False
    assert body["sourceRemoved"] is True
    assert body["targetPosition"] == 1

    # 源列表没有该条目，目标有——且 ref 原样（同一底层对象）。
    src_items = client.get(f"/api/v1/workspaces/{src}/items").json()["items"]
    dst_items = client.get(f"/api/v1/workspaces/{dst}/items").json()["items"]
    assert [i["itemRef"] for i in src_items] == []
    assert [i["itemRef"] for i in dst_items] == [ref]


def _setup_sync(client):
    import anyio

    return anyio.run(_setup, client)


def test_keep_in_source_both_members(client):
    src, dst, ref = _setup_sync(client)
    response = client.post(
        f"/api/v1/workspaces/{src}/items/{ref}/move",
        json={"targetWorkspaceId": dst, "keepInSource": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sourceRemoved"] is False
    src_items = client.get(f"/api/v1/workspaces/{src}/items").json()["items"]
    dst_items = client.get(f"/api/v1/workspaces/{dst}/items").json()["items"]
    assert [i["itemRef"] for i in src_items] == [ref]
    assert [i["itemRef"] for i in dst_items] == [ref]


def test_duplicate_flag_and_conflict_mode(client):
    src, dst, ref = _setup_sync(client)
    # 目标先持有同一条目。
    client.post(f"/api/v1/workspaces/{dst}/items", json={"itemRef": ref})

    # 默认 skip：幂等收敛，duplicate=true，源被移除。
    moved = client.post(
        f"/api/v1/workspaces/{src}/items/{ref}/move",
        json={"targetWorkspaceId": dst},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["duplicate"] is True
    dst_items = client.get(f"/api/v1/workspaces/{dst}/items").json()["items"]
    assert [i["itemRef"] for i in dst_items] == [ref]  # 绝不二份

    # 重建源成员关系后选 conflict → 409，两侧都不变。
    client.post(f"/api/v1/workspaces/{src}/items", json={"itemRef": ref})
    conflict = client.post(
        f"/api/v1/workspaces/{src}/items/{ref}/move",
        json={"targetWorkspaceId": dst, "onDuplicate": "conflict"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["type"] == "workspace_item_duplicate"


def test_move_404_paths(client):
    src, dst, ref = _setup_sync(client)
    missing = client.post(
        f"/api/v1/workspaces/{src}/items/library:00000000-0000-0000-0000-000000000000/move",
        json={"targetWorkspaceId": dst},
    )
    # 源非成员 → 400 invalid_workspace（与既有 remove 契约一致）
    assert missing.status_code == 400
    assert missing.json()["error"]["type"] == "invalid_workspace"

    no_target = client.post(
        f"/api/v1/workspaces/{src}/items/{ref}/move",
        json={"targetWorkspaceId": "ws-no-such"},
    )
    assert no_target.status_code == 404
