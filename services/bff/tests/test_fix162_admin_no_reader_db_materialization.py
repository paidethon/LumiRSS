"""FIX-162: admin routes must not trigger reader-side database work.

GET /api/v1/admin/pool and the P11 system counts used to force every
listed member's user database through the full reader-schema migration
(``RoutingDatabase.migrate()``) just to read one binding row / return
zeros for an unmigrated DB — an admin console view materializing reader
databases as a side effect. Both reads already degrade to "unbound" /
honest zeros on failure, and a binding row can only exist in a migrated
database (``bind_freshrss_account`` migrates before writing), so the
forced migration was reader-side work with no information gain.

Pinned here:
- a member row without a materialized user database stays
  unmaterialized after GET /admin/pool (and is honestly reported as
  unbound);
- a genuinely bound member is still reported bound (boundTo) — the
  short-circuit must not lose real bindings;
- GET /admin/system counts still answer for an admin whose DB exists.

All credentials in this file are runtime-generated test fakes.
"""

from fastapi.testclient import TestClient

import lumirss.middleware as middleware
from lumirss.main import app
from lumirss.storage import Database


def _session_env(monkeypatch, tmp_path) -> str:
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    middleware._implicit_owner_cache.clear()
    return str(tmp_path / "lumi.sqlite")


def _set_owner_password(db_path: str, password: str) -> str:
    import asyncio

    from lumirss.accounts_store import AccountsStore, hash_password

    async def go():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(password))
                return str(row["id"])
        raise AssertionError("owner row missing after startup migration")

    return asyncio.run(go())


def _create_member_without_user_db(db_path: str, username: str) -> str:
    import asyncio

    from lumirss.accounts_store import AccountsStore

    async def go():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        user = await store.create_user(
            username=username,
            password_hash="x" * 60,  # never used for login in this test
            role="member",
        )
        return str(user["id"])

    return asyncio.run(go())


def _login(client: TestClient, password: str):
    response = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": password}
    )
    assert response.status_code == 200, response.text
    return {"cookie": response.headers["set-cookie"].split(";")[0]}


def test_admin_pool_does_not_materialize_member_user_databases(
    monkeypatch, tmp_path
):
    db_path = _session_env(monkeypatch, tmp_path)
    tag = tmp_path.name[-6:].lower()
    users_root = tmp_path / "users"

    with TestClient(app, base_url="http://lumirss.test") as client:
        password = "pw-" + tag
        _set_owner_password(db_path, password)
        member_id = _create_member_without_user_db(db_path, "nodb" + tag)
        assert not (users_root / member_id).exists(), (
            "precondition: no user DB yet"
        )
        headers = _login(client, password)
        response = client.get("/api/v1/admin/pool", headers=headers)
    assert response.status_code == 200, response.text
    members = {m["id"]: m for m in response.json()["members"]}
    assert members[member_id]["bound"] is False
    assert members[member_id]["boundTo"] is None
    assert not (users_root / member_id).exists(), (
        "GET /admin/pool must not materialize a member's reader database"
    )


def test_admin_pool_still_reports_a_genuinely_bound_member(
    monkeypatch, tmp_path
):
    db_path = _session_env(monkeypatch, tmp_path)
    tag = tmp_path.name[-6:].lower()

    with TestClient(app, base_url="http://lumirss.test") as client:
        password = "pw-" + tag
        _set_owner_password(db_path, password)
        member_id = _create_member_without_user_db(db_path, "bound" + tag)

        # A real binding lives in a migrated user DB (the bind path
        # migrates before writing) — user context entered explicitly.
        import asyncio

        from lumirss.user_scope import user_context

        async def bind():
            with user_context(member_id):
                await app.state.db.migrate()
                await app.state.db.execute(
                    "INSERT OR REPLACE INTO freshrss_binding (id, base_url, username, public_url, bound_at, source) VALUES (1, ?, ?, ?, strftime('%s','now'), ?)",
                    ("https://freshrss.example", "member_rss", "", "pool"),
                )

        asyncio.run(bind())

        headers = _login(client, password)
        response = client.get("/api/v1/admin/pool", headers=headers)
    assert response.status_code == 200, response.text
    members = {m["id"]: m for m in response.json()["members"]}
    assert members[member_id]["bound"] is True
    assert members[member_id]["boundTo"] == "member_rss"


def test_admin_system_counts_survive_without_forcing_migration(
    monkeypatch, tmp_path
):
    db_path = _session_env(monkeypatch, tmp_path)
    tag = tmp_path.name[-6:].lower()

    with TestClient(app, base_url="http://lumirss.test") as client:
        password = "pw-" + tag
        _set_owner_password(db_path, password)
        headers = _login(client, password)
        response = client.get("/api/v1/admin/system", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    # Shape unchanged; counts remain honest numbers.
    assert isinstance(body["counts"]["users"], int)
    assert body["counts"]["users"] >= 1
    assert isinstance(body["counts"]["feeds"], int)
