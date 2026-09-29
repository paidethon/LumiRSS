"""NEW-337 空间活动摘要 —— 按用户选的时间段汇总共享面变化；不含私人阅读记录。"""

from datetime import UTC, datetime, timedelta

from new231_helpers import ab_session
from new331_helpers import space_with_members


def test_activity_summary_counts_and_scope(monkeypatch, tmp_path):
    """一段真实活动（投稿/审批/会议/讨论/版本通知/附件共享）→ 计数与
    recent 对得上；成员可读；非成员 404；响应明示不含私人阅读记录。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(session, "n337b", name="摘要空间")
        sid = space["id"]
        member = session.login("n337b")

        # 一段真实共享面活动
        contribution = session.client.post(
            f"/api/v1/spaces/{sid}/contributions",
            json={"entryRef": "entry-40", "title": "共享一篇"},
            headers=member,
        )
        assert contribution.status_code == 201
        meeting = session.client.post(
            f"/api/v1/spaces/{sid}/meetings", json={"title": "周会"}, headers=session.owner
        )
        meeting_id = meeting.json()["id"]
        discussion = session.client.post(
            f"/api/v1/spaces/{sid}/discussions",
            json={"title": "口径讨论", "question": "口径是什么？", "entryRef": "entry-40"},
            headers=member,
        )
        discussion_id = discussion.json()["id"]
        session.client.post(
            f"/api/v1/spaces/{sid}/discussions/{discussion_id}/replies",
            json={"body": "口径见第 2 段。"},
            headers=session.owner,
        )
        session.client.post(
            f"/api/v1/spaces/{sid}/meetings/{meeting_id}/close", headers=session.owner
        )
        session.client.post(
            f"/api/v1/spaces/{sid}/version-notices",
            json={"entryRef": "entry-40", "versionLabel": "v2"},
            headers=session.owner,
        )
        session.client.post(
            f"/api/v1/spaces/{sid}/attachment-shares",
            json={"attachmentRef": "att-1", "name": "数据表.csv", "sizeBytes": 2048},
            headers=member,
        )

        frm = (datetime.now(UTC) - timedelta(hours=1)).isoformat(timespec="seconds")
        to = (datetime.now(UTC) + timedelta(minutes=5)).isoformat(timespec="seconds")
        summary = session.client.get(
            f"/api/v1/spaces/{sid}/activity",
            params={"from": frm, "to": to},
            headers=session.owner,
        )
        assert summary.status_code == 200, summary.text
        body = summary.json()
        assert body["scope"] == "space-shared-only"
        assert "私人阅读记录" in body["note"]

        counts = body["counts"]
        assert counts["contributions"]["submitted"] == 1
        assert counts["meetings"]["created"] == 1
        assert counts["meetings"]["closed"] == 1
        assert counts["discussions"]["asked"] == 1
        assert counts["discussions"]["replies"] == 1
        assert counts["versionNotices"]["reported"] == 1
        assert counts["attachmentShares"]["shared"] == 1
        assert counts["members"] == 2  # owner + n337b

        assert any(item["title"] == "共享一篇" for item in body["recent"]["contributions"])
        assert any(item["title"] == "数据表.csv" for item in body["recent"]["attachmentShares"])

        # 成员可读；管理员设置的时间段非法 → 422；非成员 → 404
        assert (
            session.client.get(
                f"/api/v1/spaces/{sid}/activity",
                params={"from": frm, "to": to},
                headers=member,
            ).status_code
            == 200
        )
        bad_range = session.client.get(
            f"/api/v1/spaces/{sid}/activity",
            params={"from": to, "to": frm},
            headers=session.owner,
        )
        assert bad_range.status_code == 422
        outsider = session.activate_member("n337z")
        assert (
            session.client.get(
                f"/api/v1/spaces/{sid}/activity", headers=outsider
            ).status_code
            == 404
        )

        # 私人面不进入摘要：B 在自己库里造的私人批注不影响共享面计数
        own = session.client.post(
            "/api/v1/annotations",
            json={
                "entryRef": "9999",
                "anchor": {"paraId": "p-1", "exact": "私人", "prefix": "", "suffix": ""},
                "excerpt": "私人摘录",
                "note": "私人笔记",
            },
            headers=member,
        )
        assert own.status_code == 201, own.text
        after = session.client.get(
            f"/api/v1/spaces/{sid}/activity",
            params={"from": frm, "to": to},
            headers=session.owner,
        )
        assert after.json()["counts"] == counts
