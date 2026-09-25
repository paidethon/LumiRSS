"""N192 邀请容量仪表 — GET /admin/capacity 真实行聚合 + 低容量警示。

覆盖：
- 池 {ready, held, assigned} / 邀请 {pending, held} / 用户 {active,
  paused} 与直接对控制库原始查询的数字完全一致（不含过期预约噪声：
  过期未用邀请的池名额先被惰性清扫）；
- lowCapacity 判定 = ready+held < pending（服务端唯一口径）；
- member 403。
"""

import asyncio
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app

PASSWORD = "cap-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"
B_USER = "bob"


@pytest.fixture()
def capacity_env(monkeypatch, tmp_path):
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
            "/api/v1/auth/login", json={"username": OWNER_USER, "password": PASSWORD}
        )
        assert owner_login.status_code == 200, owner_login.text
        owner_headers = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        cookies = {}
        for username in (A_USER, B_USER):
            invite = client.post(
                "/api/v1/admin/invites", json={"label": username}, headers=owner_headers
            )
            assert invite.status_code == 200, invite.text
            activation = client.post(
                "/api/v1/auth/activate",
                json={"token": invite.json()["token"], "username": username, "password": PASSWORD},
            )
            assert activation.status_code == 200, activation.text
            cookies[username] = {"cookie": activation.headers["set-cookie"].split(";")[0]}
        yield {"client": client, "owner": owner_headers, **cookies, "db_path": tmp_path}


def _set_owner_password(db_path) -> None:
    async def run():
        from lumirss.storage import Database

        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        for row in await AccountsStore(database).list_users(limit=50):
            if row["role"] == "owner":
                await AccountsStore(database).set_password_hash(str(row["id"]), hash_password(PASSWORD))
                return
        raise AssertionError("owner migration did not run")

    asyncio.run(run())


def _raw_counts(db_path) -> dict[str, int]:
    """与端点同一事实来源的原始行查询（对照基准）。"""

    async def run() -> dict[str, int]:
        import time

        from lumirss.storage import Database

        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        now = int(time.time())

        async def one(sql: str, params: tuple = ()) -> int:
            row = await database.fetch_one(sql, params)
            return int(row["n"]) if row else 0

        store = AccountsStore(database)
        await store.release_expired_holds()
        return {
            "ready": await one("SELECT COUNT(*) AS n FROM freshrss_pool WHERE state = 'ready'"),
            "held": await one("SELECT COUNT(*) AS n FROM freshrss_pool WHERE state = 'held'"),
            "assigned": await one("SELECT COUNT(*) AS n FROM freshrss_pool WHERE state = 'assigned'"),
            "pending": await one(
                "SELECT COUNT(*) AS n FROM invites WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at > ?",
                (now,),
            ),
            "invite_held": await one(
                "SELECT COUNT(*) AS n FROM invites WHERE held_pool_account IS NOT NULL AND used_at IS NULL AND revoked_at IS NULL"
            ),
            "active": await one("SELECT COUNT(*) AS n FROM users WHERE status = 'active'"),
            "paused": await one("SELECT COUNT(*) AS n FROM users WHERE status = 'paused'"),
        }

    return asyncio.run(run())


def _create_invite(client, headers, *, hold: bool):
    body = {"kind": "signup"}
    if hold:
        body["holdPool"] = True
    return client.post("/api/v1/admin/invites", json=body, headers=headers)


def test_capacity_numbers_equal_raw_queries(capacity_env):
    env = capacity_env
    # 池：2 ready（激活 bob 时无 hold，直接手工登记一行）。
    for i in range(2):
        add = env["client"].post(
            "/api/v1/admin/pool",
            json={
                "freshrssUsername": f"pool{i}",
                "freshrssBaseUrl": "https://freshrss.example.test",
                "apiPassword": "not-a-real-password",
            },
            headers=env["owner"],
        )
        assert add.status_code == 200, add.text
    # 一个 signup 邀请 hold 一个池名额（pending 且 held）。
    held_invite = _create_invite(env["client"], env["owner"], hold=True)
    assert held_invite.status_code == 200, held_invite.text
    # 一个普通 pending 邀请。
    assert _create_invite(env["client"], env["owner"], hold=False).status_code == 200
    # 一个 revoked 邀请（不算 pending）。
    revocable = _create_invite(env["client"], env["owner"], hold=False)
    assert (
        env["client"]
        .delete(f"/api/v1/admin/invites/{revocable.json()['invite']['id']}", headers=env["owner"])
        .status_code
        == 200
    )
    # bob 暂停 → users.paused = 1。
    users = env["client"].get("/api/v1/admin/users", headers=env["owner"]).json()
    bob_id = next(row["id"] for row in users if row["username"] == B_USER)
    assert env["client"].post(f"/api/v1/admin/users/{bob_id}/pause", headers=env["owner"]).status_code == 200

    response = env["client"].get("/api/v1/admin/capacity", headers=env["owner"])
    assert response.status_code == 200, response.text
    data = response.json()
    raw = _raw_counts(env["db_path"])
    assert data["pool"] == {"ready": raw["ready"], "held": raw["held"], "assigned": raw["assigned"]}
    assert data["invites"] == {"pending": raw["pending"], "held": raw["invite_held"]}
    assert data["users"] == {"active": raw["active"], "paused": raw["paused"]}
    # 2 ready + 1 held ≥ 2 pending → 不低容量。
    assert data["lowCapacity"] is (raw["ready"] + raw["held"] < raw["pending"])


def test_capacity_low_warning_when_deliverable_below_pending(capacity_env):
    env = capacity_env
    # 不登记任何池账号：2 个 pending 邀请（ready+held=0 < 2）→ 警示为真。
    assert _create_invite(env["client"], env["owner"], hold=False).status_code == 200
    assert _create_invite(env["client"], env["owner"], hold=False).status_code == 200
    data = env["client"].get("/api/v1/admin/capacity", headers=env["owner"]).json()
    assert data["lowCapacity"] is True

    # 登记 2 个 ready 池账号后警示消除。
    for i in range(2):
        add = env["client"].post(
            "/api/v1/admin/pool",
            json={
                "freshrssUsername": f"fill{i}",
                "freshrssBaseUrl": "https://freshrss.example.test",
                "apiPassword": "not-a-real-password",
            },
            headers=env["owner"],
        )
        assert add.status_code == 200, add.text
    data = env["client"].get("/api/v1/admin/capacity", headers=env["owner"]).json()
    assert data["lowCapacity"] is False


def test_capacity_member_403(capacity_env):
    env = capacity_env
    response = env["client"].get("/api/v1/admin/capacity", headers=env[A_USER])
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "forbidden"
