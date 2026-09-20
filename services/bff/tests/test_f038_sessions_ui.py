"""F038 会话管理 —— 列表/当前标记/撤销/无 token 泄露（负向）。"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumirss.auth_store import AuthStore
from lumirss.main import app
from lumirss.storage import Database

PASSWORD = "test-password-f038-ok"


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def session_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    database = Database(tmp_path / "lumi.sqlite")

    def install():
        async def _install():
            await database.migrate()
            await AuthStore(database).set_password(PASSWORD)

        asyncio.run(_install())

    install()
    with TestClient(app) as test_client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        yield test_client, install


def test_f038_list_current_flag_no_leak_and_revoke_logout(session_env):
    client, _ = session_env
    login = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert login.status_code == 200

    sessions = client.get("/api/v1/auth/sessions")
    assert sessions.status_code == 200
    items = sessions.json()
    assert len(items) == 1
    assert items[0]["current"] is True
    assert len(items[0]["id"]) == 8
    body_text = json.dumps(items)
    # 负向断言：绝不返回 token / hash 形状字段
    assert "token" not in body_text.lower()
    assert "hash" not in body_text.lower()

    # 第二台设备（第二次登录）：当前会话标记唯一
    client.post("/api/v1/auth/login", json={"password": PASSWORD})
    items2 = client.get("/api/v1/auth/sessions").json()
    assert len(items2) == 2
    assert sum(1 for s in items2 if s["current"]) == 1

    # 撤销另一台设备
    other = next(s for s in items2 if not s["current"])
    assert client.delete(f"/api/v1/auth/sessions/{other['id']}").status_code == 204
    assert len(client.get("/api/v1/auth/sessions").json()) == 1

    # 撤销当前会话 = 登出语义：会话列表需要会话 → 401
    me = client.get("/api/v1/auth/sessions").json()[0]
    assert client.delete(f"/api/v1/auth/sessions/{me['id']}").status_code == 204
    assert client.get("/api/v1/auth/sessions").status_code == 401


def test_f038_revoke_missing_id_404(session_env):
    client, _ = session_env
    assert client.post("/api/v1/auth/login", json={"password": PASSWORD}).status_code == 200
    missing = client.delete("/api/v1/auth/sessions/00000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "session_not_found"
    _ = Path, tempfile  # keep imports honest
