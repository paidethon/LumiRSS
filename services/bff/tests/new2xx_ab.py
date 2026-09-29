"""Shared A/B isolation harness for the NEW-221..230 slice (queue/plan
user-decision capabilities).

Follows the test_multi_account_isolation pattern: session auth, owner +
two invited members (alice/bob), cookie headers per identity. Feature
suites use ``ab_env`` to prove per-user isolation on every new surface.
"""

import asyncio
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password

PASSWORD = "new2xx-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"
B_USER = "bob"


@pytest.fixture()
def ab_env(monkeypatch, tmp_path):
    """Owner + members A/B over session auth; yields {client, a, b, owner}.

    Each member value is a ``cookie`` header dict; requests must pass it
    as ``headers=`` so the session middleware routes to that user's DB.
    """
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    middleware._implicit_owner_cache.clear()

    with TestClient(app := _import_app(), base_url="http://lumirss.test") as client:
        _set_owner_password(tmp_path)
        owner_login = client.post(
            "/api/v1/auth/login", json={"username": OWNER_USER, "password": PASSWORD}
        )
        assert owner_login.status_code == 200, owner_login.text
        owner = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        members = {}
        for username in (A_USER, B_USER):
            invite = client.post(
                "/api/v1/admin/invites", json={"label": username}, headers=owner
            )
            assert invite.status_code == 200, invite.text
            activation = client.post(
                "/api/v1/auth/activate",
                json={
                    "token": invite.json()["token"],
                    "username": username,
                    "password": PASSWORD,
                    "displayName": username,
                },
            )
            assert activation.status_code == 200, activation.text
            members[username] = {
                "cookie": activation.headers["set-cookie"].split(";")[0],
                "userId": str(activation.json().get("userId") or ""),
            }
        for _username, member in members.items():
            if not member["userId"]:
                probe = client.get(
                    "/api/v1/auth/session", headers={"cookie": member["cookie"]}
                )
                member["userId"] = str(probe.json().get("userId") or "")
        yield {
            "client": client,
            "app": app,
            "owner": owner,
            "a": members[A_USER],
            "b": members[B_USER],
            "db_path": tmp_path,
        }


def _import_app():
    from lumirss.main import app

    return app


def _set_owner_password(db_path) -> None:
    """Replace the owner migration's unknowable password via the same
    control-plane store (bcrypt; no plaintext persistence)."""

    async def run():
        from lumirss.storage import Database

        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        store = AccountsStore(database)
        owner = None
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                owner = row
                break
        assert owner is not None, "owner migration did not run"
        await store.set_password_hash(str(owner["id"]), hash_password(PASSWORD))

    asyncio.run(run())


def seed_entry(env, who: str, item_id: str, *, read: int = 0, title: str = "t",
               content_text: str = "",
               published_at: str = "2026-09-20T00:00:00Z") -> str:
    """Insert an entry into that member's search_entries projection
    (routes through RoutingDatabase under the member's user_context);
    returns the ``rss:<entryRef>``."""
    from lumirss.entryref import encode_entry_ref
    from lumirss.user_scope import user_context

    entry_ref = encode_entry_ref(item_id)
    user_id = env[who]["userId"]

    async def run():
        with user_context(user_id):
            await env["app"].state.db.migrate()
            await env["app"].state.db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref,"
                " feed_url, feed_title, title, author, url, content_text,"
                " published_at, read, starred, fetched_at)"
                " VALUES (?, ?, 'https://f.example/rss', '源', ?, '', 'u',"
                " ?, ?, ?, 0, 0)",
                (item_id, entry_ref, title, content_text, published_at, read),
            )

    asyncio.run(run())
    return f"rss:{entry_ref}"
