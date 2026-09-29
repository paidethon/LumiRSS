"""NEW-231..240 隔离测试共享引导（session 模式 + 真实 RoutingDatabase）。

与既有跨用户测试（N072 等）同一模式：owner + member 各自登录，
per-user 库按会话路由；只提炼重复样板，不改变行为。
"""

import asyncio
import secrets
from contextlib import contextmanager
from typing import Any

import lumirss.middleware as middleware


def _run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


class Session:
    def __init__(self, client: Any, password: str) -> None:
        self.client = client
        self._password = password
        self._headers: dict[str, dict[str, str]] = {}
        self.owner: dict[str, str] = {}

    def login(self, username: str) -> dict[str, str]:
        if username in self._headers:
            return self._headers[username]
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": self._password},
        )
        assert response.status_code == 200, response.text
        headers = {"cookie": response.headers["set-cookie"].split(";")[0]}
        self._headers[username] = headers
        return headers

    def activate_member(self, username: str) -> dict[str, str]:
        if username in self._headers:
            return self._headers[username]
        invite = self.client.post(
            "/api/v1/admin/invites", json={"label": username}, headers=self.owner
        )
        assert invite.status_code in (200, 201), invite.text
        activation = self.client.post(
            "/api/v1/auth/activate",
            json={
                "token": invite.json()["token"],
                "username": username,
                "password": self._password,
            },
        )
        assert activation.status_code == 200, activation.text
        headers = {"cookie": activation.headers["set-cookie"].split(";")[0]}
        self._headers[username] = headers
        return headers


@contextmanager
def ab_session(monkeypatch: Any, tmp_path: Any):
    """session 模式实例：owner + 若干 member，各自 per-user 库。"""
    password = secrets.token_urlsafe(16)
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")

    middleware._rate_windows.clear()
    middleware._login_failures.clear()

    from fastapi.testclient import TestClient

    from lumirss.main import app

    with TestClient(app, base_url="http://lumirss.test") as client:

        async def _set_owner_password() -> None:
            from lumirss.accounts_store import AccountsStore, hash_password
            from lumirss.storage import Database

            database = Database(str(tmp_path / "lumi.sqlite"))
            await database.migrate()
            store = AccountsStore(database)
            for row in await store.list_users(limit=50):
                if row["role"] == "owner":
                    await store.set_password_hash(str(row["id"]), hash_password(password))
                    return

        _run(_set_owner_password())
        session = Session(client, password)
        session.owner = session.login("owner")
        yield session
