"""P15 工作区续读指针 + 跨设备并发（revision）测试。

- 续读指针 CRUD（GET null → PUT → GET → 覆盖）+ 校验（404 未知工作区 /
  404 条目不在工作区 / 400 非法 ref）；
- 指向条目被移除 → 指针清除（绝不悬空）；工作区删除 → 指针随 FK 级联消失；
- revision 矩阵：add（幂等重放不 bump）/ remove / reorder / 看板状态
  （同状态重放不 bump）；list/detail 均可见；
- 乐观并发：stale expectedRevision 重排序 → 409（体带 currentRevision），
  重取后用新 revision 重试成功；不带该参数的旧调用方行为不变；
- 「两台设备」并发添加（顺序化调用 + 捕获 revision）：两个添加都生效，
  revision 如实 +2 —— 绝不静默丢弃。
"""

import pytest


@pytest.fixture()
def workspace_with_items(client):
    """一个非保留工作区 + 两个 library 条目成员；返回 (id, refs)。"""
    created = client.post(
        "/api/v1/workspaces", json={"name": "P15 续读"}
    )
    assert created.status_code == 201
    workspace_id = created.json()["id"]
    refs = []
    for index in range(2):
        ref = client.post(
            "/api/v1/library/bookmarks",
            json={
                "url": f"https://example.com/p15-{index}",
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
    detail = client.get(f"/api/v1/workspaces/{workspace_id}")
    assert detail.status_code == 200
    return int(detail.json()["revision"])


# ---- 续读指针 CRUD ----------------------------------------------------------


def test_resume_pointer_crud(client, workspace_with_items):
    workspace_id, refs = workspace_with_items

    # 初始无指针（GET 永远 200，pointer=null 是正常态）。
    empty = client.get(f"/api/v1/workspaces/{workspace_id}/resume")
    assert empty.status_code == 200
    assert empty.json()["pointer"] is None

    # PUT 保存指针，返回保存时的位置快照。
    put = client.put(
        f"/api/v1/workspaces/{workspace_id}/resume", json={"itemRef": refs[1]}
    )
    assert put.status_code == 200
    pointer = put.json()["pointer"]
    assert pointer["itemRef"] == refs[1]
    assert pointer["positionAtSave"] == 2
    assert pointer["updatedAt"]

    fetched = client.get(f"/api/v1/workspaces/{workspace_id}/resume")
    assert fetched.status_code == 200
    assert fetched.json()["pointer"]["itemRef"] == refs[1]

    # 覆盖：指向另一个条目。
    overwrite = client.put(
        f"/api/v1/workspaces/{workspace_id}/resume", json={"itemRef": refs[0]}
    )
    assert overwrite.status_code == 200
    assert overwrite.json()["pointer"]["itemRef"] == refs[0]
    assert overwrite.json()["pointer"]["positionAtSave"] == 1

    # 保存指针不改 revision（阅读光标 ≠ 共享条目状态）。
    assert _detail_revision(client, workspace_id) == 3  # 建区=1 + 两次 add


def test_resume_validation(client, workspace_with_items):
    workspace_id, refs = workspace_with_items

    # 未知工作区 → 404。
    missing_ws = client.put(
        "/api/v1/workspaces/ws-nope/resume", json={"itemRef": refs[0]}
    )
    assert missing_ws.status_code == 404

    # 条目不是该工作区成员 → 404（即使 ref 本身可解析）。
    outsider = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/outsider", "title": "外人"},
    ).json()["ref"]
    not_member = client.put(
        f"/api/v1/workspaces/{workspace_id}/resume", json={"itemRef": outsider}
    )
    assert not_member.status_code == 404

    # 非法 ref → 400（InvalidItemRef 稳定映射）。
    bad_ref = client.put(
        f"/api/v1/workspaces/{workspace_id}/resume", json={"itemRef": "library:nope"}
    )
    assert bad_ref.status_code == 400

    # 未知工作区的 GET：pointer=null（不泄漏存在性，也不报错）。
    missing_get = client.get("/api/v1/workspaces/ws-nope/resume")
    assert missing_get.status_code == 200
    assert missing_get.json()["pointer"] is None


def test_resume_cleared_when_pointed_item_removed(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    assert (
        client.put(
            f"/api/v1/workspaces/{workspace_id}/resume",
            json={"itemRef": refs[0]},
        ).status_code
        == 200
    )

    # 移除另一个条目：指针不受影响。
    other = client.delete(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[1]}"
    )
    assert other.status_code == 204
    kept = client.get(f"/api/v1/workspaces/{workspace_id}/resume")
    assert kept.json()["pointer"]["itemRef"] == refs[0]

    # 移除被指向的条目：指针清除，绝不悬空。
    assert (
        client.delete(
            f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}"
        ).status_code
        == 204
    )
    cleared = client.get(f"/api/v1/workspaces/{workspace_id}/resume")
    assert cleared.status_code == 200
    assert cleared.json()["pointer"] is None


def test_resume_cascade_with_workspace_delete(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    assert (
        client.put(
            f"/api/v1/workspaces/{workspace_id}/resume",
            json={"itemRef": refs[0]},
        ).status_code
        == 200
    )
    assert client.delete(f"/api/v1/workspaces/{workspace_id}").status_code == 204
    after = client.get(f"/api/v1/workspaces/{workspace_id}/resume")
    assert after.status_code == 200
    assert after.json()["pointer"] is None


# ---- revision 矩阵 ----------------------------------------------------------


def test_revision_bump_matrix(client, workspace_with_items):
    workspace_id, refs = workspace_with_items

    # 列表与详情都携带 revision。
    listing = client.get("/api/v1/workspaces").json()["items"]
    assert int(next(w for w in listing if w["id"] == workspace_id)["revision"]) >= 1
    base = _detail_revision(client, workspace_id)  # 建区=1 + 两次 add = 3

    # 幂等重放 add：不 bump。
    replay = client.post(
        f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": refs[0]}
    )
    assert replay.status_code == 201
    assert _detail_revision(client, workspace_id) == base

    # 看板状态：新状态 bump。
    board = client.put(
        f"/api/v1/workspaces/{workspace_id}/board",
        json={"itemRef": refs[0], "status": "reading"},
    )
    assert board.status_code == 200
    assert _detail_revision(client, workspace_id) == base + 1

    # 同状态重放：幂等，不 bump。
    replay_board = client.put(
        f"/api/v1/workspaces/{workspace_id}/board",
        json={"itemRef": refs[0], "status": "reading"},
    )
    assert replay_board.status_code == 200
    assert _detail_revision(client, workspace_id) == base + 1

    # 状态变化：bump。
    changed = client.put(
        f"/api/v1/workspaces/{workspace_id}/board",
        json={"itemRef": refs[0], "status": "done"},
    )
    assert changed.status_code == 200
    assert _detail_revision(client, workspace_id) == base + 2

    # remove：bump。
    assert (
        client.delete(
            f"/api/v1/workspaces/{workspace_id}/items/{refs[1]}"
        ).status_code
        == 204
    )
    assert _detail_revision(client, workspace_id) == base + 3


# ---- 乐观并发（重排序） ------------------------------------------------------


def test_stale_revision_reorder_409_then_retry(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    stale_revision = _detail_revision(client, workspace_id)

    # 设备 A 携带当前 revision 重排 → 成功，revision 前进。
    first = client.patch(
        f"/api/v1/workspaces/{workspace_id}/items",
        json={
            "itemRefs": [refs[1], refs[0]],
            "expectedRevision": stale_revision,
        },
    )
    assert first.status_code == 200
    fresh_revision = stale_revision + 1
    assert _detail_revision(client, workspace_id) == fresh_revision

    # 设备 B 仍持 stale revision → 409，响应体带当前 revision。
    conflict = client.patch(
        f"/api/v1/workspaces/{workspace_id}/items",
        json={
            "itemRefs": [refs[0], refs[1]],
            "expectedRevision": stale_revision,
        },
    )
    assert conflict.status_code == 409
    body = conflict.json()
    assert body["error"]["type"] == "workspace_revision_conflict"
    assert int(body["error"]["currentRevision"]) == fresh_revision

    # B 重取后用新 revision 重试 → 成功（不静默覆盖 A 的排序意图）。
    retry = client.patch(
        f"/api/v1/workspaces/{workspace_id}/items",
        json={
            "itemRefs": [refs[0], refs[1]],
            "expectedRevision": fresh_revision,
        },
    )
    assert retry.status_code == 200
    positions = {i["itemRef"]: i["position"] for i in retry.json()["items"]}
    assert positions[refs[0]] < positions[refs[1]]


def test_reorder_without_expected_revision_backward_compatible(
    client, workspace_with_items
):
    """旧调用方不带 expectedRevision：行为不变（不校验，直接生效）。"""
    workspace_id, refs = workspace_with_items
    response = client.patch(
        f"/api/v1/workspaces/{workspace_id}/items",
        json={"itemRefs": [refs[1], refs[0]]},
    )
    assert response.status_code == 200
    positions = {i["itemRef"]: i["position"] for i in response.json()["items"]}
    assert positions[refs[1]] < positions[refs[0]]


def test_concurrent_add_two_devices_never_silently_drops(
    client, workspace_with_items
):
    """两台设备（顺序化模拟，各自捕获 revision）同时添加不同条目：
    两个添加都生效，revision 如实 +2 —— 绝不静默丢弃任何一端。"""
    workspace_id, refs = workspace_with_items
    captured = _detail_revision(client, workspace_id)

    ref_a = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/dev-a", "title": "设备A"},
    ).json()["ref"]
    ref_b = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/dev-b", "title": "设备B"},
    ).json()["ref"]

    assert (
        client.post(
            f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": ref_a}
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": ref_b}
        ).status_code
        == 201
    )

    members = client.get(
        f"/api/v1/workspaces/{workspace_id}/items", params={"limit": 500}
    ).json()["items"]
    member_refs = {i["itemRef"] for i in members}
    assert {refs[0], refs[1], ref_a, ref_b} <= member_refs
    assert _detail_revision(client, workspace_id) == captured + 2
