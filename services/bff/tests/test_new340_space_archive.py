"""NEW-340 空间归档流程 —— 未完成任务盘点 / force 归档 / 只读 / 恢复重确认成员。"""

from new231_helpers import ab_session
from new331_helpers import space_with_members


def _seed_open_tasks(session, sid: str) -> dict:
    contribution = session.client.post(
        f"/api/v1/spaces/{sid}/contributions",
        json={"entryRef": "entry-50", "title": "待审投稿"},
        headers=session.owner,
    )
    assert contribution.status_code == 201
    # 开审批让投稿保持 pending
    toggled = session.client.put(
        f"/api/v1/spaces/{sid}/settings", json={"requireApproval": True}, headers=session.owner
    )
    assert toggled.status_code == 200
    second = session.client.post(
        f"/api/v1/spaces/{sid}/contributions",
        json={"entryRef": "entry-51", "title": "另一条待审"},
        headers=session.owner,
    )
    assert second.status_code == 201
    meeting = session.client.post(
        f"/api/v1/spaces/{sid}/meetings", json={"title": "未结束会议"}, headers=session.owner
    )
    assert meeting.status_code == 201
    discussion = session.client.post(
        f"/api/v1/spaces/{sid}/discussions",
        json={"title": "未解决问题", "question": "尚待讨论"},
        headers=session.owner,
    )
    assert discussion.status_code == 201
    return {
        "contribution_pending": second.json()["id"],
        "meeting_open": meeting.json()["id"],
        "discussion_open": discussion.json()["id"],
    }


def test_archive_flow_preview_block_force_readonly(monkeypatch, tmp_path):
    """归档前列出未完成任务（preview 零写入）；有任务时归档 409 并附清单；
    force 显式确认后归档；归档后写动作 409、读取保留；非管理者 403。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, members = space_with_members(session, "n340b", name="归档空间")
        sid = space["id"]
        tasks = _seed_open_tasks(session, sid)

        preview = session.client.get(
            f"/api/v1/spaces/{sid}/archive/preview", headers=session.owner
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["openTaskCount"] == 3
        kinds = {task["kind"] for task in body["openTasks"]}
        assert kinds == {"contribution_pending", "meeting_open", "discussion_open"}
        # preview 零写入：任务原样
        preview_again = session.client.get(
            f"/api/v1/spaces/{sid}/archive/preview", headers=session.owner
        )
        assert preview_again.json()["openTaskCount"] == 3

        # 有任务且未 force → 409 + 任务清单
        blocked = session.client.post(
            f"/api/v1/spaces/{sid}/archive", json={"force": False}, headers=session.owner
        )
        assert blocked.status_code == 409
        blocked_body = blocked.json()
        assert blocked_body["error"]["type"] == "archive_blocked"
        assert blocked_body["error"]["openTaskCount"] == 3

        # 处理一条（闭合会议）→ 剩 2；force 归档
        closed = session.client.post(
            f"/api/v1/spaces/{sid}/meetings/{tasks['meeting_open']}/close",
            headers=session.owner,
        )
        assert closed.status_code == 200
        forced = session.client.post(
            f"/api/v1/spaces/{sid}/archive", json={"force": True}, headers=session.owner
        )
        assert forced.status_code == 200, forced.text
        assert forced.json()["action"] == "archived"
        assert forced.json()["forced"] is True
        assert len(forced.json()["tasks"]) == 2

        # 归档后：写动作 409；读取保留
        assert (
            session.client.post(
                f"/api/v1/spaces/{sid}/meetings", json={"title": "新会议"}, headers=session.owner
            ).status_code
            == 409
        )
        assert (
            session.client.post(
                f"/api/v1/spaces/{sid}/discussions/{tasks['discussion_open']}/replies",
                json={"body": "归档后回复"},
                headers=session.owner,
            ).status_code
            == 409
        )
        assert (
            session.client.get(f"/api/v1/spaces/{sid}", headers=session.owner).status_code
            == 200
        )
        member_b = session.login("n340b")
        assert (
            session.client.get(
                f"/api/v1/spaces/{sid}/discussions/{tasks['discussion_open']}",
                headers=member_b,
            ).status_code
            == 200
        )

        # 非管理者不能归档/恢复；台账成员可读
        member_archive = session.client.post(
            f"/api/v1/spaces/{sid}/archive", json={"force": True}, headers=member_b
        )
        assert member_archive.status_code == 403
        log = session.client.get(f"/api/v1/spaces/{sid}/archive-log", headers=member_b)
        assert [row["action"] for row in log.json()["items"]] == ["archived"]


def test_restore_reconfirms_members(monkeypatch, tmp_path):
    """恢复时逐成员重新确认：keep 清单外的成员被撤销空间权限（账户不动）；
    keep 清单必须是已知成员行（未知 → 422）；未归档时恢复 → 422。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, members = space_with_members(session, "n340c", "n340d", name="恢复空间")
        sid = space["id"]
        member_c = session.login("n340c")
        member_d = session.login("n340d")
        _seed_open_tasks(session, sid)
        archived = session.client.post(
            f"/api/v1/spaces/{sid}/archive", json={"force": True}, headers=session.owner
        )
        assert archived.status_code == 200

        # 未归档恢复 / 未知成员行 → 422（先在另一空间验证未归档分支）
        fresh = space_with_members(session, "n340e", name="未归档空间")
        fresh_restore = session.client.post(
            f"/api/v1/spaces/{fresh[0]['id']}/restore",
            json={"keepMemberIds": []},
            headers=session.owner,
        )
        assert fresh_restore.status_code == 422

        unknown = session.client.post(
            f"/api/v1/spaces/{sid}/restore",
            json={"keepMemberIds": ["00000000-0000-0000-0000-000000000000"]},
            headers=session.owner,
        )
        assert unknown.status_code == 422

        # 只保留 n340c（成员行来自归档前的清单；取详情需要管理者读归档空间——只读仍可）
        detail = session.client.get(f"/api/v1/spaces/{sid}", headers=session.owner)
        assert detail.status_code == 200
        member_rows = {
            m["username"]: m["id"]
            for m in detail.json()["members"]
            if m["role"] == "member" and m["revokedAt"] is None
        }
        restored = session.client.post(
            f"/api/v1/spaces/{sid}/restore",
            json={"keepMemberIds": [member_rows["n340c"]]},
            headers=session.owner,
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["action"] == "restored"
        assert restored.json()["archivedAt"] is None

        # n340c 保留访问；n340d 权限被撤销（404）但个人账户不受影响
        assert (
            session.client.get(f"/api/v1/spaces/{sid}", headers=member_c).status_code
            == 200
        )
        assert (
            session.client.get(f"/api/v1/spaces/{sid}", headers=member_d).status_code
            == 404
        )
        assert (
            session.client.get("/api/v1/auth/session", headers=member_d).status_code
            == 200
        )

        # 恢复动作入台账（含 keep 名单对应的 userId）
        log = session.client.get(f"/api/v1/spaces/{sid}/archive-log", headers=session.owner)
        actions = [row["action"] for row in log.json()["items"]]
        assert actions == ["restored", "archived"]
        restored_row = log.json()["items"][0]
        assert len(restored_row["keptMembers"]) == 1

        # 恢复后可正常写入（只读解除）
        writing = session.client.post(
            f"/api/v1/spaces/{sid}/meetings", json={"title": "恢复后的会议"}, headers=session.owner
        )
        assert writing.status_code == 201


def test_restore_drops_all_when_empty_list(monkeypatch, tmp_path):
    """keepMemberIds=[] 是显式确认：恢复后只剩管理者。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, members = space_with_members(session, "n340f", name="清空恢复空间")
        sid = space["id"]
        member_f = session.login("n340f")
        archived = session.client.post(
            f"/api/v1/spaces/{sid}/archive", json={"force": True}, headers=session.owner
        )
        assert archived.status_code == 200
        restored = session.client.post(
            f"/api/v1/spaces/{sid}/restore",
            json={"keepMemberIds": []},
            headers=session.owner,
        )
        assert restored.status_code == 200
        assert restored.json()["keptMembers"] == []
        assert (
            session.client.get(f"/api/v1/spaces/{sid}", headers=member_f).status_code
            == 404
        )
        assert (
            session.client.get(f"/api/v1/spaces/{sid}", headers=session.owner).status_code
            == 200
        )
