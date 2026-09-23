"""两步验证（TOTP）— N007。

覆盖：setup（秘密/URI 只出现一次）、enable（验证码 + 一次性恢复码）、
两步登录（totpRequired + pendingToken → verify 换发真会话）、重放拒绝
（同一 30 秒片二次使用）、恢复码单次燃烧、过期 pending token、单次
pending token、disable 服务端强制（密码 + 验证码）、密码修改/通行密钥
删除的敏感操作二次验证、共享登录限流。验证码用 pyotp 在固定时刻生成
（autouse fixture 把 lumirss.totp._now 钉在测试起点）。
"""

import asyncio
import secrets as _secrets
import time

import pytest
from fastapi.testclient import TestClient

import lumirss.middleware as middleware
import lumirss.totp as totp_core
from _virtual_authenticator import totp_at
from lumirss.main import app
from lumirss.storage import Database

PASSWORD = _secrets.token_urlsafe(12)
T0 = 0  # set by the fixed_clock fixture (module clock, single source)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    """Pin lumirss.totp._now at test start so codes are computed at a
    deterministic instant (pyotp .at(T) on both sides)."""
    global T0  # noqa: PLW0603 — test-local clock anchor
    T0 = int(time.time())
    monkeypatch.setattr(totp_core, "_now", lambda: T0)
    yield T0


@pytest.fixture()
def session_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    return tmp_path


def _install_password(db_path) -> None:
    from lumirss.auth_store import AuthStore

    database = Database(db_path / "lumi.sqlite")

    async def run():
        await database.migrate()
        await AuthStore(database).set_password(PASSWORD)

    asyncio.run(run())


@pytest.fixture()
def logged_in(session_env):
    _install_password(session_env)
    with TestClient(app, base_url="http://lumirss.test") as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        response = client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        yield client


def _wrong_code(secret: str, at: int) -> str:
    expected = totp_at(secret, at)
    return str((int(expected) + 1) % 1_000_000).zfill(6)


def enable_totp(client: TestClient, *, at: int) -> tuple[str, list[str]]:
    setup = client.post("/api/v1/auth/totp/setup", json={})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    enabled = client.post(
        "/api/v1/auth/totp/enable", json={"code": totp_at(secret, at)}
    )
    assert enabled.status_code == 200, enabled.text
    return secret, enabled.json()["recoveryCodes"]


def two_step_login(client: TestClient):
    """Password step → (pendingToken or None, response)."""
    response = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
    )
    return response


# ---- setup / enable ---------------------------------------------------------


def test_setup_returns_uri_and_secret(logged_in):
    setup = logged_in.post("/api/v1/auth/totp/setup", json={})
    assert setup.status_code == 200
    body = setup.json()
    assert len(body["secret"]) >= 16
    assert body["otpauthUri"].startswith("otpauth://totp/")
    assert "issuer=LumiRSS" in body["otpauthUri"]
    status = logged_in.get("/api/v1/auth/totp").json()
    assert status == {"enabled": False, "recoveryCodesRemaining": 0}


def test_enable_requires_setup(logged_in):
    rejected = logged_in.post("/api/v1/auth/totp/enable", json={"code": "123456"})
    assert rejected.status_code == 400
    assert rejected.json()["error"]["type"] == "totp_not_setup"


def test_enable_rejects_setup_while_enabled(logged_in):
    enable_totp(logged_in, at=fixed_clock_t0())
    again = logged_in.post("/api/v1/auth/totp/setup", json={})
    assert again.status_code == 400
    assert again.json()["error"]["type"] == "totp_enabled"


def fixed_clock_t0() -> int:
    """The pinned clock anchor; ceremonies use T0 (enable) and T0+30
    (later ones) so login codes never collide with the enable slice."""
    return T0


def test_enable_wrong_code_rejected(logged_in):
    secret = logged_in.post("/api/v1/auth/totp/setup", json={}).json()["secret"]
    bad = logged_in.post(
        "/api/v1/auth/totp/enable", json={"code": _wrong_code(secret, fixed_clock_t0())}
    )
    assert bad.status_code == 401
    assert bad.json()["error"]["type"] == "totp_code_invalid"
    status = logged_in.get("/api/v1/auth/totp").json()
    assert status["enabled"] is False


def test_enable_returns_eight_recovery_codes_once(logged_in):
    _secret, codes = enable_totp(logged_in, at=fixed_clock_t0())
    assert len(codes) == 8
    assert len(set(codes)) == 8
    # 明文只在 enable 响应中出现：状态面只剩计数。
    status = logged_in.get("/api/v1/auth/totp").json()
    assert status == {"enabled": True, "recoveryCodesRemaining": 8}
    for code in codes:  # 存储的是盐化哈希
        assert code not in str(status)


# ---- 两步登录 -----------------------------------------------------------------


def test_login_requires_second_step_then_mints_session(logged_in):
    secret, _codes = enable_totp(logged_in, at=fixed_clock_t0())
    first = two_step_login(logged_in)
    assert first.status_code == 200
    body = first.json()
    assert body["totpRequired"] is True
    assert body.get("authenticated") is None  # 不是会话
    pending_token = body["pendingToken"]
    # 错误验证码 → 401，pending token 已被烧掉（一码一试）。
    wrong = logged_in.post(
        "/api/v1/auth/totp/verify",
        json={"pendingToken": pending_token, "code": _wrong_code(secret, fixed_clock_t0() + 30)},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["type"] == "totp_code_invalid"
    retry_same_token = logged_in.post(
        "/api/v1/auth/totp/verify",
        json={"pendingToken": pending_token, "code": totp_at(secret, fixed_clock_t0() + 30)},
    )
    assert retry_same_token.status_code == 401
    assert retry_same_token.json()["error"]["type"] == "pending_token_invalid"
    # 新 pending token + 正确验证码（下一时间片，避开 enable 消耗的片）→ 真会话。
    second = two_step_login(logged_in)
    token2 = second.json()["pendingToken"]
    ok = logged_in.post(
        "/api/v1/auth/totp/verify",
        json={"pendingToken": token2, "code": totp_at(secret, fixed_clock_t0() + 30)},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["authenticated"] is True
    assert "Set-Cookie" in ok.headers
    assert logged_in.get("/api/v1/settings").status_code == 200


def test_login_without_totp_stays_single_step(logged_in):
    response = two_step_login(logged_in)
    assert response.status_code == 200
    assert response.json()["authenticated"] is True


def test_verify_replayed_code_rejected(logged_in):
    secret, _codes = enable_totp(logged_in, at=fixed_clock_t0())
    at = fixed_clock_t0() + 30
    token1 = two_step_login(logged_in).json()["pendingToken"]
    ok = logged_in.post(
        "/api/v1/auth/totp/verify", json={"pendingToken": token1, "code": totp_at(secret, at)}
    )
    assert ok.status_code == 200
    # 同一枚验证码（同一 30 秒片）第二次使用 → 重放拒绝。
    token2 = two_step_login(logged_in).json()["pendingToken"]
    replay = logged_in.post(
        "/api/v1/auth/totp/verify", json={"pendingToken": token2, "code": totp_at(secret, at)}
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["type"] == "totp_code_invalid"


def test_verify_expired_pending_token_rejected(logged_in):
    secret, _codes = enable_totp(logged_in, at=fixed_clock_t0())
    token = two_step_login(logged_in).json()["pendingToken"]
    database = Database(logged_in.app.state.control_db.path)

    async def expire():
        await database.migrate()
        await database.execute("UPDATE totp_pending_logins SET expires_at = 1", ())

    asyncio.run(expire())
    expired = logged_in.post(
        "/api/v1/auth/totp/verify",
        json={"pendingToken": token, "code": totp_at(secret, fixed_clock_t0() + 30)},
    )
    assert expired.status_code == 401
    assert expired.json()["error"]["type"] == "pending_token_invalid"


def test_recovery_code_logs_in_once(logged_in):
    _secret, codes = enable_totp(logged_in, at=fixed_clock_t0())
    token1 = two_step_login(logged_in).json()["pendingToken"]
    ok = logged_in.post(
        "/api/v1/auth/totp/verify", json={"pendingToken": token1, "code": codes[0]}
    )
    assert ok.status_code == 200, ok.text
    assert logged_in.get("/api/v1/settings").status_code == 200
    # 单次燃烧：同一恢复码（以及其余流程）第二次使用失败。
    token2 = two_step_login(logged_in).json()["pendingToken"]
    burnt = logged_in.post(
        "/api/v1/auth/totp/verify", json={"pendingToken": token2, "code": codes[0]}
    )
    assert burnt.status_code == 401
    status = logged_in.get("/api/v1/auth/totp").json()
    assert status["recoveryCodesRemaining"] == 7


# ---- disable（服务端强制）------------------------------------------------------


def test_disable_requires_password_and_code(logged_in):
    secret, _codes = enable_totp(logged_in, at=fixed_clock_t0())
    code = totp_at(secret, fixed_clock_t0() + 30)
    wrong_password = logged_in.post(
        "/api/v1/auth/totp/disable",
        json={"code": code, "currentPassword": _secrets.token_urlsafe(9)},
    )
    assert wrong_password.status_code == 401
    wrong_code = logged_in.post(
        "/api/v1/auth/totp/disable",
        json={"code": _wrong_code(secret, fixed_clock_t0() + 30), "currentPassword": PASSWORD},
    )
    assert wrong_code.status_code == 401
    missing = logged_in.get("/api/v1/auth/totp").json()
    assert missing["enabled"] is True  # 前两问都没关掉
    disabled = logged_in.post(
        "/api/v1/auth/totp/disable", json={"code": code, "currentPassword": PASSWORD}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json() == {"disabled": True}
    assert logged_in.get("/api/v1/auth/totp").json()["enabled"] is False
    # 密码登录回到单步；秘密已删，setup 可以重新开始。
    fresh = two_step_login(logged_in)
    assert fresh.json().get("authenticated") is True
    re_setup = logged_in.post("/api/v1/auth/totp/setup", json={})
    assert re_setup.status_code == 200


def test_disable_missing_code_rejected(logged_in):
    enable_totp(logged_in, at=fixed_clock_t0())
    response = logged_in.post(
        "/api/v1/auth/totp/disable",
        json={"code": "", "currentPassword": PASSWORD},
    )
    assert response.status_code == 422  # 契约要求 code 字段


def test_disable_with_recovery_code(logged_in):
    _secret, codes = enable_totp(logged_in, at=fixed_clock_t0())
    disabled = logged_in.post(
        "/api/v1/auth/totp/disable", json={"code": codes[1], "currentPassword": PASSWORD}
    )
    assert disabled.status_code == 200
    assert logged_in.get("/api/v1/auth/totp").json()["enabled"] is False


# ---- 敏感操作二次验证（密码修改 / 通行密钥删除）-----------------------------------


def test_password_change_requires_totp_when_enabled(logged_in):
    secret, _codes = enable_totp(logged_in, at=fixed_clock_t0())
    new_password = _secrets.token_urlsafe(12)
    missing = logged_in.post(
        "/api/v1/auth/password",
        json={"currentPassword": PASSWORD, "newPassword": new_password},
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["type"] == "totp_code_required"
    wrong = logged_in.post(
        "/api/v1/auth/password",
        json={
            "currentPassword": PASSWORD,
            "newPassword": new_password,
            "totpCode": _wrong_code(secret, fixed_clock_t0() + 30),
        },
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["type"] == "totp_code_invalid"
    ok = logged_in.post(
        "/api/v1/auth/password",
        json={
            "currentPassword": PASSWORD,
            "newPassword": new_password,
            "totpCode": totp_at(secret, fixed_clock_t0() + 30),
        },
    )
    assert ok.status_code == 200, ok.text
    # 本设备会话仍有效；新密码登录仍走两步（全新客户端，旧 Cookie 无关）。
    assert logged_in.get("/api/v1/settings").status_code == 200
    with TestClient(app, base_url="http://lumirss.test") as fresh:
        app.state.db = Database(logged_in.app.state.control_db.path)
        two_step = fresh.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": new_password},
        )
        assert two_step.status_code == 200
        assert two_step.json().get("totpRequired") is True


def test_passkey_delete_requires_totp_when_enabled(logged_in):
    import test_webauthn_passkeys as passkey_tests

    secret, _codes = enable_totp(logged_in, at=fixed_clock_t0())
    row, _auth = passkey_tests.register_passkey(logged_in)
    missing = logged_in.request(
        "DELETE",
        f"/api/v1/auth/passkeys/{row['id']}",
        json={"currentPassword": PASSWORD},
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["type"] == "totp_code_required"
    wrong = logged_in.request(
        "DELETE",
        f"/api/v1/auth/passkeys/{row['id']}",
        json={
            "currentPassword": PASSWORD,
            "totpCode": _wrong_code(secret, fixed_clock_t0() + 30),
        },
    )
    assert wrong.status_code == 401
    ok = logged_in.request(
        "DELETE",
        f"/api/v1/auth/passkeys/{row['id']}",
        json={
            "currentPassword": PASSWORD,
            "totpCode": totp_at(secret, fixed_clock_t0() + 30),
        },
    )
    assert ok.status_code == 204


# ---- 限流共享 -----------------------------------------------------------------


def test_totp_verify_shares_login_rate_budget(logged_in):
    secret, _codes = enable_totp(logged_in, at=fixed_clock_t0())
    # Pre-mint tokens while the budget is clean: the password step does
    # NOT reset the budget (only a minted session does).
    tokens = [
        two_step_login(logged_in).json()["pendingToken"]
        for _ in range(middleware.LOGIN_FAILURE_LIMIT + 1)
    ]
    for token in tokens[:-1]:
        failed = logged_in.post(
            "/api/v1/auth/totp/verify",
            json={
                "pendingToken": token,
                "code": _wrong_code(secret, fixed_clock_t0() + 30),
            },
        )
        assert failed.status_code == 401
    throttled = logged_in.post(
        "/api/v1/auth/totp/verify",
        json={
            "pendingToken": tokens[-1],
            "code": totp_at(secret, fixed_clock_t0() + 30),
        },
    )
    assert throttled.status_code == 429
    assert throttled.json()["error"]["type"] == "rate_limited"
