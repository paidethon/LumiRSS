"""P11 admin-only system diagnostics — GET /api/v1/admin/system.

Covers the admin console system panel's backend contract:

- owner and admin get 200 with the expected key structure; member 403;
  unauthenticated 401 (server-derived gate, no client-advertised roles);
- the payload never contains secret VALUES: the test wires synthetic
  secret-shaped env (FreshRSS API password / AI key) and asserts those
  exact strings appear nowhere in the response, that no key name matches
  secret/password/token patterns, and that presence facts are booleans;
- store counts honestly reflect the fixture (users/invites) with
  own-scope projection counters present and non-negative;
- background task slots are reported with honest states and an explicitly
  untracked (null) last-run;
- scoping decision for routers/operations.py stays intact: the per-user
  own-scope operations endpoints remain readable by a plain member, while
  the new system-wide diagnostics are admin-gated.
"""

import asyncio
import re
import secrets as _secrets
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app

PASSWORD = "sys-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"
B_USER = "bob"
# Synthetic secret-shaped values (never real credentials).
SECRET_LIKE = "super-secret-" + _secrets.token_urlsafe(12)

_EXPECTED_KEYS = {
    "version",
    "commit",
    "python",
    "apiVersion",
    "uptimeS",
    "uptimeCheckedAt",
    "process",
    "counts",
    "services",
    "tasks",
}
_EXPECTED_COUNT_KEYS = {
    "users",
    "activeUsers",
    "invites",
    "freshrssPoolReady",
    "freshrssPoolAssigned",
    "sessions",
    "feeds",
    "entriesIndexed",
    "libraryItems",
}
_SERVICE_NAMES = {"sqlite", "freshrss", "rsshub", "obsidian", "webdav", "ai", "imap"}
_TASK_NAMES = {
    "search_sync",
    "obsidian_scan",
    "digest_scheduler",
    "mail_imap",
    "gpt_digest_scheduler",
    "rag_idle",
    "rag_index",
}
_TASK_STATES = {"running", "completed", "cancelled", "failed", "off", "unknown"}
_SERVICE_STATES = {
    "healthy",
    "unconfigured",
    "unauthenticated",
    "unavailable",
    "configured",
    "unknown",
}
_SECRET_KEY_PATTERN = re.compile(r"secret|password|token|api[_-]?key", re.IGNORECASE)


@pytest.fixture()
def system_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    # Secret-shaped env: the endpoint must never echo any of these back.
    monkeypatch.setenv("FRESHRSS_API_PASSWORD", SECRET_LIKE)
    monkeypatch.setenv("AI_API_KEY", SECRET_LIKE)
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
    async def run():
        from lumirss.storage import Database

        database = Database(env["db_path"] / "lumi.sqlite")
        await database.migrate()
        changed = await AccountsStore(database).set_user_role(env["ids"][username], role)
        assert changed, f"role setup failed for {username}"

    asyncio.run(run())


def _walk_strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in [str(k), *_walk_strings(v)]]
    if isinstance(node, list):
        return [s for item in node for s in _walk_strings(item)]
    return []


def _assert_no_secrets(payload: Any) -> None:
    # 1. No configured secret VALUE anywhere in the serialized payload.
    for text in _walk_strings(payload):
        assert SECRET_LIKE not in text, f"secret value leaked: {text!r}"
    # 2. No key NAME looks like a secret carrier.
    def _keys(node: Any) -> list[str]:
        if isinstance(node, dict):
            return [*(str(k) for k in node), *(k2 for v in node.values() for k2 in _keys(v))]
        if isinstance(node, list):
            return [k2 for item in node for k2 in _keys(item)]
        return []

    for key in _keys(payload):
        assert not _SECRET_KEY_PATTERN.search(key), f"suspicious key name: {key!r}"
    # 3. Presence facts are booleans, never values.
    for service in payload["services"]:
        assert isinstance(service["configured"], bool)


def test_system_owner_gets_200_with_expected_structure(system_env):
    env = system_env
    response = env["client"].get("/api/v1/admin/system", headers=env["owner"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) >= _EXPECTED_KEYS
    _assert_no_secrets(body)
    # Runtime facts are present and honest (may be null off-Linux).
    assert isinstance(body["version"], str) and body["version"] != ""
    assert body["uptimeS"] is None or body["uptimeS"] >= 0
    process = body["process"]
    assert set(process) == {"rssBytes", "peakRssBytes", "cpuTimeS"}
    assert process["rssBytes"] is None or process["rssBytes"] > 0
    assert process["cpuTimeS"] is None or process["cpuTimeS"] >= 0
    # Store counts: keys fixed, numbers non-negative, identity facts real.
    counts = body["counts"]
    assert set(counts) == _EXPECTED_COUNT_KEYS
    assert counts["users"] == 3
    assert counts["activeUsers"] == 3
    assert counts["invites"] == 2  # used signup invites stay in the ledger
    assert counts["freshrssPoolReady"] == 0
    assert all(isinstance(v, int) and v >= 0 for v in counts.values())
    # Services: fixed vocabulary, honest unconfigured states in this bare env.
    services = {service["name"]: service for service in body["services"]}
    assert set(services) == _SERVICE_NAMES
    for service in services.values():
        assert service["status"] in _SERVICE_STATES
        assert service["latencyMs"] is None or service["latencyMs"] >= 0
    assert services["sqlite"]["status"] == "healthy"
    assert services["freshrss"]["status"] == "unconfigured"
    assert services["rsshub"]["status"] == "unconfigured"
    assert services["obsidian"]["configured"] is False
    # Task slots: all seven reported; search sync disabled by env (interval=0).
    tasks = {task["name"]: task for task in body["tasks"]}
    assert set(tasks) == _TASK_NAMES
    assert tasks["search_sync"]["enabled"] is False
    assert tasks["search_sync"]["state"] == "off"
    for task in tasks.values():
        assert task["state"] in _TASK_STATES
        assert task["lastRunAt"] is None, "no scheduler tracks last-run today"


def test_system_admin_gets_200_member_403(system_env):
    env = system_env
    _set_role_direct(env, A_USER, "admin")
    admin_response = env["client"].get(
        "/api/v1/admin/system", headers={"cookie": env[A_USER]["cookie"]}
    )
    assert admin_response.status_code == 200, admin_response.text
    _assert_no_secrets(admin_response.json())
    member_response = env["client"].get(
        "/api/v1/admin/system", headers={"cookie": env[B_USER]["cookie"]}
    )
    assert member_response.status_code == 403, member_response.text
    assert member_response.json()["error"]["type"] == "forbidden"


def test_system_unauthenticated_401(system_env):
    env = system_env
    # The fixture's TestClient jar holds the last activation cookie (bob);
    # clear it so this call is genuinely cookieless.
    env["client"].cookies.clear()
    response = env["client"].get("/api/v1/admin/system")
    assert response.status_code == 401, response.text
    assert response.json()["error"]["type"] == "session_required"


def test_operations_own_scope_stays_member_readable(system_env):
    """P11 scoping audit: /operations/* are own-scope (RoutingDatabase +
    already-public probe strings) and MUST stay readable for members; only
    the new system-wide diagnostics are admin-gated."""
    env = system_env
    member_headers = {"cookie": env[B_USER]["cookie"]}
    status = env["client"].get("/api/v1/operations/status", headers=member_headers)
    assert status.status_code == 200, status.text
    timeline = env["client"].get("/api/v1/operations/timeline", headers=member_headers)
    assert timeline.status_code == 200, timeline.text
    diagnostics = env["client"].get("/api/v1/operations/diagnostics", headers=member_headers)
    assert diagnostics.status_code == 200, diagnostics.text
    # ...while the cross-user admin surface stays closed to the same member.
    system = env["client"].get("/api/v1/admin/system", headers=member_headers)
    assert system.status_code == 403
