"""NEW-334 空间成员到期管理 —— 到期撤销空间权限、不删个人账户、可续期。"""

from datetime import UTC, datetime, timedelta

from new231_helpers import ab_session
from new331_helpers import space_with_members


def _iso(**delta: int) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat(timespec="seconds")


def test_expiry_revokes_space_access_only(monkeypatch, tmp_path):
    """到期成员访问空间 → 404（与无成员资格同口径）；其个人账户与自己的
    数据面完全不受影响；管理者 sweep 落审计台账（幂等）；续期恢复访问。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, members = space_with_members(session, "n334b", name="到期空间")
        sid = space["id"]
        member_b = session.login("n334b")
        member_row = members[0]

        # 基线：B 在 A/B 各自的库里留下了自己的数据（批注面即个人面）
        own_data = session.client.get("/api/v1/reading/pacts", headers=member_b)
        assert own_data.status_code == 200

        # 管理者设定到期时间（过去）→ 到期立即失效
        expired = session.client.put(
            f"/api/v1/spaces/{sid}/members/{member_row['id']}/expiry",
            json={"expiresAt": _iso(hours=-1)},
            headers=session.owner,
        )
        assert expired.status_code == 200, expired.text
        assert expired.json()["active"] is False
        assert expired.json()["expired"] is True

        # 到期撤销的是空间权限：空间面 404；个人账户面照常可用
        assert (
            session.client.get(f"/api/v1/spaces/{sid}", headers=member_b).status_code
            == 404
        )
        assert (
            session.client.get("/api/v1/reading/pacts", headers=member_b).status_code
            == 200
        )
        authed = session.client.get("/api/v1/auth/session", headers=member_b)
        assert authed.status_code == 200
        assert authed.json()["username"] == "n334b"

        # 管理者 sweep → 'expired' 台账一条；重复 sweep 幂等
        swept = session.client.post(
            f"/api/v1/spaces/{sid}/members/sweep", headers=session.owner
        )
        assert swept.status_code == 200
        assert [row["username"] for row in swept.json()["expired"]] == ["n334b"]
        swept_again = session.client.post(
            f"/api/v1/spaces/{sid}/members/sweep", headers=session.owner
        )
        assert swept_again.json()["expired"] == []

        # 台账成员可读（B 已无权限 → owner 读）
        log = session.client.get(
            f"/api/v1/spaces/{sid}/member-expiry-log", headers=session.owner
        )
        assert [row["action"] for row in log.json()["items"]] == ["expired", "expiry_set"]

        # 续期（未来到期）→ 访问恢复
        renewed = session.client.put(
            f"/api/v1/spaces/{sid}/members/{member_row['id']}/expiry",
            json={"expiresAt": _iso(days=7)},
            headers=session.owner,
        )
        assert renewed.status_code == 200
        assert renewed.json()["active"] is True
        assert (
            session.client.get(f"/api/v1/spaces/{sid}", headers=member_b).status_code
            == 200
        )
        log = session.client.get(
            f"/api/v1/spaces/{sid}/member-expiry-log", headers=session.owner
        )
        assert [row["action"] for row in log.json()["items"]] == [
            "renewed", "expired", "expiry_set"
        ]

        # 清除到期 → 永久成员
        cleared = session.client.put(
            f"/api/v1/spaces/{sid}/members/{member_row['id']}/expiry",
            json={"expiresAt": None},
            headers=session.owner,
        )
        assert cleared.status_code == 200
        assert cleared.json()["expiresAt"] is None


def test_expiry_permissions_and_invalid_payload(monkeypatch, tmp_path):
    """成员不能设定到期（403）；管理者行不可设到期（403）；非法时间 422；
    成员行不存在 → 404。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, members = space_with_members(session, "n334c", name="权限空间")
        sid = space["id"]
        member = session.login("n334c")

        forbidden = session.client.put(
            f"/api/v1/spaces/{sid}/members/{members[0]['id']}/expiry",
            json={"expiresAt": _iso(days=1)},
            headers=member,
        )
        assert forbidden.status_code == 403

        sweep_forbidden = session.client.post(
            f"/api/v1/spaces/{sid}/members/sweep", headers=member
        )
        assert sweep_forbidden.status_code == 403

        detail = session.client.get(f"/api/v1/spaces/{sid}", headers=session.owner)
        manager_row = next(
            m for m in detail.json()["members"] if m["role"] == "manager"
        )
        manager_target = session.client.put(
            f"/api/v1/spaces/{sid}/members/{manager_row['id']}/expiry",
            json={"expiresAt": _iso(days=1)},
            headers=session.owner,
        )
        assert manager_target.status_code == 403

        bad = session.client.put(
            f"/api/v1/spaces/{sid}/members/{members[0]['id']}/expiry",
            json={"expiresAt": "not-a-date"},
            headers=session.owner,
        )
        assert bad.status_code == 422
        missing = session.client.put(
            f"/api/v1/spaces/{sid}/members/00000000-0000-0000-0000-000000000000/expiry",
            json={"expiresAt": _iso(days=1)},
            headers=session.owner,
        )
        assert missing.status_code == 404
