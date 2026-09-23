"""Invite schemes / scheduling / pool hold / funnel (N001–N004, 0071).

Covers the four net-new invite features against the real HTTP surface
(admin + activation) and the control-plane store:

- N001 邀请方案模板: named schemes, batch generation (each invite an
  independent one-time token stamped with scheme_id), scheme initial
  sources subscribed best-effort at activation (failures honest, never
  blocking), scheme label on the member directory row; two schemes with
  different initial sources produce accounts with different sources.
- N002 预约生效邀请: not_before is compared against the SERVER clock
  only — store-level fake-clock boundary test; stable 403
  invite_not_active with serverTime + notBefore; preview waiting state;
  expired still behaves as the plain invite_invalid path.
- N003 邀请容量预约: hold at invite creation (ready → held), 409
  pool_empty (unless force), auto-release on revoke and on expiry,
  concurrent activations never double-assign one pool account, held
  account converts to assigned for its own invite, pool rows are never
  deleted.
- N004 邀请漏斗面板: per-scheme + totals aggregation from real rows,
  failedActivation from audit events, scheme filter, and NO invite
  codes anywhere in the response.

Backward compatibility is asserted throughout: invites without scheme /
not_before / hold activate exactly as before (no new response fields).
"""

import asyncio
import secrets as _secrets
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app

PASSWORD = "sch-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"


@pytest.fixture()
def invite_env(monkeypatch, tmp_path):
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
        # One plain member for the vertical-isolation (403) assertions.
        invite = client.post("/api/v1/admin/invites", json={"label": A_USER}, headers=owner_headers)
        assert invite.status_code == 200, invite.text
        activation = client.post(
            "/api/v1/auth/activate",
            json={"token": invite.json()["token"], "username": A_USER, "password": PASSWORD},
        )
        assert activation.status_code == 200, activation.text
        yield {
            "client": client,
            "owner": owner_headers,
            "member": {"cookie": activation.headers["set-cookie"].split(";")[0]},
            "db_path": tmp_path,
        }


def _set_owner_password(db_path) -> None:
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


async def _fresh_store(db_path):
    from lumirss.storage import Database

    database = Database(db_path / "lumi.sqlite")
    await database.migrate()
    return AccountsStore(database)


def _create_scheme(env, **overrides):
    body = {"name": "基础套餐", "ttlHours": 48, **overrides}
    response = env["client"].post("/api/v1/admin/invite-schemes", json=body, headers=env["owner"])
    assert response.status_code == 200, response.text
    return response.json()


def _generate(env, scheme_id, count, **overrides):
    body = {"count": count, **overrides}
    return env["client"].post(
        f"/api/v1/admin/invite-schemes/{scheme_id}/generate-invites",
        json=body,
        headers=env["owner"],
    )


def _activate(env, token, username, **extra):
    return env["client"].post(
        "/api/v1/auth/activate",
        json={"token": token, "username": username, "password": PASSWORD, **extra},
    )


def _add_pool(env, username):
    response = env["client"].post(
        "/api/v1/admin/pool",
        json={
            "freshrssUsername": username,
            "freshrssBaseUrl": "http://freshrss.test",
            "apiPassword": "pool-secret-" + _secrets.token_urlsafe(6),
        },
        headers=env["owner"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _pool_counts(env):
    status = env["client"].get("/api/v1/admin/pool", headers=env["owner"]).json()
    return status["ready"], status["held"], status["assigned"]


# ===== N001 邀请方案模板 ======================================================


def test_scheme_crud_shape_and_isolation(invite_env):
    env = invite_env
    scheme = _create_scheme(
        env,
        initialSourceUrls=["https://example.com/a.xml", "https://example.com/b.rss"],
        quotaNote="每人 3 源",
    )
    assert scheme["name"] == "基础套餐"
    assert scheme["ttlHours"] == 48
    assert scheme["initialSourceUrls"] == ["https://example.com/a.xml", "https://example.com/b.rss"]
    assert scheme["freshrssPoolHold"] is False
    assert scheme["quotaNote"] == "每人 3 源"
    listing = env["client"].get("/api/v1/admin/invite-schemes", headers=env["owner"])
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()] == [scheme["id"]]
    deleted = env["client"].delete(f"/api/v1/admin/invite-schemes/{scheme['id']}", headers=env["owner"])
    assert deleted.status_code == 200
    missing = env["client"].delete(f"/api/v1/admin/invite-schemes/{scheme['id']}", headers=env["owner"])
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "scheme_not_found"
    # Vertical isolation: the member surface stays 403 (same guard family
    # as the rest of the admin API).
    for method, path, payload in (
        ("get", "/api/v1/admin/invite-schemes", None),
        ("post", "/api/v1/admin/invite-schemes", {"name": "x"}),
        ("post", "/api/v1/admin/invite-schemes/nope/generate-invites", {"count": 1}),
        ("get", "/api/v1/admin/invite-funnel", None),
    ):
        kwargs: dict[str, object] = {"headers": {"cookie": env["member"]["cookie"]}}
        if payload is not None:
            kwargs["json"] = payload
        response = getattr(env["client"], method)(path, **kwargs)
        assert response.status_code == 403, f"{method.upper()} {path} → {response.status_code}"


def test_batch_generation_independent_invites_stamped_with_scheme(invite_env):
    env = invite_env
    scheme = _create_scheme(env)
    response = _generate(env, scheme["id"], 3)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scheme"]["id"] == scheme["id"]
    tokens = [item["token"] for item in body["invites"]]
    assert len(tokens) == 3
    assert len(set(tokens)) == 3  # independent one-time invites
    invites = env["client"].get("/api/v1/admin/invites", headers=env["owner"]).json()
    stamped = [row for row in invites if row["scheme_id"] == scheme["id"]]
    assert len(stamped) == 3
    assert {row["expires_at"] - row["created_at"] for row in stamped} == {48 * 3600}
    assert all(row["used_at"] is None for row in stamped)


def test_activation_applies_scheme_sources_per_scheme(invite_env, monkeypatch):
    """Two schemes with different initial sources must produce accounts
    with DIFFERENT subscription sets; the scheme lands on the account
    row and shows in the member directory."""
    env = invite_env
    seen: list[list[str]] = []

    async def fake_apply(state, user_id, source_urls):
        seen.append(list(source_urls))
        return [{"url": url, "ok": True, "error": None} for url in source_urls]

    import lumirss.control_resources as control_resources

    monkeypatch.setattr(control_resources, "apply_scheme_initial_sources", fake_apply)

    scheme_a = _create_scheme(env, name="套餐A", initialSourceUrls=["https://a.example/feed.xml"])
    scheme_b = _create_scheme(env, name="套餐B", initialSourceUrls=["https://b.example/1.xml", "https://b.example/2.xml"])
    token_a = _generate(env, scheme_a["id"], 1).json()["invites"][0]["token"]
    token_b = _generate(env, scheme_b["id"], 1).json()["invites"][0]["token"]

    activated_a = _activate(env, token_a, "usera")
    assert activated_a.status_code == 200, activated_a.text
    # error=None is omitted (exclude_none) — success carries url+ok only.
    assert activated_a.json()["initialSources"] == [{"url": "https://a.example/feed.xml", "ok": True}]
    activated_b = _activate(env, token_b, "userb")
    assert activated_b.status_code == 200, activated_b.text
    assert [row["url"] for row in activated_b.json()["initialSources"]] == [
        "https://b.example/1.xml",
        "https://b.example/2.xml",
    ]
    # Different schemes → different per-account source sets.
    assert seen == [["https://a.example/feed.xml"], ["https://b.example/1.xml", "https://b.example/2.xml"]]

    users = env["client"].get("/api/v1/admin/users", headers=env["owner"]).json()
    names = {row["username"]: row.get("scheme_name") for row in users}
    assert names["usera"] == "套餐A"
    assert names["userb"] == "套餐B"
    assert names[A_USER] is None  # plain invite → no scheme


def test_scheme_activation_backward_compatible_and_failures_honest(invite_env, monkeypatch):
    """Source failures never block activation (listed honestly per URL),
    and plain invites activate exactly as before (no initialSources key
    in the response at all)."""
    env = invite_env
    import lumirss.control_resources as control_resources

    async def failing_apply(state, user_id, source_urls):
        return [{"url": url, "ok": False, "error": "freshrss_binding_pending"} for url in source_urls]

    monkeypatch.setattr(control_resources, "apply_scheme_initial_sources", failing_apply)
    scheme = _create_scheme(env, initialSourceUrls=["https://a.example/feed.xml"])
    token = _generate(env, scheme["id"], 1).json()["invites"][0]["token"]
    activated = _activate(env, token, "failuser")
    assert activated.status_code == 200  # never blocked by source failures
    assert activated.json()["initialSources"] == [
        {"url": "https://a.example/feed.xml", "ok": False, "error": "freshrss_binding_pending"}
    ]

    plain = env["client"].post("/api/v1/admin/invites", json={"label": "plain"}, headers=env["owner"])
    plain_activated = _activate(env, plain.json()["token"], "plainuser")
    assert plain_activated.status_code == 200
    assert "initialSources" not in plain_activated.json()  # additive field omitted


def test_scheme_source_pending_without_binding(monkeypatch):
    """Unit: no FreshRSS binding → every URL reports binding_pending
    (honest state, no fake success)."""
    import lumirss.control_resources as control_resources

    async def no_adapter(state, user_id):
        return None

    monkeypatch.setattr(control_resources, "user_freshrss_adapter", no_adapter)

    async def run():
        return await control_resources.apply_scheme_initial_sources(
            object(), "u1", ["https://x.example/1.xml", "https://x.example/2.xml"]
        )

    assert asyncio.run(run()) == [
        {"url": "https://x.example/1.xml", "ok": False, "error": "freshrss_binding_pending"},
        {"url": "https://x.example/2.xml", "ok": False, "error": "freshrss_binding_pending"},
    ]


# ===== N002 预约生效邀请 ======================================================


def test_scheduled_invite_rejected_before_not_before(invite_env):
    env = invite_env
    future_iso = "2100-01-01T00:00:00+00:00"
    response = env["client"].post(
        "/api/v1/admin/invites",
        json={"label": "预约", "notBefore": future_iso},
        headers=env["owner"],
    )
    assert response.status_code == 200, response.text
    invite = response.json()["invite"]
    assert invite["not_before"] is not None
    token = response.json()["token"]

    preview = env["client"].get("/api/v1/auth/activation-preview", params={"token": token})
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["valid"] is False  # form must not render
    assert preview_body["notBefore"] is not None
    assert preview_body["serverTime"] is not None

    early = _activate(env, token, "earlyuser")
    assert early.status_code == 403
    error = early.json()["error"]
    assert error["type"] == "invite_not_active"
    assert error["notBefore"] is not None
    assert error["serverTime"] is not None
    # The failed attempt must not burn the one-time token.
    invites = env["client"].get("/api/v1/admin/invites", headers=env["owner"]).json()
    row = next(item for item in invites if item["id"] == invite["id"])
    assert row["used_at"] is None


def test_not_before_boundary_is_server_clock_only(invite_env, monkeypatch):
    """Store-level fake clock: before not_before → InviteNotActive; at /
    after the boundary → redemption succeeds. No client input is part of
    the comparison at all."""
    import lumirss.accounts_store as accounts_store

    async def scenario():
        import tempfile

        from lumirss.storage import Database

        with tempfile.TemporaryDirectory() as tmp:
            database = Database(f"{tmp}/lumi.sqlite")
            store = AccountsStore(database)
            owner = await store.create_user(username="owner", password_hash="x" * 60, role="owner")
            fake_now = 1_900_000_000
            monkeypatch.setattr(accounts_store, "_now", lambda: fake_now)
            raw, _invite = await store.create_invite(created_by=str(owner["id"]), not_before=fake_now + 600)
            # One second before the boundary — still locked.
            monkeypatch.setattr(accounts_store, "_now", lambda: fake_now + 599)
            with pytest.raises(accounts_store.InviteNotActive) as exc_info:
                await store.redeem_invite(raw)
            assert exc_info.value.not_before == fake_now + 600
            assert exc_info.value.now == fake_now + 599
            # At the boundary the invite is active (<= comparison).
            monkeypatch.setattr(accounts_store, "_now", lambda: fake_now + 600)
            redeemed = await store.redeem_invite(raw)
            assert redeemed["used_at"] == fake_now + 600

    asyncio.run(scenario())


def test_expired_invite_behaves_as_before(invite_env, monkeypatch):
    """Expired (not scheduled) → the same invite_invalid path as today."""
    import lumirss.accounts_store as accounts_store

    env = invite_env
    fake_now = 1_900_000_000
    monkeypatch.setattr(accounts_store, "_now", lambda: fake_now)
    response = env["client"].post("/api/v1/admin/invites", json={"ttlHours": 1}, headers=env["owner"])
    assert response.status_code == 200
    token = response.json()["token"]
    monkeypatch.setattr(accounts_store, "_now", lambda: fake_now + 2 * 3600)
    expired = _activate(env, token, "lateuser")
    assert expired.status_code == 400
    assert expired.json()["error"]["type"] == "invite_invalid"


def test_scheduled_invite_activates_once_not_before_passes(invite_env):
    """After not_before (server clock), the invite activates normally and
    the preview flips back to the plain form state."""
    env = invite_env
    past_iso = "2000-01-01T00:00:00+00:00"
    response = env["client"].post(
        "/api/v1/admin/invites",
        json={"notBefore": past_iso},
        headers=env["owner"],
    )
    token = response.json()["token"]
    preview = env["client"].get("/api/v1/auth/activation-preview", params={"token": token}).json()
    assert preview["valid"] is True
    assert preview["notBefore"] is None
    assert preview["serverTime"] is not None
    activated = _activate(env, token, "ontimeuser")
    assert activated.status_code == 200


# ===== N003 邀请容量预约 ======================================================


def test_pool_hold_lifecycle_revoke_releases_slot(invite_env):
    env = invite_env
    _add_pool(env, "pool_a")
    first = env["client"].post("/api/v1/admin/invites", json={"holdPool": True}, headers=env["owner"])
    assert first.status_code == 200, first.text
    assert first.json()["invite"]["held_pool_account"] == "pool_a"
    assert _pool_counts(env) == (0, 1, 0)

    # Pool exhausted → honest 409; force is the explicit downgrade.
    second = env["client"].post("/api/v1/admin/invites", json={"holdPool": True}, headers=env["owner"])
    assert second.status_code == 409
    assert second.json()["error"]["type"] == "pool_empty"
    forced = env["client"].post(
        "/api/v1/admin/invites",
        json={"holdPool": True, "force": True},
        headers=env["owner"],
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["invite"]["held_pool_account"] is None

    # Revoke auto-releases held → free; the slot is reusable.
    invite_id = first.json()["invite"]["id"]
    revoked = env["client"].delete(f"/api/v1/admin/invites/{invite_id}", headers=env["owner"])
    assert revoked.status_code == 200
    assert _pool_counts(env) == (1, 0, 0)
    reusable = env["client"].post("/api/v1/admin/invites", json={"holdPool": True}, headers=env["owner"])
    assert reusable.status_code == 200, reusable.text
    assert reusable.json()["invite"]["held_pool_account"] == "pool_a"


def test_batch_hold_insufficient_pool_rolls_back_or_forces(invite_env):
    env = invite_env
    _add_pool(env, "pool_b")
    scheme = _create_scheme(env, name="持锁套餐", freshrssPoolHold=True)
    short = _generate(env, scheme["id"], 2)
    assert short.status_code == 409
    assert short.json()["error"]["type"] == "pool_empty"
    # Partial batch rolled back: the one invite that got a hold is
    # revoked and its slot released (pool had 1 ready, 2 requested).
    invites = env["client"].get("/api/v1/admin/invites", headers=env["owner"]).json()
    rolled_back = [row for row in invites if row["scheme_id"] == scheme["id"]]
    assert len(rolled_back) == 1
    assert all(row["revoked_at"] is not None for row in rolled_back)
    assert _pool_counts(env)[:2] == (1, 0)
    # force → honest downgrade to no holds, batch still generated.
    forced = _generate(env, scheme["id"], 2, force=True)
    assert forced.status_code == 200, forced.text
    assert len(forced.json()["invites"]) == 2
    assert all(item["invite"]["held_pool_account"] is None for item in forced.json()["invites"])
    assert _pool_counts(env)[:2] == (1, 0)


def test_concurrent_activation_never_double_assigns_pool_account(invite_env):
    """Two parallel coroutines: held invites each convert THEIR OWN held
    account; plain invites racing one ready account — exactly one wins,
    and pool rows are never deleted."""
    env = invite_env
    _add_pool(env, "pool_c1")
    _add_pool(env, "pool_c2")
    scheme = _create_scheme(env, name="并发套餐", freshrssPoolHold=True)
    tokens = [item["token"] for item in _generate(env, scheme["id"], 2).json()["invites"]]
    db_path = env["db_path"]

    async def redeem_and_assign(token: str, username: str):
        store = await _fresh_store(db_path)
        invite = await store.redeem_invite(token)
        user = await store.create_user(
            username=username,
            password_hash=hash_password(PASSWORD),
            role="member",
        )
        held = str(invite["held_pool_account"]) if invite.get("held_pool_account") else None
        assigned = await store.pool_assign(str(user["id"]), held_freshrss_username=held)
        return str(assigned["freshrss_username"]) if assigned else None

    async def run_holds():
        return await asyncio.gather(
            redeem_and_assign(tokens[0], "racer1"),
            redeem_and_assign(tokens[1], "racer2"),
        )

    usernames = [name for name in asyncio.run(run_holds()) if name]
    assert sorted(usernames) == ["pool_c1", "pool_c2"]  # never the same account twice

    # Plain invites + one ready account: concurrent assigns → one winner.
    async def run_plain_race():
        store = await _fresh_store(db_path)
        await store.pool_add(base_url="http://freshrss.test", freshrss_username="pool_c3")
        raw1, _i1 = await store.create_invite(created_by="owner")
        raw2, _i2 = await store.create_invite(created_by="owner")
        await store.redeem_invite(raw1)
        await store.redeem_invite(raw2)
        user1 = await store.create_user(username="racer3", password_hash=hash_password(PASSWORD), role="member")
        user2 = await store.create_user(username="racer4", password_hash=hash_password(PASSWORD), role="member")
        return await asyncio.gather(
            store.pool_assign(str(user1["id"])),
            store.pool_assign(str(user2["id"])),
        )

    one_ready = asyncio.run(run_plain_race())
    assert len([row for row in one_ready if row is not None]) == 1
    assert one_ready[0] is None or one_ready[1] is None

    # The pool rows still exist — activated accounts are never deleted.
    async def pool_rows():
        from lumirss.storage import Database

        database = Database(db_path / "lumi.sqlite")
        rows = await database.fetch_all(
            "SELECT freshrss_username, state FROM freshrss_pool ORDER BY freshrss_username ASC"
        )
        return [dict(row) for row in rows]

    rows = asyncio.run(pool_rows())
    assert {row["freshrss_username"] for row in rows} == {"pool_c1", "pool_c2", "pool_c3"}
    assert all(row["state"] in ("ready", "held", "assigned") for row in rows)


def test_held_invite_activation_binds_held_account_via_api(invite_env):
    env = invite_env
    _add_pool(env, "pool_api")
    invite = env["client"].post("/api/v1/admin/invites", json={"holdPool": True}, headers=env["owner"]).json()
    activated = _activate(env, invite["token"], "helduser")
    assert activated.status_code == 200, activated.text
    assert _pool_counts(env) == (0, 0, 1)  # held → assigned for THIS invite
    status = env["client"].get("/api/v1/admin/pool", headers=env["owner"]).json()
    bound = [member for member in status["members"] if member["username"] == "helduser"]
    assert bound and bound[0]["bound"] is True and bound[0]["boundTo"] == "pool_api"


def test_expired_hold_auto_releases(invite_env, monkeypatch):
    """Expiry has no sweeper — release is enforced where pool state is
    read/assigned, so an expired invite never keeps its slot hostage.
    The server-side store clock is the only clock consulted."""
    import lumirss.accounts_store as accounts_store

    env = invite_env
    _add_pool(env, "pool_exp")
    invite = env["client"].post("/api/v1/admin/invites", json={"holdPool": True}, headers=env["owner"]).json()
    expires_at = invite["invite"]["expires_at"]
    assert _pool_counts(env) == (0, 1, 0)
    # Wall clock passes expires_at → the next pool read releases the hold.
    monkeypatch.setattr(accounts_store, "time", SimpleNamespace(time=lambda: expires_at + 1))
    assert _pool_counts(env) == (1, 0, 0)


# ===== N004 邀请漏斗面板 ======================================================


def test_invite_funnel_counts_and_filter(invite_env, monkeypatch):
    import lumirss.accounts_store as accounts_store

    env = invite_env
    scheme = _create_scheme(env, name="漏斗套餐")
    tokens = [item["token"] for item in _generate(env, scheme["id"], 2).json()["invites"]]
    assert _activate(env, tokens[0], "funneluser").status_code == 200
    # Ad-hoc invites: one revoked, one already expired.
    revoked = env["client"].post("/api/v1/admin/invites", json={"label": "revoked"}, headers=env["owner"]).json()
    assert env["client"].delete(f"/api/v1/admin/invites/{revoked['invite']['id']}", headers=env["owner"]).status_code == 200
    past_now = 1_700_000_000  # comfortably before today
    original_now = accounts_store._now
    monkeypatch.setattr(accounts_store, "_now", lambda: past_now)
    stale = env["client"].post("/api/v1/admin/invites", json={"ttlHours": 1}, headers=env["owner"]).json()
    assert stale["invite"]["expires_at"] == past_now + 3600
    monkeypatch.setattr(accounts_store, "_now", original_now)  # back to the real clock
    # A failed activation attempt → audit event the funnel counts.
    again = _activate(env, tokens[0], "seconduser")
    assert again.status_code == 400
    assert again.json()["error"]["type"] == "invite_invalid"

    funnel = env["client"].get("/api/v1/admin/invite-funnel", headers=env["owner"]).json()
    totals = funnel["totals"]
    assert totals["generated"] == 5  # fixture member + 2 scheme + 2 ad-hoc
    assert totals["activated"] == 2  # fixture member + scheme tokens[0]
    assert totals["revoked"] == 1
    assert totals["expired"] == 1
    assert totals["pending"] == 1  # the unused scheme invite
    assert totals["failedActivation"] >= 1
    buckets = {str(row["schemeId"]): row for row in funnel["byScheme"]}
    scheme_bucket = buckets[scheme["id"]]
    assert scheme_bucket["schemeName"] == "漏斗套餐"
    assert (scheme_bucket["generated"], scheme_bucket["activated"], scheme_bucket["pending"]) == (2, 1, 1)
    assert buckets["None"]["generated"] == 3
    # No invite codes anywhere in the funnel payload.
    flattened = str(funnel)
    assert "inv_" not in flattened and "token" not in flattened

    filtered = env["client"].get(
        "/api/v1/admin/invite-funnel",
        params={"scheme_id": scheme["id"]},
        headers=env["owner"],
    ).json()
    assert filtered["totals"]["generated"] == 2
    assert filtered["totals"]["activated"] == 1
    assert [str(row["schemeId"]) for row in filtered["byScheme"]] == [scheme["id"]]

    unknown = env["client"].get(
        "/api/v1/admin/invite-funnel",
        params={"scheme_id": "s_missing"},
        headers=env["owner"],
    ).json()
    assert unknown["totals"]["generated"] == 0


def test_funnel_updates_after_real_actions(invite_env):
    """The admin panel's funnel cards reflect create / activate — counts
    move with real rows, no cached snapshot."""
    env = invite_env

    def totals():
        return env["client"].get("/api/v1/admin/invite-funnel", headers=env["owner"]).json()["totals"]

    assert totals()["generated"] == 1  # the fixture's member invite (activated)
    created = env["client"].post("/api/v1/admin/invites", json={"label": "漏斗"}, headers=env["owner"]).json()
    assert totals()["generated"] == 2
    assert totals()["pending"] == 1
    assert _activate(env, created["token"], "funnelmove").status_code == 200
    assert totals()["activated"] == 2
    assert totals()["pending"] == 0
