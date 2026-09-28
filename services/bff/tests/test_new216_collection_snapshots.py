"""NEW-216 集合快照差异 —— 命名快照、两次快照 diff、按选择恢复成员。

验收：capture 存真实成员；diff 给出新增/移除（真实集合运算）；restore
按勾选恢复缺失成员（幂等跳过已存在；非法引用计数；不属于该快照的
引用拒绝）；快照上限与名字校验；A/B 隔离。
"""

import asyncio

from new21x_isolation import seed_library_item

run = asyncio.run

UUID_1 = "11111111-1111-4111-8111-111111111111"
UUID_2 = "22222222-2222-4222-8222-222222222222"
UUID_3 = "33333333-3333-4333-8333-333333333333"


def _mk_ws(client, name: str) -> str:
    created = client.post("/api/v1/workspaces", json={"name": name})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _add(client, ws: str, ref: str) -> None:
    added = client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": ref})
    assert added.status_code == 201, added.text


def test_new216_capture_diff_and_selective_restore(client):
    for uuid in (UUID_1, UUID_2, UUID_3):
        seed_library_item(client, uuid)
    ws = _mk_ws(client, "调研集合")
    _add(client, ws, f"library:{UUID_1}")
    _add(client, ws, f"library:{UUID_2}")

    snap_a = client.post(f"/api/v1/workspaces/{ws}/member-snapshots", json={"name": "初始"})
    assert snap_a.status_code == 201, snap_a.text
    snap_a = snap_a.json()
    assert snap_a["refCount"] == 2
    assert snap_a["truncated"] is False

    # 成员变化：移除 1 → 加入 1
    removed = client.get(f"/api/v1/workspaces/{ws}/items").json()["items"][0]
    assert client.delete(
        f"/api/v1/workspaces/{ws}/items/{removed['itemRef']}"
    ).status_code == 204
    _add(client, ws, f"library:{UUID_3}")

    snap_b = client.post(
        f"/api/v1/workspaces/{ws}/member-snapshots", json={"name": "第二轮"}
    ).json()

    listing = client.get(f"/api/v1/workspaces/{ws}/member-snapshots").json()["items"]
    assert {s["name"] for s in listing} == {"初始", "第二轮"}

    # diff：added = 仅 B（UUID_3）/ removed = 仅 A（被删的那条）
    diff = client.post(
        f"/api/v1/workspaces/{ws}/member-snapshots/diff",
        json={"a": snap_a["id"], "b": snap_b["id"]},
    )
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["added"] == [f"library:{UUID_3}"]
    assert body["removed"] == [removed["itemRef"]]
    assert body["addedTotal"] == 1 and body["removedTotal"] == 1

    # 按选择恢复被移除的成员
    restore = client.post(
        f"/api/v1/workspaces/{ws}/member-snapshots/restore",
        json={"snapshotId": snap_a["id"], "refs": [removed["itemRef"]]},
    )
    assert restore.status_code == 200, restore.text
    assert restore.json()["restored"] == [removed["itemRef"]]
    members = {
        i["itemRef"] for i in client.get(f"/api/v1/workspaces/{ws}/items").json()["items"]
    }
    assert members == {f"library:{UUID_1}", f"library:{UUID_2}", f"library:{UUID_3}"}

    # 幂等：再恢复同一引用 → skippedExisting
    again = client.post(
        f"/api/v1/workspaces/{ws}/member-snapshots/restore",
        json={"snapshotId": snap_a["id"], "refs": [removed["itemRef"]]},
    ).json()
    assert again["restored"] == [] and again["skippedExisting"] == 1

    # 校验：不属于该快照的引用拒绝；非法形状计数；坏快照 id 404
    refused = client.post(
        f"/api/v1/workspaces/{ws}/member-snapshots/restore",
        json={"snapshotId": snap_a["id"], "refs": [f"library:{UUID_3}"]},
    )
    assert refused.status_code == 422
    bad404 = client.post(
        f"/api/v1/workspaces/{ws}/member-snapshots/restore",
        json={"snapshotId": "no-such", "refs": [removed["itemRef"]]},
    )
    assert bad404.status_code == 404
    invalid_shape = client.post(
        f"/api/v1/workspaces/{ws}/member-snapshots/restore",
        json={"snapshotId": snap_b["id"], "refs": ["not-a-ref"]},
    )
    assert invalid_shape.status_code == 422  # 全部非法 → 空清单被拒

    # 名字校验 + 删除
    empty_name = client.post(f"/api/v1/workspaces/{ws}/member-snapshots", json={"name": " "})
    assert empty_name.status_code == 422
    assert (
        client.delete(
            f"/api/v1/workspaces/{ws}/member-snapshots/{snap_b['id']}"
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/workspaces/{ws}/member-snapshots/{snap_b['id']}"
        ).status_code
        == 404
    )


def test_new216_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：A 的集合快照对 B 完全不可见，恢复操作互不可达。"""
    from new21x_isolation import build_two_user_client, isolated_auth_env, make_bookmark

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        ref = make_bookmark(client, member, "乙的集合成员")
        ws_created = client.post(
            "/api/v1/workspaces", json={"name": "乙的集合"}, headers=member
        )
        assert ws_created.status_code == 201
        ws = ws_created.json()["id"]
        assert (
            client.post(
                f"/api/v1/workspaces/{ws}/items", json={"itemRef": ref}, headers=member
            ).status_code
            == 201
        )
        snap = client.post(
            f"/api/v1/workspaces/{ws}/member-snapshots",
            json={"name": "乙的快照"},
            headers=member,
        )
        assert snap.status_code == 201, snap.text
        snapshot_id = snap.json()["id"]

        # A 看不到 B 的快照列表，恢复也 404
        assert (
            client.get(
                f"/api/v1/workspaces/{ws}/member-snapshots", headers=owner
            ).json()["items"]
            == []
        )
        assert (
            client.post(
                f"/api/v1/workspaces/{ws}/member-snapshots/restore",
                json={"snapshotId": snapshot_id, "refs": [ref]},
                headers=owner,
            ).status_code
            == 404
        )
        # B 自己可 diff/恢复
        assert (
            client.post(
                f"/api/v1/workspaces/{ws}/member-snapshots/restore",
                json={"snapshotId": snapshot_id, "refs": [ref]},
                headers=member,
            ).json()["skippedExisting"]
            == 1
        )
