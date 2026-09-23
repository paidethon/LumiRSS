"""Admin lifecycle guards + owner-only role provisioning (0067).

Covers the two hard pause guards (O152) against the REAL store method
(``count_active_admins``) and the new ``POST /admin/users/{id}/role``
surface:

- pausing the last active admin is a stable 403 and does NOT pause them;
- pausing one of two active admins succeeds;
- the owner is untargetable (pause / resume / role change);
- only the owner can grant/revoke the admin role (admins and members
  get 403 — an admin can never mint another admin);
- the last active admin cannot be demoted; owner cannot be re-roled;
- unknown user → 404, unknown role → 422; changes are audited.

Promotion for the pause-guard setups goes through the control-plane
store directly (``set_user_role``) so the guard tests do not depend on
the HTTP role endpoint; the endpoint itself is exercised separately.
"""

import asyncio
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app

PASSWORD = "role-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"
B_USER = "bob"


@pytest.fixture()
def role_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(tmp_path)
        owner_login = client.post(
            "/api/v1/auth/login",
            json={"username": OWNER_USER, "password": PASSWORD},
        )
        assert owner_login.status_code == 200, owner_login.text
        owner_headers = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        created = {}
        for username in (A_USER, B_USER):
            invite = client.post(
                "/api/v1/admin/invites",
                json={"label": username},
                headers=owner_headers,
            )
            assert invite.status_code == 200, invite.text
            activation = client.post(
                "/api/v1/auth/activate",
                json={
                    "token": invite.json()["token"],
                    "username": username,
                    "password": PASSWORD,
                },
            )
            assert activation.status_code == 200, activation.text
            created[username] = {"cookie": activation.headers["set-cookie"].split(";")[0]}
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        ids = {row["username"]: row["id"] for row in users}
        yield {
            "client": client,
            "owner": owner_headers,
            **created,
            "ids": ids,
            "owner_id": ids[OWNER_USER],
            "db_path": tmp_path,
        }


def _set_owner_password(db_path) -> None:
    async def run():
        from lumirss.storage import Database

        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(PASSWORD))
                return
        raise AssertionError("owner migration did not run")

    asyncio.run(run())


def _set_role_direct(env, username: str, role: str) -> None:
    """Promote/demote through the control-plane store (setup helper)."""

    async def run():
        from lumirss.storage import Database

        database = Database(env["db_path"] / "lumi.sqlite")
        await database.migrate()
        changed = await AccountsStore(database).set_user_role(env["ids"][username], role)
        assert changed, f"role setup failed for {username}"

    asyncio.run(run())


def _post(env, who: str, path: str, json_body=None):
    return env["client"].post(path, json=json_body, headers={"cookie": env[who]["cookie"]})


def _users(env):
    response = env["client"].get("/api/v1/admin/users", headers=env["owner"])
    assert response.status_code == 200
    return {row["username"]: row for row in response.json()}


# ---- fix 1: the last-active-admin pause guard ------------------------------


def test_pause_last_active_admin_is_403_and_not_paused(role_env):
    env = role_env
    _set_role_direct(env, A_USER, "admin")
    paused = _post(env, "owner", f"/api/v1/admin/users/{env['ids'][A_USER]}/pause")
    assert paused.status_code == 403, paused.text
    assert paused.json()["error"]["type"] == "forbidden"
    assert "last active administrator" in paused.json()["error"]["message"]
    row = _users(env)[A_USER]
    assert row["status"] == "active", "the guard must not pause the admin"
    # The admin's own session keeps working (not revoked by a failed pause).
    assert (
        env["client"]
        .get("/api/v1/search/views", headers={"cookie": env[A_USER]["cookie"]})
        .status_code
        == 200
    )


def test_pause_one_of_two_admins_succeeds(role_env):
    env = role_env
    _set_role_direct(env, A_USER, "admin")
    _set_role_direct(env, B_USER, "admin")
    paused = _post(env, "owner", f"/api/v1/admin/users/{env['ids'][A_USER]}/pause")
    assert paused.status_code == 200, paused.text
    rows = _users(env)
    assert rows[A_USER]["status"] == "paused"
    assert rows[B_USER]["status"] == "active"


def test_owner_untargetable_by_pause_resume_and_role(role_env):
    env = role_env
    owner_id = env["owner_id"]
    for path, body in (
        (f"/api/v1/admin/users/{owner_id}/pause", None),
        (f"/api/v1/admin/users/{owner_id}/resume", None),
        (f"/api/v1/admin/users/{owner_id}/role", {"role": "member"}),
        (f"/api/v1/admin/users/{owner_id}/role", {"role": "admin"}),
    ):
        response = _post(env, "owner", path, body)
        assert response.status_code == 403, f"{path} → {response.status_code}"
        assert response.json()["error"]["type"] == "forbidden"
    rows = _users(env)
    assert rows[OWNER_USER]["role"] == "owner"
    assert rows[OWNER_USER]["status"] == "active"


# ---- fix 2: owner-only role provisioning -----------------------------------


def test_role_endpoint_is_owner_only(role_env):
    env = role_env
    _set_role_direct(env, B_USER, "admin")
    # A member cannot mint an admin.
    member_try = _post(
        env, A_USER, f"/api/v1/admin/users/{env['ids'][B_USER]}/role", {"role": "admin"}
    )
    assert member_try.status_code == 403
    # An admin cannot change roles either (not even another admin's).
    admin_try = _post(
        env, B_USER, f"/api/v1/admin/users/{env['ids'][A_USER]}/role", {"role": "admin"}
    )
    assert admin_try.status_code == 403
    assert _users(env)[A_USER]["role"] == "member"


def test_owner_grants_and_revokes_admin_with_last_admin_guard(role_env):
    env = role_env
    granted = _post(
        env, "owner", f"/api/v1/admin/users/{env['ids'][A_USER]}/role", {"role": "admin"}
    )
    assert granted.status_code == 200, granted.text
    assert granted.json() == {"id": env["ids"][A_USER], "role": "admin"}
    # The live session picks the new role up immediately (server-derived).
    probe = env["client"].get(
        "/api/v1/auth/session", headers={"cookie": env[A_USER]["cookie"]}
    )
    assert probe.json()["role"] == "admin"
    # Demoting the last active admin is refused.
    demote_last = _post(
        env, "owner", f"/api/v1/admin/users/{env['ids'][A_USER]}/role", {"role": "member"}
    )
    assert demote_last.status_code == 403
    assert "last active administrator" in demote_last.json()["error"]["message"]
    # With a second active admin the demotion goes through.
    second = _post(
        env, "owner", f"/api/v1/admin/users/{env['ids'][B_USER]}/role", {"role": "admin"}
    )
    assert second.status_code == 200
    demoted = _post(
        env, "owner", f"/api/v1/admin/users/{env['ids'][A_USER]}/role", {"role": "member"}
    )
    assert demoted.status_code == 200
    assert _users(env)[A_USER]["role"] == "member"
    probe = env["client"].get(
        "/api/v1/auth/session", headers={"cookie": env[A_USER]["cookie"]}
    )
    assert probe.json()["role"] == "member"
    # Every accepted change is audited (no credentials in the trail).
    audit = env["client"].get("/api/v1/admin/audit", headers=env["owner"]).json()
    actions = [row["action"] for row in audit]
    assert actions.count("user_role_change") == 3
    assert all("password" not in str(row.get("detail", "")).lower() for row in audit)


def test_role_unknown_user_404_and_unknown_role_422(role_env):
    env = role_env
    missing = _post(
        env, "owner", "/api/v1/admin/users/udeadbeefdeadbeef/role", {"role": "admin"}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "user_not_found"
    bad_role = _post(
        env, "owner", f"/api/v1/admin/users/{env['ids'][A_USER]}/role", {"role": "superadmin"}
    )
    assert bad_role.status_code == 422
    owner_role = _post(
        env, "owner", f"/api/v1/admin/users/{env['ids'][A_USER]}/role", {"role": "owner"}
    )
    assert owner_role.status_code == 422
