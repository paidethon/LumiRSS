"""NEW-346 设备信任期限 — 密码复核授予/错误密码 401/会话绝不延长/
到期判定（纯函数注入时间）/吊销后敏感操作重新被拦 + A/B 隔离。"""

from datetime import UTC, datetime, timedelta

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

TRUST_PATH = "/api/v1/privacy/device-trust"


def _member_password() -> str:
    from new2xx_ab import PASSWORD

    return PASSWORD


def test_new346_grant_and_status(ab_env):  # noqa: F811
    client = ab_env["client"]
    granted = client.post(
        TRUST_PATH,
        json={"password": _member_password(), "hours": 6},
        headers=ab_env["a"],
    )
    assert granted.status_code == 200, granted.text
    body = granted.json()
    assert body["renewed"] is False
    assert "不创建也不延长服务端会话" in body["note"]

    status = client.get(TRUST_PATH, headers=ab_env["a"]).json()
    assert status["currentDevice"]["trusted"] is True
    assert len(status["grants"]) == 1


def test_new346_wrong_password_401(ab_env):  # noqa: F811
    client = ab_env["client"]
    denied = client.post(
        TRUST_PATH,
        json={"password": "definitely-wrong-password", "hours": 6},
        headers=ab_env["a"],
    )
    assert denied.status_code == 401
    assert denied.json()["error"]["type"] == "invalid_credentials"
    status = client.get(TRUST_PATH, headers=ab_env["a"]).json()
    assert status["currentDevice"]["trusted"] is False


def test_new346_grant_does_not_extend_server_session(ab_env):  # noqa: F811
    """硬边界：授予前后服务端会话 expiresAt 逐字不变。"""
    client = ab_env["client"]
    before = client.get("/api/v1/auth/session", headers=ab_env["a"]).json()["expiresAt"]
    granted = client.post(
        TRUST_PATH,
        json={"password": _member_password(), "hours": 720},
        headers=ab_env["a"],
    )
    assert granted.status_code == 200
    after = client.get("/api/v1/auth/session", headers=ab_env["a"]).json()["expiresAt"]
    assert before == after


def test_new346_expiry_is_enforced(ab_env):  # noqa: F811
    """到期（注入过去时间）→ trusted False；纯函数判定。"""
    from lumirss.new346_device_trust import is_trusted

    future = datetime.now(UTC) + timedelta(hours=1)
    past = datetime.now(UTC) - timedelta(minutes=5)
    assert is_trusted({"trustedUntil": future.isoformat()}) is True
    assert is_trusted({"trustedUntil": past.isoformat()}) is False
    assert is_trusted(None) is False
    assert is_trusted({"trustedUntil": "not-a-date"}) is False

    client = ab_env["client"]
    client.post(
        TRUST_PATH,
        json={"password": _member_password(), "hours": 1},
        headers=ab_env["a"],
    )
    status = client.get(TRUST_PATH, headers=ab_env["a"]).json()
    until = datetime.fromisoformat(status["currentDevice"]["trustedUntil"])
    assert until > datetime.now(UTC)


def test_new346_revoke_and_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    client.post(
        TRUST_PATH,
        json={"password": _member_password(), "hours": 6},
        headers=ab_env["a"],
    )
    # B 没有授予（隔离）：B 的当前设备未信任。
    b_status = client.get(TRUST_PATH, headers=ab_env["b"]).json()
    assert b_status["currentDevice"]["trusted"] is False

    revoked = client.delete(TRUST_PATH, headers=ab_env["a"])
    assert revoked.status_code == 200
    status = client.get(TRUST_PATH, headers=ab_env["a"]).json()
    assert status["currentDevice"]["trusted"] is False

    missing = client.delete(TRUST_PATH, headers=ab_env["a"])
    assert missing.status_code == 404

    bad_hours = client.post(
        TRUST_PATH,
        json={"password": _member_password(), "hours": 0},
        headers=ab_env["a"],
    )
    assert bad_hours.status_code == 422
