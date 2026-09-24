"""Persistent multi-account session authentication (LUMIRSS_AUTH_MODE=session).

Covers: login/logout semantics, cookie flags, expiry, sliding renewal,
brute-force limiting, password change + global revocation, session-table
bounds, public/private path split, CSRF Origin validation, and layering
with the internal-token middleware.

0067 邀请制多账户：登录是 username + password（users.password_hash）。
本文件统一用启动迁移创建的 ``owner`` 账户：``_install_password`` 在
TestClient 启动前把哈希写进旧 ``auth_password`` 表，由 owner 迁移继承
（这正是生产旧库升级路径）。会话/密码表都在控制库（LUMIRSS_DB_PATH）。

All credentials below are dynamically generated fakes (never real
secrets), matching the suite-wide convention for credential-shaped data.
"""

import secrets as _secrets
import time

import pytest
from fastapi.testclient import TestClient

import lumirss.middleware as middleware
from lumirss.auth_store import MAX_LIVE_SESSIONS, AuthStore
from lumirss.main import app
from lumirss.storage import Database


def _fake(prefix: str) -> str:
    return prefix + _secrets.token_urlsafe(9)


PASSWORD = _fake("correct-")
NEW_PASSWORD = _fake("staple-")
WRONG_PASSWORD = _fake("wrong-")
INTERNAL_TOKEN = _fake("tok-")
DEAD_HASH = _secrets.token_hex(16)


@pytest.fixture()
def session_env(monkeypatch, tmp_path):
    """Session auth on, secure cookies off (plain HTTP test transport)."""
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    return tmp_path


def _install_password(db_path) -> None:
    import asyncio

    database = Database(db_path / "lumi.sqlite")

    async def run():
        await database.migrate()
        await AuthStore(database).set_password(PASSWORD)

    asyncio.run(run())


def _client(db_path) -> TestClient:
    return TestClient(app, base_url="http://lumirss.test")


def _login(client: TestClient, username: str = "owner", password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


@pytest.fixture()
def logged_in(session_env):
    """TestClient whose DB has the password and an active session cookie."""
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        response = _login(client)
        assert response.status_code == 200
        assert response.json()["authenticated"] is True
        yield client


# ---- login ---------------------------------------------------------------


def test_login_wrong_password_is_401(session_env):
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        response = _login(client, password=WRONG_PASSWORD)
        assert response.status_code == 401
        assert response.json()["error"]["type"] == "invalid_credentials"


def test_unbootstrapped_owner_password_rejected_without_oracle(session_env):
    """新契约语义（替代旧 503 auth_not_initialized）：owner 由启动迁移
    创建，但全新安装没有任何人知道的密码（password_updated_at 为
    NULL、哈希随机不可知）→ 登录失败，且失败形状与「密码错误」「账号
    不存在」完全一致——不泄露账号存在性。"""
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        response = _login(client, password=WRONG_PASSWORD)
        assert response.status_code == 401
        assert response.json()["error"]["type"] == "invalid_credentials"
        unknown = _login(client, username=_fake("nouser-"), password=WRONG_PASSWORD)
        assert unknown.status_code == 401
        assert unknown.json() == response.json()
        # 运维面诚实报告首次设置仍未完成。
        probe = client.get("/api/v1/auth/first-run")
        assert probe.status_code == 200
        assert probe.json()["needsSetup"] is True


def test_login_failure_rate_limit(session_env):
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        for _ in range(middleware.LOGIN_FAILURE_LIMIT):
            rejected = _login(client, password=WRONG_PASSWORD)
            assert rejected.status_code == 401
        throttled = _login(client, password=WRONG_PASSWORD)
        assert throttled.status_code == 429
        assert throttled.json()["error"]["type"] == "rate_limited"
        assert int(throttled.headers["Retry-After"]) >= 1
        # Still throttled inside the window even with the right password.
        throttled_valid = _login(client)
        assert throttled_valid.status_code == 429


def test_login_cookie_attributes_secure_mode(session_env, monkeypatch):
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "true")
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        response = _login(client)
        cookie = response.headers["Set-Cookie"]
        assert cookie.startswith("__Host-lumirss_session=")
        for attribute in ("HttpOnly", "SameSite=Strict", "Secure", "Path=/"):
            assert attribute in cookie
        assert "Domain=" not in cookie
        assert "no-store" in response.headers.get("Cache-Control", "")


def test_login_cookie_plain_name_in_dev_mode(session_env):
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        response = _login(client)
        cookie = response.headers["Set-Cookie"]
        assert cookie.startswith("lumirss_session=")
        assert "Secure" not in cookie
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie


# ---- protected surface ----------------------------------------------------


def test_api_requires_session(session_env):
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        denied = client.get("/api/v1/settings")
        assert denied.status_code == 401
        assert denied.json()["error"]["type"] == "session_required"


def test_public_paths_stay_open(session_env):
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert client.get("/health/live").status_code == 200
        assert client.get("/api/v1/version").status_code == 200
        probe = client.get("/api/v1/auth/session")
        assert probe.status_code == 200
        assert probe.json() == {"authenticated": False, "mode": "session"}


def test_session_probe_reports_basic_mode(monkeypatch, tmp_path):
    """In basic mode the probe must say so — the web app must not gate."""
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "basic")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    with _client(tmp_path) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        probe = client.get("/api/v1/auth/session")
        assert probe.status_code == 200
        assert probe.json() == {"authenticated": True, "mode": "basic"}


def test_session_grants_access(logged_in):
    assert logged_in.get("/api/v1/settings").status_code == 200


def test_garbage_cookie_rejected(session_env):
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        response = client.get(
            "/api/v1/settings",
            cookies={"lumirss_session": _fake("garbage-")},
        )
        assert response.status_code == 401


# ---- CSRF / Origin -------------------------------------------------------


def test_unsafe_cross_origin_rejected(logged_in):
    response = logged_in.post(
        "/api/v1/auth/logout", headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "csrf_rejected"


def test_same_origin_unsafe_allowed(logged_in):
    response = logged_in.post(
        "/api/v1/auth/logout", headers={"Origin": "http://lumirss.test"}
    )
    assert response.status_code == 200


def test_configured_public_origin_overrides_host(logged_in, monkeypatch):
    monkeypatch.setenv("LUMIRSS_PUBLIC_ORIGIN", "https://rss.example.net")
    good = logged_in.post(
        "/api/v1/auth/logout", headers={"Origin": "https://rss.example.net"}
    )
    assert good.status_code == 200
    bad = logged_in.post(
        "/api/v1/auth/logout", headers={"Origin": "https://evil.example"}
    )
    assert bad.status_code == 403


def test_get_needs_no_origin(logged_in):
    assert logged_in.get("/api/v1/settings").status_code == 200


# ---- logout / revocation --------------------------------------------------


def test_logout_revokes_session(logged_in):
    response = logged_in.post(
        "/api/v1/auth/logout", headers={"Origin": "http://lumirss.test"}
    )
    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["Set-Cookie"]
    assert logged_in.get("/api/v1/settings").status_code == 401


def test_password_change_revokes_other_sessions(session_env):
    _install_password(session_env)
    with _client(session_env) as attacker:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(attacker).status_code == 200
    with _client(session_env) as owner:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(owner).status_code == 200
        changed = owner.post(
            "/api/v1/auth/password",
            json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
            headers={"Origin": "http://lumirss.test"},
        )
        assert changed.status_code == 200
        # This device keeps working via the fresh session cookie.
        assert owner.get("/api/v1/settings").status_code == 200
    # The OTHER device's session died with the password change.
    assert attacker.get("/api/v1/settings").status_code == 401
    # The old password no longer authenticates.
    with _client(session_env) as fresh:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(fresh, password=PASSWORD).status_code == 401
        assert _login(fresh, password=NEW_PASSWORD).status_code == 200


def test_password_change_wrong_current_password(logged_in):
    response = logged_in.post(
        "/api/v1/auth/password",
        json={"currentPassword": WRONG_PASSWORD, "newPassword": NEW_PASSWORD},
        headers={"Origin": "http://lumirss.test"},
    )
    assert response.status_code == 401
    assert logged_in.get("/api/v1/settings").status_code == 200


def test_weak_new_password_rejected(logged_in):
    response = logged_in.post(
        "/api/v1/auth/password",
        json={"currentPassword": PASSWORD, "newPassword": "x" * 4},
        headers={"Origin": "http://lumirss.test"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "weak_password"


def test_logout_all_kills_every_device(session_env):
    _install_password(session_env)
    with _client(session_env) as second:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(second).status_code == 200
    with _client(session_env) as first:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(first).status_code == 200
        response = first.post(
            "/api/v1/auth/logout-all", headers={"Origin": "http://lumirss.test"}
        )
        assert response.status_code == 200
    assert first.get("/api/v1/settings").status_code == 401
    assert second.get("/api/v1/settings").status_code == 401


# ---- expiry / renewal -----------------------------------------------------


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_expired_session_rejected(session_env):
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(client).status_code == 200

        async def expire():
            db = Database(session_env / "lumi.sqlite")
            await db.migrate()
            await db.execute(
                "UPDATE auth_sessions SET expires_at = ?", (int(time.time()) - 10,)
            )

        _run(expire())
        assert client.get("/api/v1/settings").status_code == 401


def test_sliding_renewal_extends_near_expiry(session_env, monkeypatch):
    monkeypatch.setenv("LUMIRSS_SESSION_MAX_AGE_DAYS", "30")
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(client).status_code == 200

        async def force_near_expiry():
            db = Database(session_env / "lumi.sqlite")
            await db.migrate()
            await db.execute(
                "UPDATE auth_sessions SET expires_at = ?",
                (int(time.time()) + 20 * 86400,),
            )

        _run(force_near_expiry())
        before = client.get("/api/v1/auth/session").json()["expiresAt"]
        assert before is not None
        # Any authenticated request renews (30-day window, 20 days left).
        assert client.get("/api/v1/settings").status_code == 200
        after = client.get("/api/v1/auth/session").json()["expiresAt"]
        assert after > before


def test_fresh_session_not_rewritten(session_env):
    """Far from expiry: touch must NOT move expires_at (throttled writes)."""
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(client).status_code == 200
        before = client.get("/api/v1/auth/session").json()["expiresAt"]
        assert client.get("/api/v1/settings").status_code == 200
        after = client.get("/api/v1/auth/session").json()["expiresAt"]
        assert before == after


def test_expired_rows_pruned_on_login(session_env):
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(client).status_code == 200

        async def plant_expired():
            db = Database(session_env / "lumi.sqlite")
            await db.migrate()
            await db.execute(
                "INSERT INTO auth_sessions (token_hash, created_at, last_seen_at, expires_at) VALUES (?, 0, 0, 1)",
                (DEAD_HASH,),
            )

        _run(plant_expired())
        assert _login(client).status_code == 200

        async def count_expired():
            db = Database(session_env / "lumi.sqlite")
            await db.migrate()
            return await db.fetch_one(
                "SELECT COUNT(*) AS n FROM auth_sessions WHERE token_hash = ?",
                (DEAD_HASH,),
            )

        row = _run(count_expired())
        assert row["n"] == 0


def test_live_session_cap(session_env):
    """Runaway login loops cannot grow the table past MAX_LIVE_SESSIONS."""

    async def many_sessions():
        database = Database(session_env / "lumi.sqlite")
        await database.migrate()
        store = AuthStore(database)
        for _ in range(MAX_LIVE_SESSIONS + 7):
            await store.create_session(30)
        return await database.fetch_one(
            "SELECT COUNT(*) AS n FROM auth_sessions"
        )

    row = _run(many_sessions())
    assert row["n"] <= MAX_LIVE_SESSIONS


# ---- layering with the internal token --------------------------------------


def test_internal_token_still_required_in_session_mode(session_env, monkeypatch):
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", INTERNAL_TOKEN)
    _install_password(session_env)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        # Session layer passes (public), but the token layer still rejects.
        no_token = _login(client)
        assert no_token.status_code == 401
        with_token = client.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": PASSWORD},
            headers={"X-Lumi-Token": INTERNAL_TOKEN},
        )
        assert with_token.status_code == 200
        # A valid session alone cannot bypass the token layer.
        assert client.get("/api/v1/settings").status_code == 401


def test_basic_mode_is_default_and_unchanged(monkeypatch, tmp_path):
    """Without LUMIRSS_AUTH_MODE=session the API behaves exactly as before."""
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "basic")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    with _client(tmp_path) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        assert client.get("/api/v1/settings").status_code == 200


# ---- 0067 auth edges: user-id validation, legacy hashes, byte ceiling -------
#
# The rules under test live in user_scope.validate_user_id (format =
# alphanumeric only — separators, dots, whitespace and traversal can never
# select a database file — and length ≤ 40) and in accounts_store's
# bcrypt ceiling (this build of the library RAISES beyond 72 BYTES, so
# over-long passwords are rejected at the boundary with a stable 400 and
# can never turn a login into a 500).


def test_validate_user_id_accepts_server_shaped_ids():
    from lumirss.user_scope import validate_user_id

    assert validate_user_id("u1") == "u1"
    assert validate_user_id("u" + "0f" * 8) == "u" + "0f" * 8  # 17 chars
    assert validate_user_id("a" * 40) == "a" * 40  # exactly the cap


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty
        "../etc/passwd",  # traversal
        "..%2Fowner",  # encoded traversal
        "u1/u2",  # path separator
        "u1\\u2",  # windows separator
        "u-1",  # separator character
        "u_1",  # separator character
        "..hidden",  # dot prefix
        "u1 x",  # whitespace
        "u1;x",  # shell-ish punctuation
        "u1\n",  # control character
        "a" * 41,  # over the length cap
    ],
)
def test_validate_user_id_rejects_garbage(bad):
    from lumirss.user_scope import NoUserContextError, validate_user_id

    with pytest.raises(NoUserContextError):
        validate_user_id(bad)


def test_bind_user_context_rejects_forged_id():
    from lumirss.user_scope import NoUserContextError, bind_user_context

    with pytest.raises(NoUserContextError):
        bind_user_context("../../etc/passwd")


def test_forged_user_id_in_admin_path_is_404(logged_in):
    """A garbage path-param id never selects a database file: ids that
    reach the handler get the stable 404 user_not_found envelope, and
    slash-encoded traversal never even matches a route (Starlette 404)."""
    for garbage in ("..%2F..%2Fetc%2Fpasswd", "uDEADBEEF-...--", "a" * 41):
        response = logged_in.post(f"/api/v1/admin/users/{garbage}/pause")
        assert response.status_code == 404, garbage
    for garbage in ("uDEADBEEF-...--", "a" * 41):  # route-matched → handler envelope
        response = logged_in.post(f"/api/v1/admin/users/{garbage}/pause")
        assert response.json()["error"]["type"] == "user_not_found", garbage
    role = logged_in.post(
        "/api/v1/admin/users/..%2F..%2Fetc%2Fpasswd/role", json={"role": "member"}
    )
    assert role.status_code == 404


def _create_member(db_path, username: str, password: str | None, *, precomputed_hash: str | None = None) -> None:
    import asyncio

    from lumirss.accounts_store import AccountsStore, hash_password

    async def run():
        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        store = AccountsStore(database)
        await store.create_user(
            username=username,
            password_hash=precomputed_hash or hash_password(password),
            role="member",
        )

    asyncio.run(run())


def test_legacy_bcrypt_hash_login(session_env):
    """A row hashed by the legacy path (plain bcrypt, any cost) must keep
    authenticating — the control store never re-hashes logins."""
    import bcrypt as _bcrypt

    legacy_password = "legacy-" + _secrets.token_urlsafe(6)
    legacy_hash = _bcrypt.hashpw(
        legacy_password.encode("utf-8"), _bcrypt.gensalt(rounds=4)
    ).decode("utf-8")
    _create_member(session_env, "oldmember", None, precomputed_hash=legacy_hash)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        ok = _login(client, username="oldmember", password=legacy_password)
        assert ok.status_code == 200, ok.text
        assert ok.json()["authenticated"] is True
        # …and the wrong password against that same legacy row is 401.
        bad = _login(client, username="oldmember", password=WRONG_PASSWORD)
        assert bad.status_code == 401


def test_long_password_rejected_at_boundary_login_never_500s(session_env):
    """bcrypt (this build) refuses > 72 BYTES: setting such a password is
    a stable 400, and attempting to log in with one fails closed with 401
    (constant-shape dummy check) — never a 500 from the hash library."""
    long_password = "N" * 100  # 100 ASCII chars = 100 bytes > 72
    # Store level: the documented actual behavior is a rejection.
    from lumirss.accounts_store import WeakPassword, hash_password, verify_password_hash

    with pytest.raises(WeakPassword):
        hash_password(long_password)
    assert verify_password_hash(long_password, None) is False
    # HTTP level: set is rejected at the boundary; login is 401.
    base_password = "start-" + _secrets.token_urlsafe(6)
    _create_member(session_env, "polylong", base_password)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(client, username="polylong", password=base_password).status_code == 200
        changed = client.post(
            "/api/v1/auth/password",
            json={"currentPassword": base_password, "newPassword": long_password},
        )
        assert changed.status_code == 400
        assert changed.json()["error"]["type"] == "weak_password"
        overlong = _login(client, username="polylong", password=long_password)
        assert overlong.status_code == 401
        assert overlong.json()["error"]["type"] == "invalid_credentials"


def test_unicode_password_roundtrip_and_wrong_password_401(session_env):
    """CJK/emoji passwords (multi-byte, under the byte ceiling) hash and
    verify consistently: set → login round-trips; wrong password 401s."""
    unicode_password = "量子猫密码🚀测试"  # 8 chars, 25 UTF-8 bytes
    assert len(unicode_password.encode("utf-8")) <= 72
    _create_member(session_env, "polyglot", unicode_password)
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        ok = _login(client, username="polyglot", password=unicode_password)
        assert ok.status_code == 200, ok.text
        # Re-set the SAME unicode password through the change endpoint and
        # log back in — bytes in, bytes out, no silent mutation.
        changed = client.post(
            "/api/v1/auth/password",
            json={"currentPassword": unicode_password, "newPassword": unicode_password + "二"},
        )
        assert changed.status_code == 200, changed.text
        fresh = client.post(
            "/api/v1/auth/login",
            json={"username": "polyglot", "password": unicode_password + "二"},
        )
        assert fresh.status_code == 200
        # The old password no longer works.
        assert _login(client, username="polyglot", password=unicode_password).status_code == 401
        # And plain wrong passwords stay 401 after all of the above.
        assert _login(client, username="polyglot", password=WRONG_PASSWORD).status_code == 401
