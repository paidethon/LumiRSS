"""NEW-336 讨论待答与已解答 —— 发起者标记有用/解决；完整讨论保留。"""

from new231_helpers import ab_session
from new331_helpers import space_with_members


def test_discussion_ask_reply_helpful_resolve(monkeypatch, tmp_path):
    """创建即问题（open）→ 回复 → 发起者选中有用 → 标记解决（保留全部
    回复）→ 重新打开；非发起者不能标记有用/解决。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(session, "n336a", "n336b", name="问答空间")
        sid = space["id"]
        asker = session.login("n336a")
        replier = session.login("n336b")

        asked = session.client.post(
            f"/api/v1/spaces/{sid}/discussions",
            json={
                "title": "图表 3 的口径",
                "question": "图表 3 用的是同比还是环比？",
                "entryRef": "entry-30",
            },
            headers=asker,
        )
        assert asked.status_code == 201, asked.text
        discussion_id = asked.json()["id"]
        assert asked.json()["status"] == "open"

        reply_a = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/replies",
            json={"body": "是环比，图注有写。"},
            headers=replier,
        )
        assert reply_a.status_code == 201
        reply_b = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/replies",
            json={"body": "我核对了原文，确认是环比。"},
            headers=asker,
        )
        assert reply_b.status_code == 201
        replies = reply_b.json()["replies"]
        assert len(replies) == 2

        # 非发起者不能标记有用 / 解决
        helpful_forbidden = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/replies/{replies[0]['id']}/helpful",
            json={"helpful": True},
            headers=replier,
        )
        assert helpful_forbidden.status_code == 403
        resolve_forbidden = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/resolve",
            json={"replyId": replies[0]["id"]},
            headers=replier,
        )
        assert resolve_forbidden.status_code == 403

        # 发起者选中「有用」（set 语义可切换）
        marked = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/replies/{replies[0]['id']}/helpful",
            json={"helpful": True},
            headers=asker,
        )
        assert marked.status_code == 200
        assert marked.json()["replies"][0]["helpful"] is True
        unmarked = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/replies/{replies[0]['id']}/helpful",
            json={"helpful": False},
            headers=asker,
        )
        assert unmarked.json()["replies"][0]["helpful"] is False
        marked_again = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/replies/{replies[1]['id']}/helpful",
            json={"helpful": True},
            headers=asker,
        )
        assert marked_again.json()["replies"][1]["helpful"] is True

        # 标记解决（选中回复）→ resolved + 引用；完整讨论保留
        resolved = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/resolve",
            json={"replyId": replies[1]["id"]},
            headers=asker,
        )
        assert resolved.status_code == 200
        body = resolved.json()
        assert body["status"] == "resolved"
        assert body["resolvedReplyId"] == replies[1]["id"]
        assert body["resolvedAt"] is not None
        assert len(body["replies"]) == 2  # 完整保留

        # 状态筛选
        open_list = session.client.get(
            f"/api/v1/spaces/{sid}/discussions",
            params={"status": "open"},
            headers=asker,
        )
        assert open_list.json()["items"] == []
        resolved_list = session.client.get(
            f"/api/v1/spaces/{sid}/discussions",
            params={"status": "resolved"},
            headers=asker,
        )
        assert len(resolved_list.json()["items"]) == 1

        # 重新打开（replyId=null）→ open，讨论原样
        reopened = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/resolve",
            json={"replyId": None},
            headers=asker,
        )
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "open"
        assert reopened.json()["resolvedReplyId"] is None
        assert len(reopened.json()["replies"]) == 2

        # 不存在的回复 → 404；非成员 → 404
        missing_reply = session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/resolve",
            json={"replyId": "00000000-0000-0000-0000-000000000000"},
            headers=asker,
        )
        assert missing_reply.status_code == 404
        outsider = session.activate_member("n336z")
        assert (
            session.client.get(
                f"/api/v1/spaces/{sid}/discussions/{discussion_id}", headers=outsider
            ).status_code
            == 404
        )
