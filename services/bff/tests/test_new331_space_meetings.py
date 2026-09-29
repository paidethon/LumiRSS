"""NEW-331 共读会议资料单（含空间基底）—— 显式共享 / A-B 隔离 / 权限。

隐私前提：空间内容只来自成员显式动作；非成员一律 404（不泄露存在性）；
结论只在会议结束后保存。
"""

from new231_helpers import ab_session
from new331_helpers import add_member, make_space, space_with_members


def test_space_base_isolation_and_permissions(monkeypatch, tmp_path):
    """基底：非成员 404 / 成员可见 / 越权 403 / 未知用户名 422 / 成员自退。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space = make_space(session, session.owner, "隔离空间", requireApproval=True)
        sid = space["id"]

        # 未被添加的成员：404（不泄露存在性）
        outsider = session.activate_member("n331c")
        assert (
            session.client.get(f"/api/v1/spaces/{sid}", headers=outsider).status_code
            == 404
        )
        assert (
            session.client.get("/api/v1/spaces", headers=outsider).json()["items"] == []
        )
        # 空间不存在 → 同样 404
        assert (
            session.client.get(
                "/api/v1/spaces/00000000-0000-0000-0000-000000000000",
                headers=session.owner,
            ).status_code
            == 404
        )

        # 显式添加成员 → 成员可见详情（含成员表）
        session.activate_member("n331b")
        added = add_member(session, session.owner, sid, "n331b")
        assert added["role"] == "member"
        assert added["active"] is True
        detail = session.client.get(f"/api/v1/spaces/{sid}", headers=session.owner)
        assert detail.status_code == 200
        members = detail.json()["members"]
        assert [m["username"] for m in members] == ["owner", "n331b"]

        # 重复添加 → 409；未知用户名 → 422
        dup = session.client.post(
            f"/api/v1/spaces/{sid}/members",
            json={"username": "n331b"},
            headers=session.owner,
        )
        assert dup.status_code == 409
        unknown = session.client.post(
            f"/api/v1/spaces/{sid}/members",
            json={"username": "nobody-here"},
            headers=session.owner,
        )
        assert unknown.status_code == 422

        # 成员越权管理者动作 → 403
        member_headers = session.login("n331b")
        forbidden = session.client.post(
            f"/api/v1/spaces/{sid}/members",
            json={"username": "n331c"},
            headers=member_headers,
        )
        assert forbidden.status_code == 403

        # 成员自行退出 → 空间权限消失（404）；管理者行不可移除（403）
        member_row = next(m for m in members if m["username"] == "n331b")
        leave = session.client.delete(
            f"/api/v1/spaces/{sid}/members/{member_row['id']}", headers=member_headers
        )
        assert leave.status_code == 204
        assert (
            session.client.get(
                f"/api/v1/spaces/{sid}", headers=member_headers
            ).status_code
            == 404
        )
        manager_row = next(m for m in members if m["role"] == "manager")
        self_remove = session.client.delete(
            f"/api/v1/spaces/{sid}/members/{manager_row['id']}", headers=session.owner
        )
        assert self_remove.status_code == 403


def test_meeting_full_flow(monkeypatch, tmp_path):
    """会议资料单：创建 → 成员显式添加资料（快照）→ 结束 → 结论与出处。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(session, "n331b", name="会议空间")
        sid = space["id"]
        member = session.login("n331b")

        created = session.client.post(
            f"/api/v1/spaces/{sid}/meetings",
            json={"title": "第 1 次共读会"},
            headers=session.owner,
        )
        assert created.status_code == 201, created.text
        meeting_id = created.json()["id"]

        # 成员显式添加资料项（标题/摘要是添加时点快照）
        item_a = session.client.post(
            f"/api/v1/spaces/{sid}/meetings/{meeting_id}/items",
            json={
                "entryRef": "entry-77",
                "title": "共享文章 A",
                "excerpt": "文章 A 的共享摘录",
                "question": "结论 B 是否被第 3 段支持？",
            },
            headers=member,
        )
        assert item_a.status_code == 201, item_a.text
        assert item_a.json()["question"] == "结论 B 是否被第 3 段支持？"

        # 结论在会议结束前 → 422（结束后保存）
        early = session.client.post(
            f"/api/v1/spaces/{sid}/meetings/{meeting_id}/outcomes",
            json={"summary": "过早的结论"},
            headers=session.owner,
        )
        assert early.status_code == 422

        # 非发起者成员结束会议 → 403；发起者结束 → 200
        close_forbidden = session.client.post(
            f"/api/v1/spaces/{sid}/meetings/{meeting_id}/close", headers=member
        )
        assert close_forbidden.status_code == 403
        closed = session.client.post(
            f"/api/v1/spaces/{sid}/meetings/{meeting_id}/close", headers=session.owner
        )
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
        assert closed.json()["closedAt"] is not None

        # 结束后不能再添加资料项；可以保存结论与出处
        late_item = session.client.post(
            f"/api/v1/spaces/{sid}/meetings/{meeting_id}/items",
            json={"entryRef": "entry-78", "title": "迟到的资料"},
            headers=member,
        )
        assert late_item.status_code == 422
        outcome = session.client.post(
            f"/api/v1/spaces/{sid}/meetings/{meeting_id}/outcomes",
            json={"summary": "第 3 段不支持结论 B；改引第 5 段。", "entryRef": "entry-77"},
            headers=member,
        )
        assert outcome.status_code == 201, outcome.text
        assert outcome.json()["outcomes"][0]["entryRef"] == "entry-77"

        # 详情：资料项 + 结论都在（完整保留）
        detail = session.client.get(
            f"/api/v1/spaces/{sid}/meetings/{meeting_id}", headers=member
        )
        assert detail.status_code == 200
        assert len(detail.json()["items"]) == 1
        assert len(detail.json()["outcomes"]) == 1
        assert detail.json()["items"][0]["excerpt"] == "文章 A 的共享摘录"

        # 非成员（未被添加）访问会议 → 404
        outsider = session.activate_member("n331c")
        assert (
            session.client.get(
                f"/api/v1/spaces/{sid}/meetings/{meeting_id}", headers=outsider
            ).status_code
            == 404
        )
