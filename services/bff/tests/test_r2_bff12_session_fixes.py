"""R2 BFF12 会话/登录安全 FIX 项验收（FIX-030 先行）。

约定与 test_r2_auth_fixes.py 一致：每个测试编码对应 FIX 项的验收规则；
基线上真实复现缺陷的，失败运行即复现证据、修复后转绿（FIXED）；
实现本已满足规则的，通过测试即验证证据（BASELINE_OK）。

全部凭据为运行时随机生成的假值（真实 secrets 从不入库/不入测试）。
"""

import asyncio
import hashlib
import secrets as _secrets

import pytest
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


def _session_row(db_path: str, raw_token: str):
    async def go():
        database = Database(db_path)
        await database.migrate()
        return await database.fetch_one(
            "SELECT token_hash, user_id, expires_at FROM auth_sessions WHERE token_hash = ?",
            (hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),),
        )

    return _run(go())


def _audit_rows(db_path: str, action: str) -> list[dict]:
    async def go():
        database = Database(db_path)
        await database.migrate()
        rows = await database.fetch_all(
            "SELECT actor, action, object_id, outcome, detail FROM audit_log WHERE action = ? ORDER BY id ASC",
            (action,),
        )
        return [dict(r) for r in rows]

    return _run(go())


def _mint_owner_session(db_path: str) -> str:
    """第二条设备会话：绑定 owner 的真实 auth_sessions 行，返回原始 token。"""

    async def go():
        from lumirss.accounts_store import AccountsStore
        from lumirss.auth_store import AuthStore

        database = Database(db_path)
        await database.migrate()
        owner_id = None
        for row in await AccountsStore(database).list_users(limit=50):
            if row["role"] == "owner":
                owner_id = str(row["id"])
                break
        assert owner_id is not None
        raw, _expires = await AuthStore(database).create_session(
            30, user_agent="pytest/second", user_id=owner_id
        )
        return raw

    return _run(go())


# ---------------------------------------------------------------------------
# FIX-030 — 会话列表当前设备识别 + 单会话撤销：不能误撤销另一条记录，
# 更不能对「从未存在的 id」误报成功。撤销 id 的契约是「token_hash 的 8 位
# 十六进制精确前缀」——任何通配形状（%/_）都不是合法 id，绝不能经 LIKE
# 语义变成「前缀任意」而命中并删除任意一条会话。


def test_fix030_wildcard_session_id_cannot_revoke_or_succeed(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        first = _login(client, password=password)
        assert first.status_code == 200
        first_headers = _cookie_headers(first)
        first_token = first_headers["cookie"].split("=", 1)[1]
        # 第二台设备：直接造一条真实会话行（绑定 owner）。
        second_token = _mint_owner_session(db_path)
        assert _session_row(db_path, first_token) is not None
        assert _session_row(db_path, second_token) is not None

        # 8 个下划线：LIKE 通配下等价于「任意前缀」——修复前这会撤销
        # 任意一条会话并返回 204（误报成功 + 误撤销另一条记录）。
        bogus = client.delete("/api/v1/auth/sessions/________")
        assert bogus.status_code == 404, bogus.text
        assert bogus.json()["error"]["type"] == "session_not_found"
        # 两条会话都必须原样存活。
        assert _session_row(db_path, first_token) is not None
        assert _session_row(db_path, second_token) is not None
        # 当前会话仍可用（列表正常）。
        assert (
            client.get("/api/v1/auth/sessions", headers=first_headers).status_code
            == 200
        )
        # % 形状同理：不是合法十六进制 id，绝不能命中。
        pct = client.delete("/api/v1/auth/sessions/%25%25%25%25%25%25%25%25")
        assert pct.status_code == 404
        assert _session_row(db_path, first_token) is not None
        assert _session_row(db_path, second_token) is not None


def test_fix030_revoke_exact_id_only_that_session_dies(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        first = _login(client, password=password)
        first_headers = _cookie_headers(first)
        first_token = first_headers["cookie"].split("=", 1)[1]

        second_token = _mint_owner_session(db_path)
        second_hash = hashlib.sha256(second_token.encode("utf-8")).hexdigest()
        second_id = second_hash[:8]

        listing = client.get("/api/v1/auth/sessions", headers=first_headers)
        assert listing.status_code == 200
        items = listing.json()
        assert len(items) == 2
        assert sum(1 for s in items if s["current"]) == 1  # 当前设备唯一且正确
        other = next(s for s in items if not s["current"])
        assert other["id"] == second_id  # 身份映射正确（不是另一条记录）

        # 精确撤销：只有那一条死，当前会话存活。
        assert client.delete(f"/api/v1/auth/sessions/{second_id}").status_code == 204
        assert _session_row(db_path, second_token) is None
        assert _session_row(db_path, first_token) is not None
        # 已死的 id 再撤销：诚实的 404，不是误报成功。
        again = client.delete(f"/api/v1/auth/sessions/{second_id}")
        assert again.status_code == 404
        assert again.json()["error"]["type"] == "session_not_found"


# ---------------------------------------------------------------------------
# FIX-026 — 登录失败对外只有一种形状（不泄露账号是否存在；未知用户同样
# 烧一次 bcrypt 均衡时序，O171）；恢复链接对未知身份也只用通用错误；
# 真实原因只进服务端审计（login_failed + detail），供运营者经
# X-Request-ID 关联诊断。


def test_fix026_login_failures_share_one_public_shape(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        unknown_user = client.post(
            "/api/v1/auth/login",
            json={"username": "nosuch" + _secrets.token_hex(4), "password": password},
        )
        wrong_password = _login(client, password=_fake("wrong-"))
        # 完全一致的状态码与响应体（不是相近——一致）。
        assert unknown_user.status_code == wrong_password.status_code == 401
        assert unknown_user.json() == wrong_password.json()
        assert unknown_user.json()["error"]["type"] == "invalid_credentials"
        # 可诊断的事件编号：每个失败响应都带 X-Request-ID（与访问日志
        # 关联），且不回显任何身份提示。
        assert unknown_user.headers.get("x-request-id")
        body_text = repr(unknown_user.json())
        assert "nosuch" not in body_text


def test_fix026_mixed_failure_kinds_share_one_budget(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        # 未知用户 / 错误密码交替烧同一预算：第 LIMIT 次后一律 429。
        for i in range(middleware.LOGIN_FAILURE_LIMIT):
            response = (
                _login(client, password=_fake("wrong-"))
                if i % 2
                else client.post(
                    "/api/v1/auth/login",
                    json={"username": "nosuch" + _secrets.token_hex(4), "password": password},
                )
            )
            assert response.status_code == 401
        throttled = _login(client, password=_fake("wrong-"))
        assert throttled.status_code == 429
        assert throttled.json()["error"]["type"] == "rate_limited"


def test_fix026_recover_unknown_token_is_generic(monkeypatch, tmp_path):
    _session_env(monkeypatch, tmp_path)
    with TestClient(app, base_url="http://lumirss.test") as client:
        garbage = client.post(
            "/api/v1/auth/recover",
            json={"token": _fake("tok-") + _fake("x-"), "newPassword": _fake("new-")},
        )
        shaped = client.post(
            "/api/v1/auth/recover",
            json={"token": _secrets.token_urlsafe(32), "newPassword": _fake("new-")},
        )
        # 未知/伪造/过期令牌同一种通用错误——不区分「令牌不存在」与
        # 「目标账号不存在」，不泄露任何身份信息。
        assert garbage.status_code == shaped.status_code == 400
        assert garbage.json() == shaped.json()
        assert garbage.json()["error"]["type"] == "invite_invalid"


def test_fix026_failed_logins_audited_with_real_cause(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        ghost = "nosuch" + _secrets.token_hex(4)
        client.post(
            "/api/v1/auth/login", json={"username": ghost, "password": password}
        )
        _login(client, password=_fake("wrong-"))
        rows = _audit_rows(db_path, "login_failed")
        assert [str(r["detail"]) for r in rows] == ["unknown_user", "bad_password"]
        # 审计行保留真实原因（服务端可诊断），但绝不含密码材料。
        for row in rows:
            for value in row.values():
                assert password not in str(value)
                assert "wrong-" not in str(value)


# ---------------------------------------------------------------------------
# FIX-021 — 修改密码成功后其他会话按策略立即撤销（策略 = revoke-others，
# 当前设备换发新会话）。两个独立 TestClient 即两个独立浏览器会话。


def test_fix021_password_change_revokes_other_device_and_rotates_current(
    monkeypatch, tmp_path
):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    new_password = _fake("new-")
    with TestClient(app, base_url="http://lumirss.test") as device_a:
        app.state.db = Database(db_path)
        _set_owner_password(db_path, password)
        login_a = _login(device_a, password=password)
        assert login_a.status_code == 200
        token_a = login_a.headers["set-cookie"].split(";")[0].split("=", 1)[1]
        assert _session_row(db_path, token_a) is not None
        with TestClient(app, base_url="http://lumirss.test") as device_b:
            app.state.db = Database(db_path)
            login_b = _login(device_b, password=password)
            assert login_b.status_code == 200
            old_token_b = login_b.headers["set-cookie"].split(";")[0].split("=", 1)[1]
            changed = device_b.post(
                "/api/v1/auth/password",
                json={"currentPassword": password, "newPassword": new_password},
            )
            assert changed.status_code == 200, changed.text
            # 当前设备换发是轮换：新 token ≠ 旧 token。
            new_token_b = changed.headers["set-cookie"].split(";")[0].split("=", 1)[1]
            assert new_token_b != old_token_b
            # 当前设备用新 Cookie 继续；自己的旧 Cookie 已死。
            assert device_b.get("/api/v1/auth/sessions").status_code == 200
            assert (
                device_b.get(
                    "/api/v1/auth/sessions",
                    headers={"cookie": f"lumirss_session={old_token_b}"},
                ).status_code
                == 401
            )
        # 另一台独立浏览器会话：改密成功那一刻已被撤销——读立即 401。
        assert device_a.get("/api/v1/auth/sessions").status_code == 401
        # 库级证据：A 设备的会话行物理删除（不是仅 Cookie 丢弃）。
        assert _session_row(db_path, token_a) is None
    # 旧密码不再可用，新密码可登录。
    with TestClient(app, base_url="http://lumirss.test") as fresh:
        app.state.db = Database(db_path)
        assert _login(fresh, password=password).status_code == 401
        assert _login(fresh, password=new_password).status_code == 200


# ---------------------------------------------------------------------------
# FIX-023 — 角色变更即时生效：降权后同一会话的下一个 admin 请求立即
# 403（角色每次请求从 users 表现读，无陈旧缓存；会话本身保留）。


def _activate_member(client: TestClient, owner_headers, username: str, password: str):
    """管理员发邀请 + 激活；返回该成员的请求头。"""
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
    return _cookie_headers(activation)


def _role_change(
    client: TestClient, owner_headers, password: str, user_id: str, role: str
):
    """owner-only 角色变更（每次自铸一次性 step-up 令牌）。"""
    step = client.post(
        "/api/v1/admin/step-up",
        json={"password": password, "operation": "user_role_change", "targetUserId": user_id},
        headers=owner_headers,
    )
    assert step.status_code == 200, step.text
    return client.post(
        f"/api/v1/admin/users/{user_id}/role",
        json={"role": role},
        headers={**owner_headers, "X-Lumi-Step-Up": step.json()["token"]},
    )


def test_fix023_demoted_admin_next_admin_call_is_403(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    alice = "r023a" + _secrets.token_hex(3)
    bob = "r023b" + _secrets.token_hex(3)
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        owner_headers = _cookie_headers(owner)
        alice_headers = _activate_member(client, owner_headers, alice, password)
        _activate_member(client, owner_headers, bob, password)
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        ids = {u["username"]: u["id"] for u in users}
        assert (
            _role_change(client, owner_headers, password, ids[alice], "admin").status_code
            == 200
        )
        assert (
            _role_change(client, owner_headers, password, ids[bob], "admin").status_code
            == 200
        )
        # 基线：提权后同一会话立即具备 admin 能力（角色服务端派生）。
        assert (
            client.get("/api/v1/admin/users", headers=alice_headers).status_code == 200
        )
        # owner 降权 alice（bob 是第二活跃 admin → last-admin guard 放行）。
        demoted = _role_change(client, owner_headers, password, ids[alice], "member")
        assert demoted.status_code == 200, demoted.text
        # 降权后 alice 的下一个 admin 请求立即 403 —— 无陈旧角色缓存。
        after = client.get("/api/v1/admin/users", headers=alice_headers)
        assert after.status_code == 403
        assert after.json()["error"]["type"] == "forbidden"
        # 会话行未被删除（是降权不是登出）：探针仍认证成功且角色已更新。
        probe = client.get("/api/v1/auth/session", headers=alice_headers)
        assert probe.status_code == 200
        assert probe.json()["role"] == "member"


# ---------------------------------------------------------------------------
# FIX-024 — Cookie 属性与真实反代 HTTPS 拓扑一致：生产默认 Secure
# （LUMIRSS_SESSION_SECURE_COOKIES 默认 True → __Host- 前缀 + Secure，
# __Host- 的 Path=/ 无 Domain 约束全部满足）；纯 HTTP 开发经文档化
# env 显式退出且保留 HttpOnly/SameSite=Strict；清除 Cookie 与签发对称。


def test_fix024_cookie_flags_secure_default_and_clear_symmetry(monkeypatch):
    from lumirss.config import LumiSettings
    from lumirss.middleware import build_session_cookie, clear_session_cookie

    monkeypatch.delenv("LUMIRSS_SESSION_SECURE_COOKIES", raising=False)
    # 生产（HTTPS 反代，rss.oouo.top via Caddy）：默认即安全形态。
    assert LumiSettings().LUMIRSS_SESSION_SECURE_COOKIES is True
    secure_set = build_session_cookie("tok", 60)
    assert secure_set.startswith("__Host-lumirss_session=")
    for attribute in ("Path=/", "HttpOnly", "SameSite=Strict", "Secure"):
        assert attribute in secure_set
    assert "Domain=" not in secure_set  # __Host- 约束：不得带 Domain
    secure_clear = clear_session_cookie()
    assert secure_clear.startswith("__Host-lumirss_session=")
    for attribute in ("Path=/", "HttpOnly", "SameSite=Strict", "Secure", "Max-Age=0"):
        assert attribute in secure_clear
    # 开发（纯 HTTP vite 代理）：文档化 env 退出 → 无 Secure/__Host-，
    # 其余防护属性保持。
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    plain_set = build_session_cookie("tok", 60)
    assert plain_set.startswith("lumirss_session=")
    assert "Secure" not in plain_set
    assert "HttpOnly" in plain_set and "SameSite=Strict" in plain_set
    plain_clear = clear_session_cookie()
    assert plain_clear.startswith("lumirss_session=")
    assert "Secure" not in plain_clear
    assert "HttpOnly" in plain_clear and "SameSite=Strict" in plain_clear


# ---------------------------------------------------------------------------
# FIX-025 — 跨站写请求防护：真实跨站 form-post 形状（表单编码、无任何
# 自定义头、外域 Origin）必须被拒——会话内写与公开写路径（登录 CSRF）
# 都过 Origin 闸门。SameSite=Strict 是浏览器侧第二层（传输层不模拟，
# 其属性存在性由 FIX-024 断言）；这里验证的是服务端强制边界。


def test_fix025_cross_site_form_post_writes_refused(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        headers = _cookie_headers(_login(client, password=password))
        evil = {"Origin": "https://evil.example"}
        # 会话内写：application/x-www-form-urlencoded + 外域 Origin。
        attack = client.post(
            "/api/v1/auth/logout", data="x=1", headers={**headers, **evil}
        )
        assert attack.status_code == 403
        assert attack.json()["error"]["type"] == "csrf_rejected"
        # 会话没有被这次攻击登出（写未发生）。
        assert (
            client.get("/api/v1/auth/sessions", headers=headers).status_code == 200
        )
        # 登录 CSRF：公开写路径同样被拒。
        login_csrf = client.post(
            "/api/v1/auth/login",
            data="username=owner&password=x",
            headers=evil,
        )
        assert login_csrf.status_code == 403
        assert login_csrf.json()["error"]["type"] == "csrf_rejected"
        # text/plain 形态同样拒绝（判定依据是 Origin，不是内容类型）。
        plain = client.post(
            "/api/v1/auth/login",
            content="x",
            headers={**evil, "content-type": "text/plain"},
        )
        assert plain.status_code == 403
        # 同源表单写不受影响（False positive=0）。
        ok = client.post(
            "/api/v1/auth/logout",
            data="x=1",
            headers={**headers, "Origin": "http://lumirss.test"},
        )
        assert ok.status_code == 200


# ---------------------------------------------------------------------------
# FIX-027 — 登录限流分桶与 Retry-After：浏览器重试风暴或任意转发头
# 不能绕过/转桶。TestClient 的 peer 非可信代理网段 → X-Forwarded-For
# 一律忽略（生产契约：仅可信代理 peer 采纳最后一跳）。


def test_fix027_rotating_xff_cannot_evade_login_budget(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        # 每次失败都换一个伪造 XFF：预算仍只记一个桶。
        for i in range(middleware.LOGIN_FAILURE_LIMIT):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "owner", "password": _fake("wrong-")},
                headers={"X-Forwarded-For": f"203.0.113.{i}"},
            )
            assert response.status_code == 401
        # 换全新 XFF 继续（重试风暴）：仍 429，且 Retry-After 数值诚实
        #（1..窗口秒）。
        still = client.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": _fake("wrong-")},
            headers={"X-Forwarded-For": "198.51.100.254"},
        )
        assert still.status_code == 429
        assert still.json()["error"]["type"] == "rate_limited"
        retry_after = int(still.headers["Retry-After"])
        assert 1 <= retry_after <= middleware.LOGIN_FAILURE_WINDOW_S
        # 正确密码同样被限（不能靠换头越过预算）。
        assert _login(client, password=password).status_code == 429
        # 单元口径：真实 peer 变化才换桶——不同客户端互不锁死。
        middleware._login_failures.clear()
        peer_a = {"client": ("203.0.113.7", 1000), "headers": []}
        peer_b = {"client": ("203.0.113.8", 1000), "headers": []}
        for _ in range(middleware.LOGIN_FAILURE_LIMIT):
            middleware.register_login_failure(peer_a)
        assert not middleware.login_attempts_allowed(peer_a)
        assert middleware.login_attempts_allowed(peer_b)


# ---------------------------------------------------------------------------
# FIX-029 — 2FA/通行密钥失败、取消与钟差场景不得锁死账户，且不降低
# 已有认证强度。TOTP 按 RFC 6238 自定合理策略接受 ±1 个 30s 窗口
# （并拒绝 ±2）；失败尝试只烧一次性 pending token/挑战行，绝不产生
# 账户级锁状态；放弃的 WebAuthn ceremony 留下的挑战行 TTL 自清、
# 不阻塞后续正常登录。


def test_fix029_totp_accepts_adjacent_window_rejects_two_away():
    import time as _time
    from datetime import UTC, datetime

    import pyotp

    import lumirss.totp as totp_core

    secret = pyotp.random_base32()
    totp_obj = pyotp.TOTP(
        secret, digits=totp_core.TOTP_DIGITS, interval=totp_core.TOTP_STEPS
    )

    def code_at(epoch: int) -> str:
        return totp_obj.at(datetime.fromtimestamp(epoch, tz=UTC))

    base = int(_time.time()) // totp_core.TOTP_STEPS * totp_core.TOTP_STEPS
    step = totp_core.TOTP_STEPS
    # 当前窗口 / +1 / -1（客户端钟快或钟慢一个窗口）都接受，
    # 且返回被接受的 slice 供防重放记账。
    assert totp_core.match_timeslice(secret, code_at(base), now=base) == base // step
    assert (
        totp_core.match_timeslice(secret, code_at(base + step), now=base)
        == base // step + 1
    )
    assert (
        totp_core.match_timeslice(secret, code_at(base - step), now=base)
        == base // step - 1
    )
    # ±2 窗口之外：拒绝（不放宽既有认证强度）。
    assert totp_core.match_timeslice(secret, code_at(base + 2 * step), now=base) is None
    assert totp_core.match_timeslice(secret, code_at(base - 2 * step), now=base) is None


@pytest.fixture()
def totp_clock(monkeypatch):
    """Pin lumirss.totp._now so enable/login slices are deterministic."""
    import time as _time

    import lumirss.totp as totp_core

    t0 = int(_time.time()) // totp_core.TOTP_STEPS * totp_core.TOTP_STEPS
    monkeypatch.setattr(totp_core, "_now", lambda: t0)
    return t0


def _enable_totp(client: TestClient, *, at: int) -> str:
    from _virtual_authenticator import totp_at

    setup = client.post("/api/v1/auth/totp/setup", json={})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    enabled = client.post("/api/v1/auth/totp/enable", json={"code": totp_at(secret, at)})
    assert enabled.status_code == 200, enabled.text
    return secret


def test_fix029_repeated_totp_failures_do_not_wedge_account(
    monkeypatch, tmp_path, totp_clock
):
    import lumirss.totp as totp_core
    from _virtual_authenticator import totp_at

    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        assert _login(client, password=password).status_code == 200
        secret = _enable_totp(client, at=totp_clock)
        login_slice = totp_clock + totp_core.TOTP_STEPS

        def wrong_code() -> str:
            expected = totp_at(secret, login_slice)
            return str((int(expected) + 1) % 1_000_000).zfill(6)

        # 两轮「密码步 → 错误验证码 + 同 token 复用」：每轮只烧一次性
        # pending token（4 次失败，恰在共享暴力破解预算内）。
        for _ in range(2):
            challenge = _login(client, password=password)
            assert challenge.status_code == 200
            pending = challenge.json()["pendingToken"]
            bad = client.post(
                "/api/v1/auth/totp/verify",
                json={"pendingToken": pending, "code": wrong_code()},
            )
            assert bad.status_code == 401
            # 同一 pending token 复用也无效（一次性语义未变）。
            replay = client.post(
                "/api/v1/auth/totp/verify",
                json={"pendingToken": pending, "code": wrong_code()},
            )
            assert replay.status_code == 401
            assert replay.json()["error"]["type"] == "pending_token_invalid"
        # 三次错误验证码 + 一次 pending token 重放，全部被拒且只烧
        # 一次性材料（共享暴力破解预算 4/5，尚可完成一次正确登录）。
        # 失败没有产生任何账户级锁状态：TOTP 仍开启、恢复码仍在。
        status = client.get("/api/v1/auth/totp")
        assert status.status_code == 200
        assert status.json()["enabled"] is True
        assert status.json()["recoveryCodesRemaining"] == 8
        # 正确验证码 + 新 pending token → 立即恢复完整登录（不锁死）。
        challenge = _login(client, password=password)
        good = client.post(
            "/api/v1/auth/totp/verify",
            json={
                "pendingToken": challenge.json()["pendingToken"],
                "code": totp_at(secret, login_slice),
            },
        )
        assert good.status_code == 200, good.text
        assert good.json()["authenticated"] is True
        assert client.get("/api/v1/settings").status_code == 200


def test_fix029_aborted_webauthn_ceremony_does_not_block_retry(
    monkeypatch, tmp_path
):
    from _virtual_authenticator import VirtualAuthenticator

    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    origin = "http://lumirss.test"
    with TestClient(app, base_url=origin) as client:
        _set_owner_password(db_path, password)
        assert _login(client, password=password).status_code == 200
        options = client.post("/api/v1/auth/passkeys/options", json={})
        assert options.status_code == 200
        authenticator = VirtualAuthenticator(origin=origin, rp_id="lumirss.test")
        registration = authenticator.make_registration(options.json()["challenge"])
        done = client.post(
            "/api/v1/auth/passkeys",
            json={"label": "钥匙", "challenge": options.json()["challenge"], **registration},
        )
        assert done.status_code == 200, done.text
        client.post("/api/v1/auth/logout")

        def fresh_options():
            payload = client.post(
                "/api/v1/auth/passkeys/login/options", json={"username": "owner"}
            )
            assert payload.status_code == 200
            return payload.json()

        # ceremony ①：取了 options 后用户放弃（挑战行残留，TTL 自清）。
        fresh_options()
        # ceremony ②：签名验证失败（坏签名）。
        payload = fresh_options()
        assertion = authenticator.make_assertion(
            payload["challenge"], corrupt_signature=True
        )
        failed = client.post(
            "/api/v1/auth/passkeys/login",
            json={"username": "owner", "challenge": payload["challenge"], **assertion},
        )
        assert failed.status_code == 401
        assert failed.json()["error"]["type"] == "invalid_credentials"
        # ceremony ③：全新 options + 有效断言 → 立即成功（无锁死、
        # 无需任何解锁步骤），会话可用。
        payload = fresh_options()
        assertion = authenticator.make_assertion(payload["challenge"])
        ok = client.post(
            "/api/v1/auth/passkeys/login",
            json={"username": "owner", "challenge": payload["challenge"], **assertion},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["authenticated"] is True
        assert client.get("/api/v1/settings").status_code == 200
        # 再来一轮失败→成功：凭据没有被任何失败状态楔住（计数器单调
        # 语义只约束克隆，不约束失败重试）。
        payload = fresh_options()
        assertion = authenticator.make_assertion(
            payload["challenge"], corrupt_signature=True
        )
        assert (
            client.post(
                "/api/v1/auth/passkeys/login",
                json={
                    "username": "owner",
                    "challenge": payload["challenge"],
                    **assertion,
                },
            ).status_code
            == 401
        )
        payload = fresh_options()
        assertion = authenticator.make_assertion(payload["challenge"])
        again = client.post(
            "/api/v1/auth/passkeys/login",
            json={"username": "owner", "challenge": payload["challenge"], **assertion},
        )
        assert again.status_code == 200, again.text
        listing = client.get("/api/v1/auth/passkeys")
        assert listing.status_code == 200
        assert len(listing.json()) == 1  # 凭据状态完好，未被标记/移除
