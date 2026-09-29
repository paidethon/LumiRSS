"""NEW-332 共享内容审批队列 —— pending 不公开给全体 / 退回原因可见 / 权限。"""

from new231_helpers import ab_session
from new331_helpers import space_with_members


def test_approval_queue_visibility_and_review(monkeypatch, tmp_path):
    """开审批：A 投稿 pending → B（非管理者）看不到；管理者退回（必须
    带原因）→ A 看到退回原因；再投稿批准 → 全员可见。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(
            session, "n332a", "n332b", name="审批空间", requireApproval=True
        )
        sid = space["id"]
        member_a = session.login("n332a")
        member_b = session.login("n332b")

        submitted = session.client.post(
            f"/api/v1/spaces/{sid}/contributions",
            json={"entryRef": "entry-12", "title": "待审文章", "excerpt": "摘录"},
            headers=member_a,
        )
        assert submitted.status_code == 201, submitted.text
        contribution = submitted.json()
        assert contribution["status"] == "pending"

        # 未审批内容不公开给全体：B 的默认视图与单条都不含 A 的 pending
        visible_b = session.client.get(
            f"/api/v1/spaces/{sid}/contributions", headers=member_b
        )
        assert visible_b.status_code == 200
        assert visible_b.json()["items"] == []
        assert (
            session.client.get(
                f"/api/v1/spaces/{sid}/contributions/{contribution['id']}",
                headers=member_b,
            ).status_code
            == 404
        )

        # 投稿者本人与管理者可见 pending
        mine = session.client.get(
            f"/api/v1/spaces/{sid}/contributions", params={"scope": "mine"}, headers=member_a
        )
        assert [item["status"] for item in mine.json()["items"]] == ["pending"]
        manager_view = session.client.get(
            f"/api/v1/spaces/{sid}/contributions", headers=session.owner
        )
        assert [item["id"] for item in manager_view.json()["items"]] == [contribution["id"]]

        # 管理者退回：无原因 → 422；带原因 → rejected + 原因可见
        reject_no_note = session.client.post(
            f"/api/v1/spaces/{sid}/contributions/{contribution['id']}/review",
            json={"approve": False},
            headers=session.owner,
        )
        assert reject_no_note.status_code == 422
        rejected = session.client.post(
            f"/api/v1/spaces/{sid}/contributions/{contribution['id']}/review",
            json={"approve": False, "reviewNote": "出处未核对，请补充原文链接。"},
            headers=session.owner,
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["reviewNote"] == "出处未核对，请补充原文链接。"

        # 贡献者看到自己的待审/退回原因（默认视图 + mine）
        a_view = session.client.get(
            f"/api/v1/spaces/{sid}/contributions", headers=member_a
        )
        assert a_view.json()["items"][0]["reviewNote"] == "出处未核对，请补充原文链接。"

        # 非管理者不能审批；重复审批 → 422
        forbidden = session.client.post(
            f"/api/v1/spaces/{sid}/contributions/{contribution['id']}/review",
            json={"approve": True},
            headers=member_b,
        )
        assert forbidden.status_code == 403
        twice = session.client.post(
            f"/api/v1/spaces/{sid}/contributions/{contribution['id']}/review",
            json={"approve": True, "reviewNote": "补审"},
            headers=session.owner,
        )
        assert twice.status_code == 422

        # 第二次投稿 → 管理者批准 → 全体成员可见
        second = session.client.post(
            f"/api/v1/spaces/{sid}/contributions",
            json={"entryRef": "entry-13", "title": "批准文章"},
            headers=member_a,
        )
        second_id = second.json()["id"]
        approved = session.client.post(
            f"/api/v1/spaces/{sid}/contributions/{second_id}/review",
            json={"approve": True},
            headers=session.owner,
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        visible_b = session.client.get(
            f"/api/v1/spaces/{sid}/contributions", headers=member_b
        )
        assert [item["id"] for item in visible_b.json()["items"]] == [second_id]


def test_no_approval_mode_and_settings_permission(monkeypatch, tmp_path):
    """未开审批：投稿直接 approved 全员可见；审批开关只有管理者能改。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(session, "n332c", name="开放空间")
        sid = space["id"]
        member = session.login("n332c")

        submitted = session.client.post(
            f"/api/v1/spaces/{sid}/contributions",
            json={"entryRef": "entry-20", "title": "直接共享"},
            headers=member,
        )
        assert submitted.status_code == 201
        assert submitted.json()["status"] == "approved"

        session.activate_member("n332d")
        session.client.post(
            f"/api/v1/spaces/{sid}/members", json={"username": "n332d"}, headers=session.owner
        )
        other = session.login("n332d")
        visible = session.client.get(f"/api/v1/spaces/{sid}/contributions", headers=other)
        assert [item["id"] for item in visible.json()["items"]] == [submitted.json()["id"]]

        # 成员改设置 → 403；管理者关闭审批 → 后续投稿仍直接 approved
        forbidden = session.client.put(
            f"/api/v1/spaces/{sid}/settings",
            json={"requireApproval": True},
            headers=member,
        )
        assert forbidden.status_code == 403
        toggled = session.client.put(
            f"/api/v1/spaces/{sid}/settings",
            json={"requireApproval": True},
            headers=session.owner,
        )
        assert toggled.status_code == 200
        assert toggled.json()["requireApproval"] is True
        gated = session.client.post(
            f"/api/v1/spaces/{sid}/contributions",
            json={"entryRef": "entry-21", "title": "开启后投稿"},
            headers=member,
        )
        assert gated.json()["status"] == "pending"
