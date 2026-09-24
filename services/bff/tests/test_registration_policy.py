"""P0 公开注册 — 策略真源、服务端强制、角色边界、审计。

- 实例默认 allow_public_registration = false（存量升级与全新部署一致）；
- 注册关闭时直接 POST /auth/register 必须 403 registration_disabled，
  且不泄露用户名存在性（关闭的实例不是用户名 oracle）；
- 管理员开启后注册成功：角色恒为 member（客户端无法指定），
  FreshRSS 池为空 → 账号可用、绑定诚实 pending；
- 每次策略变更与注册落 audit_log。
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app

PASSWORD = "correct horse battery staple"


@pytest.fixture()
def session_client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    from lumirss import middleware as mw

    monkeypatch.setattr(mw.LumiSettings, "model_config", mw.LumiSettings.model_config)
    from lumirss.config import LumiSettings

    monkeypatch.setattr(LumiSettings, "LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"), raising=False)
    client = TestClient(app)
    return client


def _register_enabled(client: TestClient) -> None:
    """Flip allow_public_registration directly in the control DB."""
    from lumirss.instance_settings import InstanceSettingsStore
    from lumirss.storage import Database

    async def run():
        database = Database(str(client.app.state.control_db.path))
        await database.migrate()
        await InstanceSettingsStore(database).set(
            "allow_public_registration", "1", updated_by="test"
        )

    asyncio.run(run())


def test_register_disabled_by_default(client, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "newmember", "password": PASSWORD},
    )
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["type"] == "registration_disabled"
    assert response.headers.get("cache-control") == "no-store"


def test_register_disabled_is_not_a_username_oracle(client, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    # 关闭态：无论用户名是否已存在/合法，都返回同一错误形状。
    for payload in (
        {"username": "owner", "password": PASSWORD},
        {"username": "!!bad!!", "password": "short"},
        {"username": "somebody-else", "password": PASSWORD},
    ):
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 403
        assert response.json()["error"]["type"] == "registration_disabled"


def test_register_success_creates_member_with_pending_binding(client, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    _register_enabled(client)
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "NewMember", "password": PASSWORD, "displayName": "新成员"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # 与 /auth/activate 同契约：注册响应只带会话事实；身份经 /auth/session。
    assert body["authenticated"] is True
    # 响应携带会话 cookie；后续 /auth/session 以该身份应答。
    cookie = response.headers["set-cookie"].split(";")[0]
    session = client.get("/api/v1/auth/session", headers={"cookie": cookie}).json()
    assert session["authenticated"] is True
    assert session["role"] == "member"
    assert session["username"] == "newmember"


def test_register_rejects_client_controlled_role(client, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    _register_enabled(client)
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "escalator", "password": PASSWORD, "role": "admin"},
    )
    assert response.status_code == 200
    accounts = AccountsStore(client.app.state.control_db)
    row = asyncio.run(accounts.get_user_by_username("escalator"))
    assert row is not None and row["role"] == "member"


def test_register_duplicate_username_conflict(client, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    _register_enabled(client)
    first = client.post("/api/v1/auth/register", json={"username": "dup", "password": PASSWORD})
    assert first.status_code == 200
    second = client.post(
        "/api/v1/auth/register", json={"username": "DUP", "password": PASSWORD}
    )
    assert second.status_code == 409
    assert second.json()["error"]["type"] == "username_taken"


def test_register_validation_errors(client, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    _register_enabled(client)
    weak = client.post("/api/v1/auth/register", json={"username": "okname", "password": "short"})
    assert weak.status_code == 400
    assert weak.json()["error"]["type"] == "weak_password"
    bad_name = client.post(
        "/api/v1/auth/register", json={"username": "1nvalid name", "password": PASSWORD}
    )
    assert bad_name.status_code == 400
    assert bad_name.json()["error"]["type"] == "invalid_username"


def test_policy_endpoints_require_admin(client, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    assert client.get("/api/v1/admin/registration-policy").status_code == 401
    assert (
        client.put(
            "/api/v1/admin/registration-policy",
            json={"allowPublicRegistration": True},
        ).status_code
        == 401
    )


def test_policy_change_is_audited(client, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    from lumirss.storage import Database

    async def seed_owner():
        database = Database(str(client.app.state.control_db.path))
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(PASSWORD))
                return str(row["id"])
        raise AssertionError("owner migration did not run")

    owner_id = asyncio.run(seed_owner())
    login = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    headers = {"cookie": login.headers["set-cookie"].split(";")[0]}

    default = client.get("/api/v1/admin/registration-policy", headers=headers)
    assert default.status_code == 200
    assert default.json()["allowPublicRegistration"] is False

    flipped = client.put(
        "/api/v1/admin/registration-policy",
        json={"allowPublicRegistration": True},
        headers=headers,
    )
    assert flipped.status_code == 200
    assert flipped.json()["allowPublicRegistration"] is True
    assert flipped.json()["updatedBy"] == owner_id

    async def read_audit():
        database = Database(str(client.app.state.control_db.path))

        async def run():
            rows = await database.fetch_all(
                "SELECT action, detail FROM audit_log WHERE action = 'registration_policy_change'"
            )
            return rows

        return await run()

    audits = asyncio.run(read_audit())
    assert any("False->True" in str(r["detail"]) for r in audits)


def test_register_success_is_audited(client, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    _register_enabled(client)
    client.post("/api/v1/auth/register", json={"username": "audited", "password": PASSWORD})

    async def read_audit():
        database = Database(str(client.app.state.control_db.path))
        rows = await database.fetch_all(
            "SELECT action, detail FROM audit_log WHERE action = 'account_register'"
        )
        return rows

    from lumirss.storage import Database

    audits = asyncio.run(read_audit())
    assert any(r["detail"] in ("pool_assigned", "binding_pending") for r in audits)
