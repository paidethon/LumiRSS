"""N101 标签页分组 + N102 固定标签页测试。

- N101：add 带 groupName；PATCH group 移动（含 null 回未分组）；幂等
  重放不 bump revision；GET /groups 分组视图（未分组 = 隐式前置组，
  命名组按 group_order_json 排序，未列入顺序的组按名字典序追加；
  组内 position 序）；PUT /groups 只重排既有组（未知名字 400、重复
  400、顺序未变不 bump）；跨工作区行隔离（同名组互不串扰）；
- N102：PUT pin（set 语义，幂等重放不 bump）；固定区排所有组之前
  （position 序）；remove 固定条目不带 force → 409
  workspace_item_pinned，?force=1 才放行；固定状态在列表/分组视图
  中如实可见；被固定条目的续读指针随 force 删除清除。
"""

import pytest


@pytest.fixture()
def workspace_with_items(client):
    """非保留工作区 + 4 个 library 成员；返回 (id, refs)。"""
    created = client.post("/api/v1/workspaces", json={"name": "N101 分组"})
    assert created.status_code == 201
    workspace_id = created.json()["id"]
    refs = []
    for index in range(4):
        ref = client.post(
            "/api/v1/library/bookmarks",
            json={
                "url": f"https://example.com/n101-{index}",
                "title": f"条目{index}",
            },
        ).json()["ref"]
        added = client.post(
            f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": ref}
        )
        assert added.status_code == 201
        refs.append(ref)
    return workspace_id, refs


def _detail_revision(client, workspace_id: str) -> int:
    return int(client.get(f"/api/v1/workspaces/{workspace_id}").json()["revision"])


def _groups(client, workspace_id: str) -> dict:
    response = client.get(f"/api/v1/workspaces/{workspace_id}/groups")
    assert response.status_code == 200
    return response.json()


def _move(client, workspace_id: str, ref: str, group: str | None):
    return client.patch(
        f"/api/v1/workspaces/{workspace_id}/items/{ref}/group",
        json={"groupName": group},
    )


# ---- N101 分组 ---------------------------------------------------------------


def test_add_with_group_and_grouped_view(client, workspace_with_items):
    workspace_id, refs = workspace_with_items

    # 带 groupName 幂等添加一个新条目。
    ref_g = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/n101-g", "title": "分组条目"},
    ).json()["ref"]
    added = client.post(
        f"/api/v1/workspaces/{workspace_id}/items",
        json={"itemRef": ref_g, "groupName": "深度阅读"},
    )
    assert added.status_code == 201
    assert added.json()["groupName"] == "深度阅读"

    # 把两个既有条目移进同一组。
    assert _move(client, workspace_id, refs[0], "深度阅读").status_code == 200
    assert _move(client, workspace_id, refs[1], "待定").status_code == 200

    view = _groups(client, workspace_id)
    names = [g["name"] for g in view["groups"]]
    # 未分组（refs[2]/refs[3]）= 隐式前置组；命名组按名字典序（尚未设置顺序）。
    assert names[0] is None
    assert names[1:] == sorted(["深度阅读", "待定"])
    by_name = {g["name"]: [i["itemRef"] for i in g["items"]] for g in view["groups"]}
    assert by_name[None] == [refs[2], refs[3]]
    assert by_name["深度阅读"] == [refs[0], ref_g]
    assert by_name["待定"] == [refs[1]]
    # 平铺列表同样携带 groupName。
    flat = client.get(f"/api/v1/workspaces/{workspace_id}/items").json()["items"]
    groups_in_flat = {i["itemRef"]: i["groupName"] for i in flat}
    assert groups_in_flat[refs[0]] == "深度阅读"
    assert groups_in_flat[refs[3]] is None


def test_move_group_validation_and_idempotence(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    base = _detail_revision(client, workspace_id)

    # 移动到组：真实变化 bump。
    assert _move(client, workspace_id, refs[0], "A组").status_code == 200
    assert _detail_revision(client, workspace_id) == base + 1

    # 幂等重放（同组）：不 bump。
    assert _move(client, workspace_id, refs[0], "A组").status_code == 200
    assert _detail_revision(client, workspace_id) == base + 1

    # null = 移回未分组：真实变化 bump。
    back = _move(client, workspace_id, refs[0], None)
    assert back.status_code == 200
    assert back.json()["groupName"] is None
    assert _detail_revision(client, workspace_id) == base + 2

    # 非成员 → 404（含未知工作区）。
    assert _move(client, workspace_id, "library:00000000-0000-0000-0000-000000000000", "A组").status_code == 404
    assert _move(client, "ws-nope", refs[0], "A组").status_code == 404

    # 组名过长 → 400（稳定错误族 invalid_workspace）。
    long_name = "超" * 65
    bad = _move(client, workspace_id, refs[0], long_name)
    assert bad.status_code == 400
    assert bad.json()["error"]["type"] == "invalid_workspace"


def test_put_group_order_and_validation(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    assert _move(client, workspace_id, refs[0], "甲组").status_code == 200
    assert _move(client, workspace_id, refs[1], "乙组").status_code == 200
    base = _detail_revision(client, workspace_id)

    # 设置顺序：乙组在前。顺序真实变化 bump。
    ordered = client.put(
        f"/api/v1/workspaces/{workspace_id}/groups", json={"order": ["乙组", "甲组"]}
    )
    assert ordered.status_code == 200
    view = ordered.json()
    assert [g["name"] for g in view["groups"] if g["name"] is not None] == ["乙组", "甲组"]
    assert _detail_revision(client, workspace_id) == base + 1

    # 幂等重放：顺序未变不 bump。
    client.put(
        f"/api/v1/workspaces/{workspace_id}/groups", json={"order": ["乙组", "甲组"]}
    )
    assert _detail_revision(client, workspace_id) == base + 1

    # 未知组名 → 400（只重排既有组，不创建）。
    unknown = client.put(
        f"/api/v1/workspaces/{workspace_id}/groups", json={"order": ["乙组", "幻影组"]}
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["type"] == "invalid_workspace"

    # 重复名字 → 400。
    dup = client.put(
        f"/api/v1/workspaces/{workspace_id}/groups", json={"order": ["乙组", "乙组"]}
    )
    assert dup.status_code == 400

    # 未列入顺序的组按名字典序追加在后。
    assert _move(client, workspace_id, refs[2], "丙组").status_code == 200
    view = _groups(client, workspace_id)
    assert [g["name"] for g in view["groups"] if g["name"] is not None] == [
        "乙组",
        "甲组",
        "丙组",
    ]


def test_groups_are_isolated_per_workspace(client, workspace_with_items):
    """跨工作区串扰不可能：同名组在两个工作区各自独立。"""
    workspace_id, refs = workspace_with_items
    other = client.post("/api/v1/workspaces", json={"name": "另一工作区"}).json()["id"]
    other_ref = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/other-ws", "title": "别区条目"},
    ).json()["ref"]
    client.post(
        f"/api/v1/workspaces/{other}/items",
        json={"itemRef": other_ref, "groupName": "甲组"},
    )

    view_other = _groups(client, other)
    assert [g["name"] for g in view_other["groups"]] == ["甲组"]
    # 原工作区没有该组（组名只在本工作区行上）。
    view_self = _groups(client, workspace_id)
    assert "甲组" not in [g["name"] for g in view_self["groups"] if g["name"]]
    # PUT 顺序在另一工作区拒绝未知组名（组顺序同样是每工作区的）。
    assert (
        client.put(
            f"/api/v1/workspaces/{other}/groups", json={"order": ["不存在的组"]}
        ).status_code
        == 400
    )


# ---- N102 固定 ---------------------------------------------------------------


def test_pin_set_semantics_and_pinned_section_first(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    assert _move(client, workspace_id, refs[1], "甲组").status_code == 200
    base = _detail_revision(client, workspace_id)

    # 固定 refs[2]：set 语义，真实变化 bump。
    pinned = client.put(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[2]}/pin",
        json={"pinned": True},
    )
    assert pinned.status_code == 200
    assert pinned.json()["pinned"] is True
    assert _detail_revision(client, workspace_id) == base + 1

    # 幂等重放：不 bump。
    client.put(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[2]}/pin",
        json={"pinned": True},
    )
    assert _detail_revision(client, workspace_id) == base + 1

    # 再固定一个（position 更后者）：固定区按 position 序排所有组之前。
    client.put(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[3]}/pin",
        json={"pinned": True},
    )
    view = _groups(client, workspace_id)
    assert [i["itemRef"] for i in view["pinned"]] == [refs[2], refs[3]]
    for group in view["groups"]:
        assert all(item["itemRef"] not in (refs[2], refs[3]) for item in group["items"])

    # 取消固定（set False）：回到原组。
    unpinned = client.put(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[3]}/pin",
        json={"pinned": False},
    )
    assert unpinned.json()["pinned"] is False
    view = _groups(client, workspace_id)
    assert [i["itemRef"] for i in view["pinned"]] == [refs[2]]

    # 非成员 / 未知工作区 → 404。
    assert (
        client.put(
            f"/api/v1/workspaces/{workspace_id}/items/library:00000000-0000-0000-0000-000000000000/pin",
            json={"pinned": True},
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/v1/workspaces/ws-nope/items/{refs[0]}/pin",
            json={"pinned": True},
        ).status_code
        == 404
    )


def test_remove_pinned_requires_force(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    # 续读指针指向将被固定删除的条目。
    client.put(
        f"/api/v1/workspaces/{workspace_id}/resume", json={"itemRef": refs[0]}
    )
    client.put(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}/pin",
        json={"pinned": True},
    )
    base = _detail_revision(client, workspace_id)

    # 不带 force → 409 workspace_item_pinned，条目仍在。
    refused = client.delete(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}"
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["type"] == "workspace_item_pinned"
    flat = client.get(f"/api/v1/workspaces/{workspace_id}/items").json()["items"]
    assert any(i["itemRef"] == refs[0] for i in flat)
    assert _detail_revision(client, workspace_id) == base

    # force=1 → 放行：条目删除 + 续读指针清除（指针绝不悬空）+ bump。
    forced = client.delete(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}?force=1"
    )
    assert forced.status_code == 204
    assert _detail_revision(client, workspace_id) == base + 1
    pointer = client.get(f"/api/v1/workspaces/{workspace_id}/resume").json()["pointer"]
    assert pointer is None

    # 未固定条目照常删除（force 不是必需）。
    assert (
        client.delete(f"/api/v1/workspaces/{workspace_id}/items/{refs[1]}").status_code
        == 204
    )


def test_pin_persists_across_reorder(client, workspace_with_items):
    """固定状态在重排序后保留（固定是行的属性，position 独立）。"""
    workspace_id, refs = workspace_with_items
    client.put(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[1]}/pin",
        json={"pinned": True},
    )
    reorder = client.patch(
        f"/api/v1/workspaces/{workspace_id}/items",
        json={"itemRefs": list(reversed(refs))},
    )
    assert reorder.status_code == 200
    view = _groups(client, workspace_id)
    assert [i["itemRef"] for i in view["pinned"]] == [refs[1]]
