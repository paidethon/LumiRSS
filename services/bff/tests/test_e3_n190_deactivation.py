"""N190 账户停用前迁出 — 停用请求 / 登录阻断 + 诚实状态页 / 运营者恢复。

- 请求：密码复核 + owner 拒绝 + 会话立即吊销 + 审计；
- 登录：pending_deletion 凭密码正确 → 403 account_deactivated（带
  scheduledDeletionAt + 恢复/迁出提示），不混入通用 401；
- 恢复：运营者既有 resume 端点清停用标记（状态回 active）；
- 诚实边界：到期后没有自动删除作业（代码路径不存在——搜索 import
  与 tasks 注册即可证；界面文案如实说明由运营者手动执行）。
"""

import asyncio
import secrets

from fastapi.testclient import TestClient

from lumirss.main import app

PASSWORD = secrets.token_urlsafe(16)
MEMBER = "n190member"


def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()

    async def _set_owner_password():
        from lumirss.accounts_store import AccountsStore, hash_password
        from lumirss.storage import Database

        database = Database(str(tmp_path / "lumi.sqlite"))
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(PASSWORD))
                return

    with TestClient(app, base_url="http://lumirss.test") as session_client:
        _run(_set_owner_password())
        owner_login = session_client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
        )
        assert owner_login.status_code == 200
        owner = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = session_client.post(
            "/api/v1/admin/invites", json={"label": MEMBER}, headers=owner
        )
        activation = session_client.post(
            "/api/v1/auth/activate",
            json={"token": invite.json()["token"], "username": MEMBER, "password": PASSWORD},
        )
        assert activation.status_code == 200, activation.text
        member = {"cookie": activation.headers["set-cookie"].split(";")[0]}
        yield session_client, owner, member


def _run(coroutine):
    return asyncio.run(coroutine)


def test_n190_request_blocks_login_and_owner_restores(monkeypatch, tmp_path):
    for session_client, owner, member in _setup(monkeypatch, tmp_path):
        # 成员查看当前状态：未请求
        status = session_client.get(
            "/api/v1/me/deactivation-request", headers=member
        )
        assert status.status_code == 200
        assert status.json() == {"requested": False}

        # 错误密码 → 401，状态不变
        wrong = session_client.post(
            "/api/v1/me/deactivation-request", json={"password": "wrong-password"}, headers=member
        )
        assert wrong.status_code == 401
        assert (
            session_client.get("/api/v1/me/deactivation-request", headers=member).json()[
                "requested"
            ]
            is False
        )

        # 正确密码 → pending_deletion；会话立即吊销（该 cookie 失效）
        request = session_client.post(
            "/api/v1/me/deactivation-request", json={"password": PASSWORD}, headers=member
        )
        assert request.status_code == 200, request.text
        body = request.json()
        assert body["requested"] is True
        assert body["scheduledDeletionAt"] > body["requestedAt"]
        assert body["graceDays"] >= 1
        assert "手动" in body["note"]  # 诚实：无自动删除作业

        # 旧会话已吊销 → 需要登录 → 登录被阻断为诚实的 403 状态页
        still = session_client.get("/api/v1/me/deactivation-request", headers=member)
        assert still.status_code == 401
        login = session_client.post(
            "/api/v1/auth/login", json={"username": MEMBER, "password": PASSWORD}
        )
        assert login.status_code == 403, login.text
        denial = login.json()["error"]
        assert denial["type"] == "account_deactivated"
        assert "停用" in denial["message"]
        assert denial["scheduledDeletionAt"] == body["scheduledDeletionAt"]
        assert "运营者" in denial["message"]

        # 运营者恢复（既有 resume 端点 = 清停用标记）
        users = session_client.get("/api/v1/admin/users", headers=owner).json()
        member_id = next(r["id"] for r in users if r["username"] == MEMBER)
        resumed = session_client.post(
            f"/api/v1/admin/users/{member_id}/resume", headers=owner
        )
        assert resumed.status_code == 200, resumed.text

        # 恢复后：状态页回未请求；登录重新可用
        after = session_client.post(
            "/api/v1/auth/login", json={"username": MEMBER, "password": PASSWORD}
        )
        assert after.status_code == 200, after.text
        member2 = {"cookie": after.headers["set-cookie"].split(";")[0]}
        status = session_client.get("/api/v1/me/deactivation-request", headers=member2)
        assert status.json() == {"requested": False}


def test_n190_owner_cannot_self_deactivate(monkeypatch, tmp_path):
    for session_client, owner, _member in _setup(monkeypatch, tmp_path):
        denied = session_client.post(
            "/api/v1/me/deactivation-request", json={"password": PASSWORD}, headers=owner
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["type"] == "owner_undeactivatable"


def test_n190_no_auto_deletion_path_exists():
    """诚实边界（负向断言）：不存在到期自动删除的代码路径——
    - 没有任何 SQL 删除 users 行（状态机只有 UPDATE）；
    - 后台任务注册表（main.py lifespan / control_resources）没有
      deactivation 清扫任务。"""
    import pathlib

    import lumirss

    src_root = pathlib.Path(lumirss.__path__[0])
    for path in src_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "DELETE FROM users" not in text, f"{path} 疑似删除账户行"
    main_text = (src_root / "main.py").read_text(encoding="utf-8")
    assert "deactivation" not in main_text, "lifespan 中不应有停用清扫任务"
