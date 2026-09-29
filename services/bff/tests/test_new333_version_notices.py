"""NEW-333 共读内容版本通知 —— 显式报告版本更新 → 讨论参与者收到待核对提醒。"""

from new231_helpers import ab_session
from new331_helpers import space_with_members


def _ask_discussion(session, sid: str, headers: dict, entry_ref: str, title: str) -> dict:
    response = session.client.post(
        f"/api/v1/spaces/{sid}/discussions",
        json={"title": title, "question": f"{title} 的待讨论问题", "entryRef": entry_ref},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_version_notice_notifies_discussion_participants(monkeypatch, tmp_path):
    """B 就条目 X 提问（参与者 = B）；owner 回复（参与者 += owner）；
    B 报告 X 新版本 → 提醒发给 owner（参与者）而非报告人 B 自己；
    owner 标记已核对后待办清空；ack 幂等。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(session, "n333b", name="版本空间")
        sid = space["id"]
        member_b = session.login("n333b")

        _ask_discussion(session, sid, member_b, "entry-x", "第 3 段引用核对")
        owner_reply = session.client.post(
            f"/api/v1/spaces/{sid}/discussions",
            json={"title": "占位", "question": "另一问", "entryRef": "entry-x"},
            headers=session.owner,
        )
        assert owner_reply.status_code == 201

        # B 显式报告新版本（B 是报告人 → 自己不进提醒名单）
        reported = session.client.post(
            f"/api/v1/spaces/{sid}/version-notices",
            json={
                "entryRef": "entry-x",
                "versionLabel": "v2（2026-09 更新版）",
                "summary": "正文第 3 段已改写，引用可能失效。",
            },
            headers=member_b,
        )
        assert reported.status_code == 201, reported.text
        notice = reported.json()
        ack_user_ids = {ack["userId"] for ack in notice["acks"]}
        owner_user_id = session.client.get(
            "/api/v1/auth/session", headers=session.owner
        ).json()["userId"]
        # 只有讨论参与者 owner 收到提醒（报告人 B 被排除）
        assert ack_user_ids == {owner_user_id}

        # owner 的待核对清单含该通知；B 的待核对为空
        owner_pending = session.client.get(
            f"/api/v1/spaces/{sid}/version-notices",
            params={"scope": "pending"},
            headers=session.owner,
        )
        assert [item["id"] for item in owner_pending.json()["items"]] == [notice["id"]]
        assert owner_pending.json()["items"][0]["versionLabel"] == "v2（2026-09 更新版）"
        b_pending = session.client.get(
            f"/api/v1/spaces/{sid}/version-notices",
            params={"scope": "pending"},
            headers=member_b,
        )
        assert b_pending.json()["items"] == []

        # 未参与讨论的成员 → 不在提醒名单；ack 视为不存在 → 404
        session.activate_member("n333c")
        add_c = session.client.post(
            f"/api/v1/spaces/{sid}/members", json={"username": "n333c"}, headers=session.owner
        )
        assert add_c.status_code == 201
        member_c = session.login("n333c")
        assert (
            session.client.post(
                f"/api/v1/spaces/{sid}/version-notices/{notice['id']}/ack",
                headers=member_c,
            ).status_code
            == 404
        )

        # owner 标记已重新核对（幂等）→ 待办清空；全体列表仍保留通知
        acked = session.client.post(
            f"/api/v1/spaces/{sid}/version-notices/{notice['id']}/ack",
            headers=session.owner,
        )
        assert acked.status_code == 200
        assert acked.json()["acks"][0]["acknowledgedAt"] is not None
        acked_again = session.client.post(
            f"/api/v1/spaces/{sid}/version-notices/{notice['id']}/ack",
            headers=session.owner,
        )
        assert acked_again.status_code == 200
        owner_pending = session.client.get(
            f"/api/v1/spaces/{sid}/version-notices",
            params={"scope": "pending"},
            headers=session.owner,
        )
        assert owner_pending.json()["items"] == []
        all_notices = session.client.get(
            f"/api/v1/spaces/{sid}/version-notices", headers=session.owner
        )
        assert len(all_notices.json()["items"]) == 1


def test_version_notice_boundary_and_isolation(monkeypatch, tmp_path):
    """无讨论参与者的条目 → 无提醒；非成员 404；回复者也是参与者。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(session, "n333d", name="边界空间")
        sid = space["id"]
        member_d = session.login("n333d")

        # D 回复了 owner 就条目 Y 的提问 → D 是参与者
        asked = _ask_discussion(session, sid, session.owner, "entry-y", "Y 的讨论")
        reply = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{asked['id']}/replies",
            json={"body": "我核对了第 2 段，引用无误。"},
            headers=member_d,
        )
        assert reply.status_code == 201

        reported = session.client.post(
            f"/api/v1/spaces/{sid}/version-notices",
            json={"entryRef": "entry-y", "versionLabel": "v9"},
            headers=session.owner,
        )
        assert reported.status_code == 201
        assert {ack["userId"] for ack in reported.json()["acks"]} == {
            reply.json()["replies"][0]["authorUserId"]
        }

        # 无讨论的条目 Z → 报告成功但零提醒
        quiet = session.client.post(
            f"/api/v1/spaces/{sid}/version-notices",
            json={"entryRef": "entry-z", "versionLabel": "v1"},
            headers=session.owner,
        )
        assert quiet.status_code == 201
        assert quiet.json()["acks"] == []

        # 非成员不可见任何版本通知面
        outsider = session.activate_member("n333e")
        assert (
            session.client.get(
                f"/api/v1/spaces/{sid}/version-notices", headers=outsider
            ).status_code
            == 404
        )
