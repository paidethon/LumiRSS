"""NEW-236 批注回复提醒 — 显式共享 / 回复 / 收件人提醒与关闭 / 越权。

隐私前提：线程只由 owner 显式 share 创建（私人批注绝不自动共享）；
收件人可查看原上下文、回复、关闭提醒；非成员一律 404。
"""

from new231_helpers import ab_session


def _owner_annotation(session) -> dict:
    created = session.client.post(
        "/api/v1/annotations",
        json={
            "entryRef": "9901",
            "anchor": {"paraId": "p-3", "exact": "共享摘录上下文", "prefix": "", "suffix": ""},
            "excerpt": "共享摘录上下文",
            "note": "owner 的批注",
        },
        headers=session.owner,
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_new236_share_reply_dismiss_flow(monkeypatch, tmp_path):
    """owner 显式共享 → 收件人提醒箱可见原上下文 → 双方回复 → 收件人
    查看即清未读 → 关闭提醒 → 收件箱为空（历史可查）→ owner 再共享重开。"""
    with ab_session(monkeypatch, tmp_path) as session:
        annotation = _owner_annotation(session)
        member = session.activate_member("n236b")

        # 未共享前：收件箱为空（私人批注绝不自动进入共享面）
        assert session.client.get(
            "/api/v1/annotation-replies", headers=member
        ).json()["items"] == []

        shared = session.client.post(
            f"/api/v1/annotations/{annotation['id']}/share",
            json={"withUsername": "n236b"},
            headers=session.owner,
        )
        assert shared.status_code == 201, shared.text
        thread = shared.json()
        assert thread["sharedWithUsername"] == "n236b"
        assert thread["excerpt"] == "共享摘录上下文"
        assert thread["unreadForRecipient"] == 0

        # 收件人提醒箱：一条未读提醒（含原上下文快照）
        inbox = session.client.get("/api/v1/annotation-replies", headers=member)
        assert inbox.status_code == 200
        items = inbox.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == thread["id"]
        assert items[0]["note"] == "owner 的批注"
        assert items[0]["entryRef"] == annotation["entryRef"]

        # 收件人回复 → owner 未读视角（owner 列表可见串）
        reply = session.client.post(
            f"/api/v1/annotation-replies/{thread['id']}/replies",
            json={"body": "这条批注的上下文在第 3 段，我补充了背景。"},
            headers=member,
        )
        assert reply.status_code == 201, reply.text
        assert len(reply.json()["replies"]) == 1

        # 收件人查看详情（查看原上下文即清未读）
        detail = session.client.get(
            f"/api/v1/annotation-replies/{thread['id']}", headers=member
        )
        assert detail.status_code == 200
        assert detail.json()["unreadForRecipient"] == 0

        # owner 回复 → 收件人未读 +1
        owner_reply = session.client.post(
            f"/api/v1/annotation-replies/{thread['id']}/replies",
            json={"body": "收到，已按你的建议修正。"},
            headers=session.owner,
        )
        assert owner_reply.status_code == 201
        inbox = session.client.get("/api/v1/annotation-replies", headers=member)
        assert inbox.json()["items"][0]["unreadForRecipient"] == 1

        # 收件人关闭该串提醒 → 默认收件箱消失；历史可查
        dismissed = session.client.post(
            f"/api/v1/annotation-replies/{thread['id']}/dismiss", headers=member
        )
        assert dismissed.status_code == 204
        assert (
            session.client.get("/api/v1/annotation-replies", headers=member).json()[
                "items"
            ]
            == []
        )
        history = session.client.get(
            "/api/v1/annotation-replies", params={"includeDismissed": "true"}, headers=member
        )
        assert len(history.json()["items"]) == 1
        assert history.json()["items"][0]["dismissedAt"] is not None

        # owner 再次显式共享 → 重开提醒（不伪造未读计数）
        again = session.client.post(
            f"/api/v1/annotations/{annotation['id']}/share",
            json={"withUsername": "n236b"},
            headers=session.owner,
        )
        assert again.status_code == 201
        assert again.json()["dismissedAt"] is None
        assert again.json()["unreadForRecipient"] == 0
        assert len(again.json()["replies"]) == 2  # 回复历史保留

        # owner 撤销共享 → 串与回复删除，双方不可见
        revoked = session.client.delete(
            f"/api/v1/annotations/{annotation['id']}/share/{thread['id']}",
            headers=session.owner,
        )
        assert revoked.status_code == 204
        assert (
            session.client.get(
                "/api/v1/annotation-replies", params={"includeDismissed": "true"},
                headers=member,
            ).json()["items"]
            == []
        )
        assert (
            session.client.get(
                f"/api/v1/annotation-replies/{thread['id']}", headers=member
            ).status_code
            == 404
        )


def test_new236_share_validation(monkeypatch, tmp_path):
    """未知收件人 422；共享给自己 422；未知批注 404；owner 视角列表。"""
    with ab_session(monkeypatch, tmp_path) as session:
        annotation = _owner_annotation(session)

        unknown = session.client.post(
            f"/api/v1/annotations/{annotation['id']}/share",
            json={"withUsername": "no-such-member"},
            headers=session.owner,
        )
        assert unknown.status_code == 422
        assert unknown.json()["error"]["type"] == "share_recipient_unknown"

        himself = session.client.post(
            f"/api/v1/annotations/{annotation['id']}/share",
            json={"withUsername": "owner"},
            headers=session.owner,
        )
        assert himself.status_code == 422
        assert himself.json()["error"]["type"] == "share_recipient_self"

        missing = session.client.post(
            "/api/v1/annotations/no-such/share",
            json={"withUsername": "owner"},
            headers=session.owner,
        )
        assert missing.status_code == 404

        member = session.activate_member("n236c")
        empty_body = session.client.post(
            "/api/v1/annotation-replies/x/replies", json={"body": "x"}, headers=member
        )
        assert empty_body.status_code == 404  # 非成员串对局外人 404

        # owner 视角：尚未共享 → 空
        assert (
            session.client.get("/api/v1/annotation-shares", headers=session.owner).json()[
                "items"
            ]
            == []
        )


def test_new236_third_user_cannot_see_thread(monkeypatch, tmp_path):
    """C（非成员）不能读写 A→B 的串（统一 404，不泄露存在性）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        annotation = _owner_annotation(session)
        session.activate_member("n236b")
        third = session.activate_member("n236d")

        shared = session.client.post(
            f"/api/v1/annotations/{annotation['id']}/share",
            json={"withUsername": "n236b"},
            headers=session.owner,
        )
        thread_id = shared.json()["id"]

        for method, path, kwargs in (
            ("get", f"/api/v1/annotation-replies/{thread_id}", None),
            ("post", f"/api/v1/annotation-replies/{thread_id}/replies", {"json": {"body": "局外人的回复"}}),
            ("post", f"/api/v1/annotation-replies/{thread_id}/dismiss", None),
            ("delete", f"/api/v1/annotations/{annotation['id']}/share/{thread_id}", None),
        ):
            call = getattr(session.client, method)
            response = call(path, headers=third, **(kwargs or {}))
            assert response.status_code == 404, (method, path, response.status_code)

        # C 的提醒箱为空
        assert (
            session.client.get("/api/v1/annotation-replies", headers=third).json()[
                "items"
            ]
            == []
        )

