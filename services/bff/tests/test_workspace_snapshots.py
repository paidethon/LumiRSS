"""N105 工作区会话快照测试。

- 捕获（201，元数据 + itemCount）→ 列表（新→旧）→ 删除（204；再删
  404 workspace_snapshot_not_found）；
- capture → mutate → restore(reorder)：顺序/分组/固定恢复；快照外
  成员保留（kept）；已消失 ref 诚实上报 missing（绝不复活）；
- restore(replace)：快照外成员被移除（removed 列出）；固定条目受
  N102 保护——不带 force → 409 workspace_item_pinned 且绝不半删，
  force=true 才放行；missing 不复活；
- revision：restore 真实写库时 bump（P15）；快照捕获/删除不 bump
  （快照不是共享条目状态）；
- 校验：未知工作区 404 / 快照不存在 404 / 非法 mode 400 / 空名 400 /
  名字上限内。
"""

import pytest


@pytest.fixture()
def workspace_with_items(client):
    """非保留工作区 + 3 个 library 成员；返回 (id, refs)。"""
    created = client.post("/api/v1/workspaces", json={"name": "N105 快照"})
    assert created.status_code == 201
    workspace_id = created.json()["id"]
    refs = []
    for index in range(3):
        ref = client.post(
            "/api/v1/library/bookmarks",
            json={
                "url": f"https://example.com/n105-{index}",
                "title": f"条目{index}",
            },
        ).json()["ref"]
        added = client.post(
            f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": ref}
        )
        assert added.status_code == 201
        refs.append(ref)
    return workspace_id, refs


def _capture(client, workspace_id: str, name: str) -> dict:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/snapshots", json={"name": name}
    )
    assert response.status_code == 201
    return response.json()


def _restore(client, workspace_id: str, snapshot_id: str, mode: str, **extra) -> dict:
    return client.post(
        f"/api/v1/workspaces/{workspace_id}/snapshots/{snapshot_id}/restore",
        json={"mode": mode, **extra},
    )


def _members(client, workspace_id: str) -> list[dict]:
    response = client.get(
        f"/api/v1/workspaces/{workspace_id}/items", params={"limit": 500}
    )
    return response.json()["items"]


def _detail_revision(client, workspace_id: str) -> int:
    return int(client.get(f"/api/v1/workspaces/{workspace_id}").json()["revision"])


def test_capture_list_delete(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    base = _detail_revision(client, workspace_id)

    first = _capture(client, workspace_id, "周一状态")
    assert first["name"] == "周一状态"
    assert first["itemCount"] == 3
    assert first["id"].startswith("snap-")
    second = _capture(client, workspace_id, "周二状态")

    listed = client.get(f"/api/v1/workspaces/{workspace_id}/snapshots").json()["items"]
    assert [s["id"] for s in listed] == [second["id"], first["id"]]  # 新→旧

    # 捕获/删除不 bump revision（快照不是共享条目状态）。
    assert _detail_revision(client, workspace_id) == base

    deleted = client.delete(f"/api/v1/workspaces/{workspace_id}/snapshots/{first['id']}")
    assert deleted.status_code == 204
    gone = client.delete(f"/api/v1/workspaces/{workspace_id}/snapshots/{first['id']}")
    assert gone.status_code == 404
    assert gone.json()["error"]["type"] == "workspace_snapshot_not_found"

    # 空名 → 400；未知工作区 → 404。
    assert (
        client.post(
            f"/api/v1/workspaces/{workspace_id}/snapshots", json={"name": "  "}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/workspaces/ws-nope/snapshots", json={"name": "孤儿"}
        ).status_code
        == 404
    )


def test_capture_mutate_restore_reorder(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    # 捕获时：refs[0] 在「甲组」且固定，顺序为默认添加序。
    client.patch(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}/group",
        json={"groupName": "甲组"},
    )
    client.put(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}/pin",
        json={"pinned": True},
    )
    client.put(
        f"/api/v1/workspaces/{workspace_id}/groups", json={"order": ["甲组"]}
    )
    snapshot = _capture(client, workspace_id, "重组前")

    # 破坏：反序 + 改组 + 取消固定 + 新增快照外成员。
    client.patch(
        f"/api/v1/workspaces/{workspace_id}/items",
        json={"itemRefs": list(reversed(refs))},
    )
    client.patch(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}/group",
        json={"groupName": "乙组"},
    )
    client.put(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}/pin",
        json={"pinned": False},
    )
    outsider = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/n105-outsider", "title": "后来者"},
    ).json()["ref"]
    client.post(f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": outsider})

    result = _restore(client, workspace_id, snapshot["id"], "reorder")
    assert result.status_code == 200
    body = result.json()
    assert body["restored"] == 3
    assert body["missing"] == []
    assert body["kept"] == 1  # 快照外的后来者原样保留
    assert body["removed"] == []

    members = {m["itemRef"]: m for m in _members(client, workspace_id)}
    # 顺序恢复（快照序 = refs 原添加序）。
    assert [members[refs[i]]["position"] for i in range(3)] == [1, 2, 3]
    assert members[outsider]["position"] == 4
    # 分组 + 固定恢复。
    assert members[refs[0]]["groupName"] == "甲组"
    assert members[refs[0]]["pinned"] is True
    view = client.get(f"/api/v1/workspaces/{workspace_id}/groups").json()
    assert view["groupOrder"] == ["甲组"]
    assert [i["itemRef"] for i in view["pinned"]] == [refs[0]]


def test_restore_reports_missing_refs_never_resurrects(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    snapshot = _capture(client, workspace_id, "含将逝条目")

    # 捕获后移除一个成员：restore 时它是 missing，绝不复活。
    client.delete(f"/api/v1/workspaces/{workspace_id}/items/{refs[2]}")
    before = {m["itemRef"] for m in _members(client, workspace_id)}

    body = _restore(client, workspace_id, snapshot["id"], "reorder").json()
    assert body["restored"] == 2
    assert body["missing"] == [refs[2]]
    after = {m["itemRef"] for m in _members(client, workspace_id)}
    assert after == before  # 没有复活


def test_restore_replace_removes_and_honors_pinned(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    snapshot = _capture(client, workspace_id, "三人态")

    # 固定一个快照外成员 + 新增快照外成员。
    outsider = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/n105-replace", "title": "替换外人"},
    ).json()["ref"]
    client.post(f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": outsider})
    client.put(
        f"/api/v1/workspaces/{workspace_id}/items/{outsider}/pin",
        json={"pinned": True},
    )

    # replace 不带 force：固定条目会被丢 → 拒绝（409），绝不半删。
    refused = _restore(client, workspace_id, snapshot["id"], "replace")
    assert refused.status_code == 409
    assert refused.json()["error"]["type"] == "workspace_item_pinned"
    assert len(_members(client, workspace_id)) == 4

    # force=true：放行——快照外成员被移除并列出，快照态恢复。
    body = _restore(
        client, workspace_id, snapshot["id"], "replace", force=True
    ).json()
    assert body["removed"] == [outsider]
    assert body["kept"] == 0
    assert body["restored"] == 3
    assert body["missing"] == []
    member_refs = {m["itemRef"] for m in _members(client, workspace_id)}
    assert member_refs == set(refs)

    # replace 模式下 missing 的 ref 同样不复活。
    snapshot2 = _capture(client, workspace_id, "三人态 2")
    client.delete(f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}")
    body2 = _restore(client, workspace_id, snapshot2["id"], "replace").json()
    assert body2["missing"] == [refs[0]]
    assert {m["itemRef"] for m in _members(client, workspace_id)} == set(refs[1:])


def test_restore_validation_and_revision(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    snapshot = _capture(client, workspace_id, "校验用")

    # 非法 mode → 400。
    assert (
        _restore(client, workspace_id, snapshot["id"], "merge").status_code == 400
    )
    # 快照不存在 → 404（稳定错误族）。
    missing = _restore(client, workspace_id, "snap-does-not-exist", "reorder")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "workspace_snapshot_not_found"
    # 未知工作区 → 404。
    other = client.post("/api/v1/workspaces", json={"name": "别的区"}).json()["id"]
    assert (
        _restore(client, other, snapshot["id"], "reorder").status_code == 404
    )

    # restore 真实写库时 bump revision。
    client.patch(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}/group",
        json={"groupName": "甲组"},
    )
    base = _detail_revision(client, workspace_id)
    body = _restore(client, workspace_id, snapshot["id"], "reorder").json()
    assert body["revision"] == base + 1
    assert _detail_revision(client, workspace_id) == base + 1

    # 快照随工作区删除级联消失（工作区本身 404，快照行随之清空）。
    assert client.delete(f"/api/v1/workspaces/{workspace_id}").status_code == 204
    assert (
        client.get(f"/api/v1/workspaces/{workspace_id}/snapshots").status_code == 404
    )
