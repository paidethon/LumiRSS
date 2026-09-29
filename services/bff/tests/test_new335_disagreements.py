"""NEW-335 共读分歧记录 —— 并列保存不同结论与各自引用；证据补充；不强制统一结论。"""

from new231_helpers import ab_session
from new331_helpers import space_with_members


def test_disagreement_parallel_positions_and_evidence(monkeypatch, tmp_path):
    """A/B 各自的结论并列保存（每人一条、可改写自己的）；任何成员补充
    证据（可挂立场）；闭合只是停笔——无「统一结论」字段。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(session, "n335a", "n335b", name="分歧空间")
        sid = space["id"]
        member_a = session.login("n335a")
        member_b = session.login("n335b")

        created = session.client.post(
            f"/api/v1/spaces/{sid}/disagreements",
            json={"title": "第 4 段数据是否支持结论", "entryRef": "entry-9"},
            headers=member_a,
        )
        assert created.status_code == 201, created.text
        did = created.json()["id"]

        pos_a = session.client.put(
            f"/api/v1/spaces/{sid}/disagreements/{did}/positions/my",
            json={
                "conclusion": "支持：表 2 的增幅显著。",
                "citations": [{"ref": "entry-9", "note": "第 4 段表 2"}],
            },
            headers=member_a,
        )
        assert pos_a.status_code == 200, pos_a.text
        pos_b = session.client.put(
            f"/api/v1/spaces/{sid}/disagreements/{did}/positions/my",
            json={
                "conclusion": "不支持：样本期只有三个月。",
                "citations": [{"note": "第 7 段方法说明"}],
            },
            headers=member_b,
        )
        assert pos_b.status_code == 200

        detail = session.client.get(
            f"/api/v1/spaces/{sid}/disagreements/{did}", headers=session.owner
        )
        positions = detail.json()["positions"]
        assert len(positions) == 2  # 并列，不合并
        assert {p["authorUsername"] for p in positions} == {"n335a", "n335b"}

        # A 改写自己的结论（upsert 仍一人一条）
        pos_a2 = session.client.put(
            f"/api/v1/spaces/{sid}/disagreements/{did}/positions/my",
            json={"conclusion": "部分支持：增幅显著但外推受限。"},
            headers=member_a,
        )
        assert pos_a2.status_code == 200
        detail = session.client.get(
            f"/api/v1/spaces/{sid}/disagreements/{did}", headers=member_a
        )
        assert len(detail.json()["positions"]) == 2
        mine = next(
            p
            for p in detail.json()["positions"]
            if p["authorUsername"] == "n335a"
        )
        assert mine["conclusion"].startswith("部分支持")
        assert mine["citations"] == []  # 改写覆盖

        # 证据：B 给整体 + 挂在 A 立场上各补一条
        ev_all = session.client.post(
            f"/api/v1/spaces/{sid}/disagreements/{did}/evidence",
            json={"note": "官方修订版附录提供了全年数据。", "ref": "entry-10"},
            headers=member_b,
        )
        assert ev_all.status_code == 201
        position_id = next(
            p["id"]
            for p in detail.json()["positions"]
            if p["authorUsername"] == "n335a"
        )
        ev_pos = session.client.post(
            f"/api/v1/spaces/{sid}/disagreements/{did}/evidence",
            json={"note": "补充：作者博客承认外推限制。", "positionId": position_id},
            headers=session.owner,
        )
        assert ev_pos.status_code == 201
        # 不存在的立场 → 422
        ev_bad = session.client.post(
            f"/api/v1/spaces/{sid}/disagreements/{did}/evidence",
            json={"note": "挂错立场", "positionId": "00000000-0000-0000-0000-000000000000"},
            headers=member_b,
        )
        assert ev_bad.status_code == 422

        # 闭合（发起者）→ 停笔；再补立场 422；重新打开（管理者）可继续
        closed = session.client.post(
            f"/api/v1/spaces/{sid}/disagreements/{did}/close",
            json={"closed": True},
            headers=member_a,
        )
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
        frozen = session.client.put(
            f"/api/v1/spaces/{sid}/disagreements/{did}/positions/my",
            json={"conclusion": "闭合后不能再写。"},
            headers=member_b,
        )
        assert frozen.status_code == 422
        reopened = session.client.post(
            f"/api/v1/spaces/{sid}/disagreements/{did}/close",
            json={"closed": False},
            headers=session.owner,
        )
        assert reopened.json()["status"] == "open"

        # 非成员 404；成员不能闭合他人分歧（403：非发起者非管理者）
        outsider = session.activate_member("n335c")
        assert (
            session.client.get(
                f"/api/v1/spaces/{sid}/disagreements/{did}", headers=outsider
            ).status_code
            == 404
        )
        session.activate_member("n335d")
        session.client.post(
            f"/api/v1/spaces/{sid}/members", json={"username": "n335d"}, headers=session.owner
        )
        member_d = session.login("n335d")
        close_forbidden = session.client.post(
            f"/api/v1/spaces/{sid}/disagreements/{did}/close",
            json={"closed": True},
            headers=member_d,
        )
        assert close_forbidden.status_code == 403
