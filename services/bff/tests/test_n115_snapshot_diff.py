"""N115 快照差异视图测试 —— 两快照 diff（只读）。

- fixture 快照对：capture → 变更（增/删/重排/改组）→ capture；
- diff 报告 added/removed/moved/groupChanges 全部正确；
- 纯只读：diff 不改成员、不 bump revision；未知工作区/快照 → 404。
"""

import pytest


@pytest.fixture()
def workspace_with_items(client):
    created = client.post("/api/v1/workspaces", json={"name": "N115 快照"})
    assert created.status_code == 201
    workspace_id = created.json()["id"]
    refs = []
    for index in range(3):
        ref = client.post(
            "/api/v1/library/bookmarks",
            json={
                "url": f"https://example.com/n115-{index}",
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


def _revision(client, workspace_id: str) -> int:
    return int(client.get(f"/api/v1/workspaces/{workspace_id}").json()["revision"])


def test_diff_reports_added_removed_moved_groups(client, workspace_with_items):
    workspace_id, refs = workspace_with_items
    # 快照 A：顺序 [r0, r1, r2]（position 1..3），r0 在「甲组」。
    client.patch(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}/group",
        json={"groupName": "甲组"},
    )
    snap_a = _capture(client, workspace_id, "A")

    # 变更：移除 r2（removed）、新增第四条（added）、r0 移回未分组
    # （groupChanges）、重排为 [r1, r0, new]（r0 与 r1 都 moved）。
    client.delete(f"/api/v1/workspaces/{workspace_id}/items/{refs[2]}")
    new_ref = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/n115-new", "title": "新条目"},
    ).json()["ref"]
    client.post(f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": new_ref})
    client.patch(
        f"/api/v1/workspaces/{workspace_id}/items/{refs[0]}/group",
        json={"groupName": None},
    )
    client.patch(
        f"/api/v1/workspaces/{workspace_id}/items",
        json={"itemRefs": [refs[1], refs[0], new_ref]},
    )
    snap_b = _capture(client, workspace_id, "B")

    before = _revision(client, workspace_id)
    response = client.get(
        f"/api/v1/workspaces/{workspace_id}/snapshots/{snap_a['id']}/diff/{snap_b['id']}"
    )
    assert response.status_code == 200
    diff = response.json()
    assert diff["snapshotA"] == snap_a["id"]
    assert diff["snapshotB"] == snap_b["id"]
    assert diff["added"] == [new_ref]
    assert diff["removed"] == [refs[2]]
    # B 内 position 序：r1(pos1) 在前，r0(pos2) 在后。
    assert diff["moved"] == [
        {"ref": refs[1], "fromPos": 2, "toPos": 1},
        {"ref": refs[0], "fromPos": 1, "toPos": 2},
    ]
    assert diff["groupChanges"] == [
        {"ref": refs[0], "from": "甲组", "to": None}
    ]

    # 纯只读：diff 不 bump revision、不动成员。
    assert _revision(client, workspace_id) == before
    members = client.get(
        f"/api/v1/workspaces/{workspace_id}/items", params={"limit": 500}
    ).json()["items"]
    assert len(members) == 3


def test_diff_identical_snapshots_are_empty(client, workspace_with_items):
    workspace_id, _refs = workspace_with_items
    snap_a = _capture(client, workspace_id, "一")
    snap_b = _capture(client, workspace_id, "二")
    diff = client.get(
        f"/api/v1/workspaces/{workspace_id}/snapshots/{snap_a['id']}/diff/{snap_b['id']}"
    ).json()
    assert diff["added"] == []
    assert diff["removed"] == []
    assert diff["moved"] == []
    assert diff["groupChanges"] == []


def test_diff_404_unknown_workspace_or_snapshot(client, workspace_with_items):
    workspace_id, _refs = workspace_with_items
    snap = _capture(client, workspace_id, "唯一")
    assert (
        client.get(
            f"/api/v1/workspaces/ws-nope/snapshots/{snap['id']}/diff/{snap['id']}"
        ).status_code
        == 404
    )
    missing = client.get(
        f"/api/v1/workspaces/{workspace_id}/snapshots/snap-none/diff/{snap['id']}"
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "workspace_snapshot_not_found"
