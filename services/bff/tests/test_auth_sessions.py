"""Persistent single-user session authentication (LUMIRSS_AUTH_MODE=session).

Covers: login/logout semantics, cookie flags, expiry, sliding renewal,
brute-force limiting, password change + global revocation, session-table
bounds, public/private path split, CSRF Origin validation, and layering
with the internal-token middleware.

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


def _login(client: TestClient, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"password": password})


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


def test_login_without_bootstrap_is_503(session_env):
    with _client(session_env) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        response = _login(client)
        assert response.status_code == 503
        assert response.json()["error"]["type"] == "auth_not_initialized"


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
        no_token = client.post("/api/v1/auth/login", json={"password": PASSWORD})
        assert no_token.status_code == 401
        with_token = client.post(
            "/api/v1/auth/login",
            json={"password": PASSWORD},
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
