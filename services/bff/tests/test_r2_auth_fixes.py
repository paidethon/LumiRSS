"""R2 auth-domain FIX items — reproduction + regression evidence.

Covers FIX-022 / FIX-211 / FIX-212 / FIX-213 / FIX-219 / FIX-220. Each
test encodes the acceptance rule from the fix item; where the described
defect reproduces on the baseline, the failing run is the reproduction
evidence, and the fix turns it green. Where the implementation already
satisfies the rule, the passing test IS the verifying evidence
(BASELINE_OK). Concurrency samples use deterministic interleavings
(asyncio.Barrier / explicit admission order) so results are repeatable.

All credentials are runtime-generated fakes — never real secrets.
"""

import asyncio
import hashlib
import secrets as _secrets

from fastapi.testclient import TestClient

import lumirss.middleware as middleware
from lumirss.main import app
from lumirss.storage import Database


def _fake(prefix: str) -> str:
    return prefix + _secrets.token_urlsafe(9)


def _run(coroutine):
    return asyncio.run(coroutine)


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
    """Give the startup-migration owner account a known (random) password."""

    async def go():
        from lumirss.accounts_store import AccountsStore, hash_password

        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(password))
                return str(row["id"])
        raise AssertionError("owner row missing after startup migration")

    return _run(go())


def _login(client: TestClient, *, username: str = "owner", password: str):
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


def _cookie_headers(response) -> dict[str, str]:
    return {"cookie": response.headers["set-cookie"].split(";")[0]}


def _activate_member(client, owner_headers, username: str, password: str):
    """Admin invite + activation; returns (headers, raw_session_token)."""
    invite = client.post(
        "/api/v1/admin/invites", json={"label": username}, headers=owner_headers
    )
    assert invite.status_code == 200, invite.text
    activation = client.post(
        "/api/v1/auth/activate",
        json={
            "token": invite.json()["token"],
            "username": username,
            "password": password,
        },
    )
    assert activation.status_code == 200, activation.text
    cookie = activation.headers["set-cookie"].split(";")[0]
    return {"cookie": cookie}, cookie.split("=", 1)[1]


def _session_row(db_path: str, raw_token: str):
    async def go():
        database = Database(db_path)
        await database.migrate()
        return await database.fetch_one(
            "SELECT token_hash, user_id, expires_at FROM auth_sessions WHERE token_hash = ?",
            (hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),),
        )

    return _run(go())


# ---------------------------------------------------------------------------
# FIX-022 — 管理员禁用用户后，旧 Cookie 的每次授权都遵守有效状态
#（读 + 写立即失败，不依赖下次登录）。


def test_fix022_admin_pause_blocks_old_cookie_read_and_write(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    member_name = "r022a" + _secrets.token_hex(3)
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        owner_headers = _cookie_headers(owner)
        member_headers, _member_token = _activate_member(
            client, owner_headers, member_name, password
        )
        # 基线：禁用前读与写都放行。
        assert (
            client.get("/api/v1/auth/sessions", headers=member_headers).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/auth/login-events/seen", headers=member_headers
            ).status_code
            == 200
        )
        # 管理员禁用：真实 admin 路由（step-up + pause）。
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        member_id = next(
            str(u["id"]) for u in users if str(u["username"]) == member_name
        )
        step = client.post(
            "/api/v1/admin/step-up", json={"password": password}, headers=owner_headers
        )
        assert step.status_code == 200, step.text
        paused = client.post(
            f"/api/v1/admin/users/{member_id}/pause",
            headers={**owner_headers, "X-Lumi-Step-Up": step.json()["token"]},
        )
        assert paused.status_code == 200, paused.text
        # 旧 Cookie：读与写立即 401 —— 不是等下次登录才生效。
        assert (
            client.get("/api/v1/auth/sessions", headers=member_headers).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/login-events/seen", headers=member_headers
            ).status_code
            == 401
        )


def test_fix022_status_rule_blocks_even_without_revocation(monkeypatch, tmp_path):
    """更严格的口径：即使管理员路径的会话吊销带没有执行（存量会话行
    原样保留），每次授权也必须遵守 users.status —— 读写全拒。"""
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    member_name = "r022b" + _secrets.token_hex(3)
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        owner_headers = _cookie_headers(owner)
        member_headers, member_token = _activate_member(
            client, owner_headers, member_name, password
        )
        assert (
            client.get("/api/v1/auth/sessions", headers=member_headers).status_code
            == 200
        )

        async def pause_without_revocation():
            from lumirss.accounts_store import AccountsStore

            database = Database(db_path)
            await database.migrate()
            store = AccountsStore(database)
            rows = await store.list_users(limit=50)
            member_id = next(
                str(r["id"]) for r in rows if str(r["username"]) == member_name
            )
            assert await store.set_user_status(member_id, "paused")

        _run(pause_without_revocation())
        # 会话行仍在 —— 拦截必须来自状态规则本身。
        assert _session_row(db_path, member_token) is not None
        assert (
            client.get("/api/v1/auth/sessions", headers=member_headers).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/login-events/seen", headers=member_headers
            ).status_code
            == 401
        )


# ---------------------------------------------------------------------------
# FIX-211 — 并发首次初始化：至多一个有效 owner；输家干净收敛，
# 失败不留下半初始化状态。


def test_fix211_concurrent_first_init_yields_exactly_one_owner(
    monkeypatch, tmp_path
):
    from lumirss.accounts_store import AccountsStore
    from lumirss.owner_migration import ensure_owner_migration
    from lumirss.secrets_store import SecretsStore

    db_path = str(tmp_path / "lumi.sqlite")
    monkeypatch.setenv("LUMIRSS_DB_PATH", db_path)
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    middleware._implicit_owner_cache.clear()

    # 确定性并发样本：三个初始化请求先一起完成「库里没有 owner」的
    # 判定（Barrier 汇合，仅拦最前的 3 次调用），再同时进入
    # create_user —— 复现多 worker 同库冷启动的竞争窗口。其后的
    # list_users 调用（含修复内的收敛路径）直通原实现。
    original_list_users = AccountsStore.list_users
    barrier = asyncio.Barrier(3)
    barriered = [3]

    async def synced_list_users(self, limit=200):
        if barriered[0] > 0:
            barriered[0] -= 1
            await barrier.wait()
        return await original_list_users(self, limit=limit)

    monkeypatch.setattr(AccountsStore, "list_users", synced_list_users)

    async def scenario():
        database = Database(db_path)
        control_secrets = SecretsStore(tmp_path / "control-secrets.json")
        return await asyncio.gather(
            ensure_owner_migration(database, control_secrets),
            ensure_owner_migration(database, control_secrets),
            ensure_owner_migration(database, control_secrets),
            return_exceptions=True,
        )

    results = _run(scenario())
    failures = [r for r in results if isinstance(r, BaseException)]
    # 输家必须干净收敛（或抛定义好的错误），绝不裸抛 UNIQUE 冲突
    # 崩掉启动，也不留下半初始化状态。
    assert not failures, [repr(f) for f in failures]
    assert len({str(r) for r in results}) == 1

    async def owner_rows():
        database = Database(db_path)
        await database.migrate()
        rows = await database.fetch_all(
            "SELECT id, username, role FROM users ORDER BY created_at ASC"
        )
        return [dict(r) for r in rows]

    users = _run(owner_rows())
    owners = [u for u in users if u["role"] == "owner"]
    assert len(owners) == 1
    assert owners[0]["username"] == "owner"
    assert len(users) == 1  # 没有任何半初始化的额外账户行


# ---------------------------------------------------------------------------
# FIX-212 — 会话固定：认证前的 Cookie 标识不得成为认证后的有效会话
#（登录必须轮换标识，旧固定值重放被拒）。


def test_fix212_pre_auth_cookie_never_becomes_valid_session(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    fixated = "fixated-" + _secrets.token_urlsafe(16)
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        # 登录前浏览器已被诱导持有攻击者已知的固定 Cookie。
        pre = client.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": password},
            headers={"cookie": f"lumirss_session={fixated}"},
        )
        assert pre.status_code == 200, pre.text
        minted = pre.headers["set-cookie"].split(";")[0].split("=", 1)[1]
        # 登录成功必须轮换标识：新 Set-Cookie ≠ 认证前的固定值。
        assert minted != fixated
        # 固定的旧标识重放：读与写都被拒。
        replay = {"cookie": f"lumirss_session={fixated}"}
        assert client.get("/api/v1/auth/sessions", headers=replay).status_code == 401
        assert (
            client.post("/api/v1/auth/login-events/seen", headers=replay).status_code
            == 401
        )
        # 服务端从未为该标识签发过会话行。
        assert _session_row(db_path, fixated) is None


# ---------------------------------------------------------------------------
# FIX-213 — 同一重置令牌并发兑换只有一次成功；密码变更与撤销
# 结果保持一致。


def test_fix213_concurrent_reset_token_redeem_single_winner(monkeypatch, tmp_path):
    from lumirss.accounts_store import AccountsStore, InviteInvalid, hash_password

    db_path = str(tmp_path / "lumi.sqlite")
    monkeypatch.setenv("LUMIRSS_DB_PATH", db_path)
    password = _fake("pw-")

    async def setup():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        user = await store.create_user(
            username="r213member",
            password_hash=hash_password(password),
            role="member",
        )
        raw, _invite = await store.create_invite(
            created_by="test",
            ttl_hours=1,
            kind="recovery",
            target_user=str(user["id"]),
            label="r213",
        )
        return raw

    raw = _run(setup())

    async def redeem_all():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        return await asyncio.gather(
            store.redeem_invite(raw),
            store.redeem_invite(raw),
            store.redeem_invite(raw),
            return_exceptions=True,
        )

    outcomes = _run(redeem_all())
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    losers = [o for o in outcomes if isinstance(o, InviteInvalid)]
    assert len(winners) == 1, [repr(o) for o in outcomes]
    assert len(losers) == len(outcomes) - 1


def test_fix213_recover_second_use_rejected_state_consistent(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    new_password = _fake("new-")
    member_name = "r213b" + _secrets.token_hex(3)
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        owner_headers = _cookie_headers(owner)
        member_headers, _member_token = _activate_member(
            client, owner_headers, member_name, password
        )
        # 管理员密码重置 → 一次性恢复令牌（同时吊销该用户全部会话）。
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        member_id = next(
            str(u["id"]) for u in users if str(u["username"]) == member_name
        )
        step = client.post(
            "/api/v1/admin/step-up", json={"password": password}, headers=owner_headers
        )
        reset = client.post(
            f"/api/v1/admin/users/{member_id}/reset-password",
            headers={**owner_headers, "X-Lumi-Step-Up": step.json()["token"]},
        )
        assert reset.status_code == 200, reset.text
        recovery_token = reset.json()["recoveryToken"]
        # 旧会话已被吊销。
        assert (
            client.get("/api/v1/auth/sessions", headers=member_headers).status_code
            == 401
        )
        # 第一次兑换：成功，密码变更 + 为本人签发新会话。
        first = client.post(
            "/api/v1/auth/recover",
            json={"token": recovery_token, "newPassword": new_password},
        )
        assert first.status_code == 200, first.text
        # 第二次兑换同一令牌：干净的已定义错误，状态不再变化。
        second = client.post(
            "/api/v1/auth/recover",
            json={"token": recovery_token, "newPassword": _fake("again-")},
        )
        assert second.status_code == 400
        assert second.json()["error"]["type"] == "invite_invalid"
        # 密码变更与撤销结果一致：新密码可登录，旧密码/旧 Cookie 无效。
        assert (
            _login(client, username=member_name, password=new_password).status_code
            == 200
        )
        assert (
            _login(client, username=member_name, password=password).status_code == 401
        )
        assert (
            client.get("/api/v1/auth/sessions", headers=member_headers).status_code
            == 401
        )


# ---------------------------------------------------------------------------
# FIX-219 — 并行成功登录不得清空并发的失败计数；限流结果可重复。


def test_fix219_parallel_success_may_not_erase_concurrent_failures():
    middleware._login_failures.clear()
    scope = {"client": ("127.0.0.1", 45678)}
    # ① 一次已入账的失败。
    middleware.register_login_failure(scope)
    # ② 并行的正确密码请求准入：看到 ①，预算未耗尽。
    assert middleware.login_attempts_allowed(scope)
    # ③ 准入之后、成功返回之前，并行的错误密码请求入账一次失败。
    middleware.register_login_failure(scope)
    # ④ 正确密码请求成功：解锁只对它「准入时已存在」的失败生效。
    middleware.reset_login_failures(scope)
    # ③ 的失败必须仍在预算内：窗口内至多再容纳 LIMIT-1 次失败。
    for _ in range(middleware.LOGIN_FAILURE_LIMIT - 1):
        assert middleware.login_attempts_allowed(scope)
        middleware.register_login_failure(scope)
    assert not middleware.login_attempts_allowed(scope)


def test_fix219_success_still_unlocks_own_prior_failures():
    """保留既有语义：准入前已存在的失败随本次成功一并解锁。"""
    middleware._login_failures.clear()
    scope = {"client": ("127.0.0.1", 45679)}
    for _ in range(3):
        middleware.register_login_failure(scope)
    assert middleware.login_attempts_allowed(scope)
    middleware.reset_login_failures(scope)
    assert middleware.login_attempts_allowed(scope)
    assert middleware.login_retry_after_s(scope) >= 1
    # 解锁后预算完整：整整 LIMIT 次失败后才拒绝。
    for _ in range(middleware.LOGIN_FAILURE_LIMIT):
        assert middleware.login_attempts_allowed(scope)
        middleware.register_login_failure(scope)
    assert not middleware.login_attempts_allowed(scope)


# ---------------------------------------------------------------------------
# FIX-220 — 注销响应返回时撤销已提交：紧接着的写请求必须被拒。


def test_fix220_write_immediately_after_logout_response_rejected(
    monkeypatch, tmp_path
):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        login = _login(client, password=password)
        headers = _cookie_headers(login)
        raw_token = headers["cookie"].split("=", 1)[1]
        assert client.get("/api/v1/auth/sessions", headers=headers).status_code == 200
        logout = client.post("/api/v1/auth/logout", headers=headers)
        assert logout.status_code == 200
        assert "Max-Age=0" in logout.headers["Set-Cookie"]
        # 前端收到成功的那一刻（客户端尚未丢弃 Cookie），紧随的写与读
        # 都必须被拒 —— 撤销已随响应前的提交生效。
        assert (
            client.post("/api/v1/auth/login-events/seen", headers=headers).status_code
            == 401
        )
        assert client.get("/api/v1/auth/sessions", headers=headers).status_code == 401
        # 服务端状态已提交：会话行已物理删除。
        assert _session_row(db_path, raw_token) is None


# ---------------------------------------------------------------------------
# D-03 — reset-password 与其他 owner-targetable 端点同语义：owner 目标 403。
#（敌意 admin 不得借密码重置接管 owner 身份；owner 自己的密码走自助/
#  恢复通道，不经管理端点。）


def _grant_admin_role(client, owner_headers, password: str, member_name: str) -> str:
    """把一个已激活 member 提为 admin（owner-only 端点），返回其 user id。"""
    users = client.get("/api/v1/admin/users", headers=owner_headers).json()
    member_id = next(
        str(u["id"]) for u in users if str(u["username"]) == member_name
    )
    step = client.post(
        "/api/v1/admin/step-up", json={"password": password}, headers=owner_headers
    )
    assert step.status_code == 200, step.text
    role = client.post(
        f"/api/v1/admin/users/{member_id}/role",
        json={"role": "admin"},
        headers={**owner_headers, "X-Lumi-Step-Up": step.json()["token"]},
    )
    assert role.status_code == 200, role.text
    return member_id


def test_d03_admin_cannot_reset_owner_password(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    member_name = "d03a" + _secrets.token_hex(3)
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        owner_headers = _cookie_headers(owner)
        admin_headers, _ = _activate_member(
            client, owner_headers, member_name, password
        )
        _grant_admin_role(client, owner_headers, password, member_name)
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        owner_id = next(
            str(u["id"]) for u in users if str(u.get("role")) == "owner"
        )
        # admin 提权后 step-up 用自己的（同一个随机生成的测试）密码。
        step = client.post(
            "/api/v1/admin/step-up",
            json={"password": password},
            headers=admin_headers,
        )
        assert step.status_code == 200, step.text
        reset = client.post(
            f"/api/v1/admin/users/{owner_id}/reset-password",
            headers={**admin_headers, "X-Lumi-Step-Up": step.json()["token"]},
        )
        assert reset.status_code == 403, reset.text
        assert reset.json()["error"]["type"] == "forbidden"
        # owner 的会话不因这次被拒的尝试而受影响。
        assert (
            client.get("/api/v1/auth/sessions", headers=owner_headers).status_code
            == 200
        )


def test_d03_owner_cannot_target_itself_via_reset_password(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        owner_headers = _cookie_headers(owner)
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        owner_id = next(str(u["id"]) for u in users if str(u.get("role")) == "owner")
        step = client.post(
            "/api/v1/admin/step-up", json={"password": password}, headers=owner_headers
        )
        assert step.status_code == 200, step.text
        reset = client.post(
            f"/api/v1/admin/users/{owner_id}/reset-password",
            headers={**owner_headers, "X-Lumi-Step-Up": step.json()["token"]},
        )
        assert reset.status_code == 403, reset.text
        assert reset.json()["error"]["type"] == "forbidden"


# ---------------------------------------------------------------------------
# FIX-036 — 服务器侧语义核验（BASELINE_OK）：恢复令牌明文只出现一次
#（库里仅 SHA-256），消费是单条条件 UPDATE（单赢家）；二次兑换干净拒绝。


def test_fix036_recovery_token_hash_only_and_single_consumption(
    monkeypatch, tmp_path
):
    from lumirss.accounts_store import AccountsStore, InviteInvalid, hash_password
    from lumirss.token_hash import hash_token

    db_path = str(tmp_path / "lumi.sqlite")
    monkeypatch.setenv("LUMIRSS_DB_PATH", db_path)
    password = _fake("pw-")

    async def setup():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        user = await store.create_user(
            username="f036member",
            password_hash=hash_password(password),
            role="member",
        )
        raw, invite = await store.create_invite(
            created_by="test",
            ttl_hours=1,
            kind="recovery",
            target_user=str(user["id"]),
            label="f036",
        )
        return raw, invite, store

    raw, invite, _store = _run(setup())
    # 明文只在返回值里出现一次；库行只有 SHA-256，绝不回读出明文。
    assert isinstance(raw, str) and raw
    assert invite.get("token_hash") is None  # 行投影不含 token_hash 之外的明文

    async def verify_row():
        database = Database(db_path)
        await database.migrate()
        return await database.fetch_one(
            "SELECT * FROM invites WHERE id = ?", (invite["id"],)
        )

    row = _run(verify_row())
    assert str(row["token_hash"]) == hash_token(raw)
    assert str(row["token_hash"]) != raw
    for value in row:
        if isinstance(value, str):
            assert raw not in value  # 明文不出现在任何列

    async def redeem_twice():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        first = await store.redeem_invite(raw)
        try:
            await store.redeem_invite(raw)
        except InviteInvalid:
            second = "rejected"
        else:
            second = "accepted"
        return first, second

    first, second = _run(redeem_twice())
    assert first["used_at"] is not None
    assert second == "rejected"
