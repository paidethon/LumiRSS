"""N009 管理员临时提权（step-up auth）测试。

- 敏感管理操作（角色变更 / 暂停成员 / 配额设置 / 成员密码重置）不带
  X-Lumi-Step-Up 令牌 → 403 step_up_required；普通浏览（GET /users）
  不受影响；
- POST /admin/step-up 用管理员自己的密码铸造令牌（5 分钟、单次使用）；
  密码错 → 400 invalid_credentials；
- 过期令牌 / 已消费令牌 → 403；member 无法铸造（403 forbidden）；
- 审计只记 mint 动作，绝不落令牌/密码（masked audit）。
"""

import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.main import app

PASSWORD = "stepup-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"


def _set_owner_password(db_path) -> None:
    import asyncio

    from lumirss.accounts_store import AccountsStore
    from lumirss.storage import Database

    async def run():
        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["username"] == OWNER_USER:
                await store.set_password_hash(row["id"], hash_of(PASSWORD))

    def hash_of(pw: str) -> str:
        from lumirss.accounts_store import hash_password

        return hash_password(pw)

    asyncio.run(run())


@pytest.fixture()
def stepup_env(monkeypatch, tmp_path):
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
        owner = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = client.post(
            "/api/v1/admin/invites", json={"label": A_USER}, headers=owner
        )
        activation = client.post(
            "/api/v1/auth/activate",
            json={
                "token": invite.json()["token"],
                "username": A_USER,
                "password": PASSWORD,
            },
        )
        assert activation.status_code == 200, activation.text
        member = {"cookie": activation.headers["set-cookie"].split(";")[0]}
        users = client.get("/api/v1/admin/users", headers=owner).json()
        ids = {row["username"]: row["id"] for row in users}
        yield {
            "client": client,
            "owner": owner,
            "member": member,
            "alice_id": ids[A_USER],
        }


def _mint(client, headers, password=PASSWORD):
    return client.post("/api/v1/admin/step-up", json={"password": password}, headers=headers)


def test_sensitive_ops_require_step_up_and_token_works(stepup_env):
    client = stepup_env["client"]
    owner = stepup_env["owner"]
    alice_id = stepup_env["alice_id"]

    # 普通浏览不受影响。
    assert client.get("/api/v1/admin/users", headers=owner).status_code == 200

    # 无令牌 → 403 step_up_required（角色变更）。
    denied = client.post(
        f"/api/v1/admin/users/{alice_id}/role",
        json={"role": "admin"},
        headers=owner,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["type"] == "step_up_required"

    # 暂停成员同样要求提权。
    denied = client.post(f"/api/v1/admin/users/{alice_id}/pause", headers=owner)
    assert denied.status_code == 403
    assert denied.json()["error"]["type"] == "step_up_required"

    # 铸造令牌 → 同一令牌执行敏感操作成功；重放 → 403（单次使用）。
    minted = _mint(client, owner)
    assert minted.status_code == 200, minted.text
    token = minted.json()["token"]
    assert minted.json()["expiresInMinutes"] <= 5
    ok = client.post(
        f"/api/v1/admin/users/{alice_id}/role",
        json={"role": "admin"},
        headers={**owner, "X-Lumi-Step-Up": token},
    )
    assert ok.status_code == 200, ok.text
    replay = client.post(
        f"/api/v1/admin/users/{alice_id}/role",
        json={"role": "member"},
        headers={**owner, "X-Lumi-Step-Up": token},
    )
    assert replay.status_code == 403
    assert replay.json()["error"]["type"] == "step_up_required"


def test_expired_or_invalid_token_denied(stepup_env):
    import asyncio
    import datetime

    from lumirss.storage import Database
    from lumirss.token_hash import hash_token

    client = stepup_env["client"]
    owner = stepup_env["owner"]
    alice_id = stepup_env["alice_id"]

    expired_token = "expired-" + _secrets.token_urlsafe(16)
    past = (
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
    ).isoformat(timespec="seconds")
    future = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5)
    ).isoformat(timespec="seconds")

    async def _insert():
        db = Database(client.app.state.control_db.path)
        await db.migrate()
        await db.execute(
            "INSERT INTO admin_step_up_tokens (token_hash, user_id, operation, created_at, expires_at) VALUES (?, 'owner', NULL, ?, ?)",
            (hash_token(expired_token), past, past),
        )
        await db.execute(
            "INSERT INTO admin_step_up_tokens (token_hash, user_id, operation, created_at, expires_at) VALUES (?, 'someone-else', NULL, ?, ?)",
            (hash_token("foreign-" + _secrets.token_urlsafe(8)), past, future),
        )

    asyncio.run(_insert())

    # 过期 → 403
    expired = client.post(
        f"/api/v1/admin/users/{alice_id}/pause",
        headers={**owner, "X-Lumi-Step-Up": expired_token},
    )
    assert expired.status_code == 403
    assert expired.json()["error"]["type"] == "step_up_required"

    # 他人令牌 → 403
    foreign = client.post(
        f"/api/v1/admin/users/{alice_id}/pause",
        headers={**owner, "X-Lumi-Step-Up": "foreign-" + _secrets.token_urlsafe(8)},
    )
    assert foreign.status_code == 403

    # 乱值 → 403
    junk = client.put(
        f"/api/v1/admin/users/{alice_id}/quota",
        json={"dailyTokens": 1000},
        headers={**owner, "X-Lumi-Step-Up": "junk"},
    )
    assert junk.status_code == 403


def test_member_cannot_mint_step_up_token(stepup_env):
    client = stepup_env["client"]
    member = stepup_env["member"]
    forged = _mint(client, member)
    assert forged.status_code == 403
    assert forged.json()["error"]["type"] == "forbidden"


def test_wrong_password_and_masked_audit(stepup_env):
    client = stepup_env["client"]
    owner = stepup_env["owner"]

    wrong = _mint(client, owner, password="totally-wrong-password")
    assert wrong.status_code == 400
    assert wrong.json()["error"]["type"] == "invalid_credentials"

    minted = _mint(client, owner)
    assert minted.status_code == 200
    token = minted.json()["token"]

    audit = client.get("/api/v1/admin/audit", headers=owner).json()
    rows = audit["items"] if isinstance(audit, dict) else audit
    serialized = str(audit)
    assert token not in serialized
    assert PASSWORD not in serialized
    actions = [row.get("action") for row in rows]
    assert "admin_step_up_mint" in actions
    assert "admin_step_up_mint_failed" in actions
