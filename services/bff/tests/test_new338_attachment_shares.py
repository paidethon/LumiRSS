"""NEW-338 共享附件访问清单 —— 元数据台账 / 逐项撤销 / 不触碰所有者私人文件。"""

from new231_helpers import ab_session
from new331_helpers import space_with_members


def test_attachment_share_ledger_and_revoke(monkeypatch, tmp_path):
    """A 共享自己附件元数据 → B 可见清单（透明）；管理者逐项撤销（台账
    保留）；非管理者非所有者不能撤销；响应只含元数据，绝无附件内容。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(session, "n338a", "n338b", name="附件空间")
        sid = space["id"]
        member_a = session.login("n338a")
        member_b = session.login("n338b")

        shared = session.client.post(
            f"/api/v1/spaces/{sid}/attachment-shares",
            json={
                "attachmentRef": "note-attachment:abc123",
                "name": "会议笔记.pdf",
                "mimeType": "application/pdf",
                "sizeBytes": 4096,
            },
            headers=member_a,
        )
        assert shared.status_code == 201, shared.text
        share = shared.json()
        assert share["ownerUsername"] == "n338a"
        # 台账只含元数据键，绝无内容字段
        assert "content" not in share
        assert "data" not in share

        # 清单对成员可见（共享面透明）；默认不含已撤销
        listing = session.client.get(
            f"/api/v1/spaces/{sid}/attachment-shares", headers=member_b
        )
        assert [item["id"] for item in listing.json()["items"]] == [share["id"]]

        # 非管理者非所有者不能撤销
        forbidden = session.client.delete(
            f"/api/v1/spaces/{sid}/attachment-shares/{share['id']}", headers=member_b
        )
        assert forbidden.status_code == 422

        # 管理者撤销 → revokedAt 落账（台账保留，includeRevoked 可见）
        revoked = session.client.delete(
            f"/api/v1/spaces/{sid}/attachment-shares/{share['id']}",
            headers=session.owner,
        )
        assert revoked.status_code == 200
        assert revoked.json()["revokedAt"] is not None
        assert revoked.json()["revokedByUsername"] == "owner"
        active = session.client.get(
            f"/api/v1/spaces/{sid}/attachment-shares", headers=member_b
        )
        assert active.json()["items"] == []
        with_revoked = session.client.get(
            f"/api/v1/spaces/{sid}/attachment-shares",
            params={"includeRevoked": "true"},
            headers=member_b,
        )
        assert [item["id"] for item in with_revoked.json()["items"]] == [share["id"]]

        # 所有者也能撤销自己的共享（幂等）
        second = session.client.post(
            f"/api/v1/spaces/{sid}/attachment-shares",
            json={"attachmentRef": "note-attachment:def456", "name": "摘录.md"},
            headers=member_a,
        )
        assert second.status_code == 201
        self_revoked = session.client.delete(
            f"/api/v1/spaces/{sid}/attachment-shares/{second.json()['id']}",
            headers=member_a,
        )
        assert self_revoked.status_code == 200
        assert self_revoked.json()["revokedByUsername"] == "n338a"
        again = session.client.delete(
            f"/api/v1/spaces/{sid}/attachment-shares/{second.json()['id']}",
            headers=member_a,
        )
        assert again.status_code == 200  # 幂等

        # 负载校验：负大小 / 空名 → 422；非成员 → 404
        bad_size = session.client.post(
            f"/api/v1/spaces/{sid}/attachment-shares",
            json={"attachmentRef": "x", "name": "y", "sizeBytes": -1},
            headers=member_a,
        )
        assert bad_size.status_code == 422
        outsider = session.activate_member("n338z")
        assert (
            session.client.get(
                f"/api/v1/spaces/{sid}/attachment-shares", headers=outsider
            ).status_code
            == 404
        )
