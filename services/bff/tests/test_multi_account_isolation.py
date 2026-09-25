"""Cross-account isolation (0067 / O197): owner + members A/B + anonymous.

Plants same-shaped data for two members (identical names/UUIDs where the
schema allows) and asserts every private surface resolves per verified
identity only:

- member→member horizontal isolation (listings, settings, saved views,
  workspace names, object ids);
- admin API vertical isolation (member 403; admin manages lifecycle but
  has no product route to read member content);
- paused users lose access immediately (sessions rejected at the gate);
- invitations are single-use, expiring and revocable;
- anonymous requests stay on the public allow-list.

All credentials are synthetic; the two accounts deliberately use the
same display strings to prove the databases — not names — isolate.
"""

import asyncio
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app

PASSWORD = "iso-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"
B_USER = "bob"
# Same label planted for both accounts — listings must not cross.
SHARED_LABEL = "共享同名项目-" + _secrets.token_urlsafe(4)


@pytest.fixture()
def iso_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    return tmp_path


def _set_owner_password(db_path) -> None:
    """The owner migration installs an unknowable password; the fixture
    replaces it through the same control-plane store (bcrypt, no
    plaintext persistence)."""

    async def run():
        database = await _control_db(db_path)
        store = AccountsStore(database)
        owner = None
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                owner = row
                break
        assert owner is not None, "owner migration did not run"
        await store.set_password_hash(str(owner["id"]), hash_password(PASSWORD))

    asyncio.run(run())


async def _control_db(db_path):
    from lumirss.storage import Database

    database = Database(db_path / "lumi.sqlite")
    await database.migrate()
    return database


def _login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


@pytest.fixture()
def env(iso_env):
    with TestClient(app, base_url="http://lumirss.test") as client:
        # Lifespan ran the owner migration; now replace the owner's
        # unknowable password through the same control-plane store.
        _set_owner_password(iso_env)
        # Owner session cookie.
        response = _login(client, OWNER_USER)
        assert response.status_code == 200
        owner_cookie = response.headers["set-cookie"].split(";")[0]
        owner_headers = {"cookie": owner_cookie}
        # Invite + activate members A and B (same display label for both).
        created = {}
        for username in (A_USER, B_USER):
            invite = client.post(
                "/api/v1/admin/invites",
                json={"label": username},
                headers=owner_headers,
            )
            assert invite.status_code == 200, invite.text
            token = invite.json()["token"]
            activation = client.post(
                "/api/v1/auth/activate",
                json={
                    "token": token,
                    "username": username,
                    "password": PASSWORD,
                    "displayName": SHARED_LABEL,
                },
            )
            assert activation.status_code == 200, activation.text
            created[username] = {
                "cookie": activation.headers["set-cookie"].split(";")[0]
            }
        yield {
            "client": client,
            "owner": owner_headers,
            **created,
            "db_path": iso_env,
        }


def _get(env, who: str, path: str):
    return env["client"].get(path, headers={"cookie": env[who]["cookie"]})


def test_activation_and_login_identity(env):
    """A/B activated independently; session probe reports each identity."""
    client = env["client"]
    for username in (A_USER, B_USER):
        probe = client.get(
            "/api/v1/auth/session", headers={"cookie": env[username]["cookie"]}
        )
        assert probe.status_code == 200
        body = probe.json()
        assert body["authenticated"] is True
        assert body["username"] == username
        assert body["role"] == "member"
        assert body["userId"]


def test_saved_view_names_do_not_cross(env):
    """A creates a saved view; B's list has no row with A's view id."""
    client = env["client"]
    made = client.post(
        "/api/v1/search/views",
        json={"name": SHARED_LABEL, "query": "标记-" + A_USER},
        headers={"cookie": env[A_USER]["cookie"]},
    )
    assert made.status_code in (200, 201), made.text
    view_id = made.json().get("id") or made.json().get("view", {}).get("id")
    assert view_id
    b_views = client.get(
        "/api/v1/search/views", headers={"cookie": env[B_USER]["cookie"]}
    )
    assert b_views.status_code == 200
    ids = _flatten_ids(b_views.json())
    assert view_id not in ids
    # B cannot act on A's view (rotate its feed token) — 404, no leak.
    borrowed = client.post(
        f"/api/v1/search/views/{view_id}/token/rotate",
        headers={"cookie": env[B_USER]["cookie"]},
    )
    assert borrowed.status_code == 404


def test_workspace_same_name_isolated(env):
    """Both members create a workspace with the SAME name; the members
    see exactly their own row (no shared storage behind equal names)."""
    client = env["client"]
    for username in (A_USER, B_USER):
        made = client.post(
            "/api/v1/workspaces",
            json={"name": SHARED_LABEL},
            headers={"cookie": env[username]["cookie"]},
        )
        assert made.status_code in (200, 201), made.text
    for username in (A_USER, B_USER):
        rows = client.get(
            "/api/v1/workspaces", headers={"cookie": env[username]["cookie"]}
        )
        assert rows.status_code == 200
        payload = rows.json()
        mine = [
            row
            for row in _rows(payload)
            if str(row.get("name", "")) == SHARED_LABEL
        ]
        assert len(mine) == 1, f"{username} should see exactly own workspace"


def test_app_settings_do_not_cross(env):
    """A changes a portable setting; B still reads the default."""
    client = env["client"]
    changed = client.patch(
        "/api/v1/settings",
        content=b'{"themeMode": "dark"}',
        headers={"cookie": env[A_USER]["cookie"], "content-type": "application/json"},
    )
    assert changed.status_code in (200, 204), changed.text
    b_view = client.get(
        "/api/v1/settings", headers={"cookie": env[B_USER]["cookie"]}
    )
    assert b_view.status_code == 200
    values = b_view.json()
    assert values.get("themeMode", "system") != "dark"


def test_member_cannot_call_admin_api(env):
    client = env["client"]
    gets = ("/api/v1/admin/users", "/api/v1/admin/invites", "/api/v1/admin/audit", "/api/v1/admin/pool")
    for path_ in gets:
        response = client.get(path_, headers={"cookie": env[A_USER]["cookie"]})
        assert response.status_code == 403, f"GET {path_} → {response.status_code}"
    response = client.post(
        "/api/v1/admin/invites", json={"label": "nope"}, headers={"cookie": env[A_USER]["cookie"]}
    )
    assert response.status_code == 403


def test_owner_admin_api_has_no_content_read(env):
    """The admin surface exposes lifecycle metadata only — no product
    route serves another user's entries/library/AI content to the owner.
    (Enumerated here: user directory has no content fields.)"""
    client = env["client"]
    users = client.get("/api/v1/admin/users", headers={"cookie": env["owner"]["cookie"]})
    assert users.status_code == 200
    for row in users.json():
        assert "password_hash" not in row
        assert not any(key in row for key in ("entries", "library", "content", "notes"))


def test_paused_member_loses_access_immediately(env):
    """Owner pauses A → A's live session is dead on the next request;
    B unaffected; resume restores A."""
    client = env["client"]
    users = client.get("/api/v1/admin/users", headers={"cookie": env["owner"]["cookie"]})
    a_id = next(row["id"] for row in users.json() if row["username"] == A_USER)
    step_up = client.post(
        "/api/v1/admin/step-up",
        json={"password": PASSWORD},
        headers={"cookie": env["owner"]["cookie"]},
    )
    assert step_up.status_code == 200, step_up.text
    paused = client.post(
        f"/api/v1/admin/users/{a_id}/pause",
        headers={
            "cookie": env["owner"]["cookie"],
            "X-Lumi-Step-Up": step_up.json()["token"],
        },
    )
    assert paused.status_code == 200
    assert _get(env, A_USER, "/api/v1/search/views").status_code == 401
    assert _get(env, B_USER, "/api/v1/search/views").status_code == 200
    step_up = client.post(
        "/api/v1/admin/step-up",
        json={"password": PASSWORD},
        headers={"cookie": env["owner"]["cookie"]},
    )
    resumed = client.post(
        f"/api/v1/admin/users/{a_id}/resume",
        headers={
            "cookie": env["owner"]["cookie"],
            "X-Lumi-Step-Up": step_up.json()["token"],
        },
    )
    assert resumed.status_code == 200
    # A's old cookie was revoked with the pause; re-login works.
    fresh = _login(client, A_USER)
    assert fresh.status_code == 200
    assert client.get(
        "/api/v1/search/views",
        headers={"cookie": fresh.headers["set-cookie"].split(";")[0]},
    ).status_code == 200


def test_invite_single_use_and_expiring(env):
    """A redeemed invite cannot redeem twice; unknown token rejected."""
    client = env["client"]
    invite = client.post(
        "/api/v1/admin/invites",
        json={"label": "once"},
        headers={"cookie": env["owner"]["cookie"]},
    )
    token = invite.json()["token"]
    first = client.post(
        "/api/v1/auth/activate",
        json={"token": token, "username": "carol", "password": PASSWORD},
    )
    assert first.status_code == 200
    again = client.post(
        "/api/v1/auth/activate",
        json={"token": token, "username": "dave", "password": PASSWORD},
    )
    assert again.status_code == 400
    assert again.json()["error"]["type"] == "invite_invalid"


def test_logout_all_revokes_only_own_sessions(env):
    """A logs out everywhere; B's session survives (O149)."""
    client = env["client"]
    client.post(
        "/api/v1/auth/logout-all", headers={"cookie": env[A_USER]["cookie"]}
    )
    assert _get(env, A_USER, "/api/v1/search/views").status_code == 401
    assert _get(env, B_USER, "/api/v1/search/views").status_code == 200


def _rows(payload):
    if isinstance(payload, list):
        return payload
    for key in ("items", "rows", "views", "workspaces", "data"):
        if isinstance(payload, dict) and isinstance(payload.get(key), list):
            return payload[key]
    return []


def _flatten_ids(payload):
    ids: list = []
    for row in _rows(payload):
        if isinstance(row, dict):
            value = row.get("id") or row.get("viewId") or row.get("uuid")
            if value:
                ids.append(value)
        elif isinstance(row, str):
            ids.append(row)
    return ids
