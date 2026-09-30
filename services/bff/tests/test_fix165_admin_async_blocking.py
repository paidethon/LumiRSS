"""FIX-165: the measured blocking calls on the admin surface leave the
event loop.

Measurement first (this repo, bcrypt rounds=12, 5-run averages):

- ``hash_password``        ≈ 189 ms/call
- ``verify_password_hash`` ≈ 191 ms/call
- ``SecretsStore.get``     ≈ 0.007 ms/call — kept synchronous (noise)
- admin ``_uptime_seconds``/``_process_metrics`` (/proc) ≈ 0.04 ms —
  kept synchronous (noise)

The two >100 ms call sites on the admin surface ran SYNCHRONOUSLY on
the event loop and stalled every concurrent request for that whole
window:

1. ``POST /api/v1/admin/step-up`` → ``mint_step_up_token`` →
   ``verify_password_hash`` (step_up.py);
2. ``POST /api/v1/admin/users/{id}/reset-password`` → ``hash_password``
   (routers/admin/users.py).

Both now run in a worker thread. The tests pin it by thread identity:
the bcrypt calls must NOT execute on the event-loop thread (which, in
these tests, is the ``asyncio.run`` main thread). All credentials are
runtime-generated test fakes.
"""

import asyncio
import secrets
import threading

import httpx

import lumirss.accounts_store as accounts_store
import lumirss.middleware as middleware
import lumirss.step_up as step_up_module
from lumirss.main import app
from lumirss.storage import Database

LOOP_THREAD = threading.get_ident()


def _session_env(monkeypatch, tmp_path) -> tuple[str, str]:
    password = "pw-" + secrets.token_urlsafe(16)
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    middleware._implicit_owner_cache.clear()
    return str(tmp_path / "lumi.sqlite"), password


async def _set_owner_password(db_path: str, password: str) -> None:
    from lumirss.accounts_store import AccountsStore, hash_password

    database = Database(db_path)
    await database.migrate()
    store = AccountsStore(database)
    for row in await store.list_users(limit=50):
        if row["role"] == "owner":
            await store.set_password_hash(str(row["id"]), hash_password(password))
            return
    raise AssertionError("owner row missing after startup migration")


async def _scenario(monkeypatch, tmp_path) -> None:
    db_path, owner_password = _session_env(monkeypatch, tmp_path)

    verify_idents: list[int] = []
    real_verify = accounts_store.verify_password_hash

    def recording_verify(supplied: str, stored: str) -> bool:
        verify_idents.append(threading.get_ident())
        return real_verify(supplied, stored)

    monkeypatch.setattr(accounts_store, "verify_password_hash", recording_verify)

    hash_idents: list[int] = []
    import lumirss.routers.admin.users as admin_users_module

    real_hash = admin_users_module.hash_password

    def recording_hash(password: str) -> str:
        hash_idents.append(threading.get_ident())
        return real_hash(password)

    monkeypatch.setattr(admin_users_module, "hash_password", recording_hash)

    async with app.router.lifespan_context(app):
        # The lifespan's owner migration created the owner row — only
        # now can the test password be installed.
        await _set_owner_password(db_path, owner_password)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://bff.test"
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": "owner", "password": owner_password},
            )
            assert login.status_code == 200, login.text
            # Login itself runs a bcrypt verify on the loop — that is the
            # auth surface's boundary (a different fix lane), not this
            # item's claim. Only the ADMIN step-up mint is pinned here.
            verify_idents.clear()

            # 1) step-up mint with a WRONG password: the bcrypt verify
            # must run off the loop (400 invalid_credentials unchanged).
            mint = await client.post(
                "/api/v1/admin/step-up",
                json={
                    "password": owner_password + "x" * 4,
                    "operation": "user_password_reset",
                    "targetUserId": "u" + tmp_path.name[-6:],
                },
            )
            assert mint.status_code == 400, mint.text
            assert mint.json()["error"]["type"] == "invalid_credentials"
            assert verify_idents, "step-up mint must run the password verify"
            assert all(i != LOOP_THREAD for i in verify_idents), (
                "verify_password_hash ran on the event loop thread"
            )

            # 2) reset-password on a real member: the bcrypt hash must
            # run off the loop too. The member row is created directly
            # (activation would mint a member session over the owner's).
            from lumirss.accounts_store import AccountsStore

            store = AccountsStore(app.state.control_db)
            member = await store.create_user(
                username="fix165member",
                password_hash=real_hash("member-pw-not-used-for-login"),
                role="member",
            )
            member_id = str(member["id"])
            hash_idents.clear()

            mint_ok = await client.post(
                "/api/v1/admin/step-up",
                json={
                    "password": owner_password,
                    "operation": "user_password_reset",
                    "targetUserId": member_id,
                },
            )
            assert mint_ok.status_code == 200, mint_ok.text
            reset = await client.post(
                f"/api/v1/admin/users/{member_id}/reset-password",
                headers={"X-Lumi-Step-Up": mint_ok.json()["token"]},
            )
            assert reset.status_code == 200, reset.text
            assert hash_idents, "reset-password must hash a fresh password"
            assert all(i != LOOP_THREAD for i in hash_idents), (
                "hash_password ran on the event loop thread"
            )


def test_admin_bcrypt_calls_run_off_the_event_loop(monkeypatch, tmp_path):
    asyncio.run(_scenario(monkeypatch, tmp_path))


def test_step_up_mint_offloads_the_bcrypt_verify():
    """Regression guard by construction: the mint coroutine must reach
    the bcrypt verify through a worker thread, never inline."""
    import inspect

    source = inspect.getsource(step_up_module.mint_step_up_token)
    assert "to_thread" in source, (
        "mint_step_up_token must offload the bcrypt verify"
    )
