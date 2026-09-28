"""R2 BFF12 会话/登录安全 FIX 项验收（FIX-030 先行）。

约定与 test_r2_auth_fixes.py 一致：每个测试编码对应 FIX 项的验收规则；
基线上真实复现缺陷的，失败运行即复现证据、修复后转绿（FIXED）；
实现本已满足规则的，通过测试即验证证据（BASELINE_OK）。

全部凭据为运行时随机生成的假值（真实 secrets 从不入库/不入测试）。
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
