"""通行密钥（WebAuthn passkeys）— N006。

覆盖真实验证路径（python-fido2 + 软件 authenticator 产生真实结构，
见 _virtual_authenticator.py）：注册（options → 完成并落库）、列表只含
id/label/时间戳、登录（options allowCredentials → 断言 → 会话 Cookie）、
以及全部负路径：错误 origin、重放挑战、克隆 authenticator（计数回退）、
过期挑战、未知用户名的诚实通用响应（无账号枚举）、删除需密码、
共享登录限流、跨用户 404。
"""

import asyncio
import secrets as _secrets
import time

import pytest
from fastapi.testclient import TestClient

import lumirss.middleware as middleware
from _virtual_authenticator import VirtualAuthenticator
from lumirss.main import app
from lumirss.storage import Database

PASSWORD = _secrets.token_urlsafe(12)
ORIGIN = "http://lumirss.test"
RP_ID = "lumirss.test"


@pytest.fixture()
def session_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    return tmp_path


def _install_password(db_path) -> None:
    """Legacy auth_password row → inherited by the startup owner migration
    (exactly the production upgrade path; same shape as test_auth_sessions)."""
    from lumirss.auth_store import AuthStore

    database = Database(db_path / "lumi.sqlite")

    async def run():
        await database.migrate()
        await AuthStore(database).set_password(PASSWORD)

    asyncio.run(run())


def _login(client: TestClient, username: str = "owner", password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


@pytest.fixture()
def logged_in(session_env):
    _install_password(session_env)
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        response = _login(client)
        assert response.status_code == 200, response.text
        yield client


def register_passkey(client: TestClient, label: str = "笔记本") -> tuple[dict, VirtualAuthenticator]:
    """Full real registration ceremony; returns (row, authenticator)."""
    options = client.post("/api/v1/auth/passkeys/options", json={})
    assert options.status_code == 200, options.text
    payload = options.json()
    assert payload["publicKey"]["rp"]["id"] == RP_ID
    authenticator = VirtualAuthenticator(origin=ORIGIN, rp_id=RP_ID)
    registration = authenticator.make_registration(payload["challenge"])
    done = client.post(
        "/api/v1/auth/passkeys",
        json={"label": label, "challenge": payload["challenge"], **registration},
    )
    assert done.status_code == 200, done.text
    row = done.json()
    assert row["label"] == label
    assert row["lastUsedAt"] is None
    return row, authenticator


def passkey_login(client: TestClient, authenticator: VirtualAuthenticator, username: str = "owner", **kwargs):
    options = client.post(
        "/api/v1/auth/passkeys/login/options", json={"username": username}
    )
    assert options.status_code == 200, options.text
    payload = options.json()
    assertion = authenticator.make_assertion(payload["challenge"], **kwargs)
    return client.post(
        "/api/v1/auth/passkeys/login",
        json={
            "username": username,
            "challenge": payload["challenge"],
            **assertion,
        },
    )


# ---- 注册 -----------------------------------------------------------------


def test_register_roundtrip_lists_only_safe_fields(logged_in):
    row, _auth = register_passkey(logged_in, label="我的钥匙")
    listing = logged_in.get("/api/v1/auth/passkeys")
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    assert items[0]["id"] == row["id"]
    assert items[0]["label"] == "我的钥匙"
    # 绝不回传密钥材料 / 计数器。
    for forbidden in ("publicKey", "public_key", "signCount", "sign_count", "userId", "user_id"):
        assert forbidden not in items[0]


def test_register_options_exclude_existing_credentials(logged_in):
    row, _auth = register_passkey(logged_in)
    second = logged_in.post("/api/v1/auth/passkeys/options", json={})
    exclude = second.json()["publicKey"].get("excludeCredentials") or []
    assert any(item["id"] == row["id"] for item in exclude)


def test_register_replayed_challenge_rejected(logged_in):
    options = logged_in.post("/api/v1/auth/passkeys/options", json={})
    payload = options.json()
    auth = VirtualAuthenticator(origin=ORIGIN, rp_id=RP_ID)
    registration = auth.make_registration(payload["challenge"])
    body = {"label": "钥匙", "challenge": payload["challenge"], **registration}
    first = logged_in.post("/api/v1/auth/passkeys", json=body)
    assert first.status_code == 200
    replay = logged_in.post("/api/v1/auth/passkeys", json=body)
    assert replay.status_code == 400
    assert replay.json()["error"]["type"] == "challenge_invalid"
    assert len(logged_in.get("/api/v1/auth/passkeys").json()) == 1


def test_register_bad_origin_rejected(logged_in):
    options = logged_in.post("/api/v1/auth/passkeys/options", json={})
    payload = options.json()
    # Authenticator claims a DIFFERENT origin than the RP served by the host.
    auth = VirtualAuthenticator(origin="http://evil.example", rp_id=RP_ID)
    registration = auth.make_registration(payload["challenge"])
    done = logged_in.post(
        "/api/v1/auth/passkeys",
        json={"label": "x", "challenge": payload["challenge"], **registration},
    )
    assert done.status_code == 400
    assert done.json()["error"]["type"] == "verification_failed"


def test_register_garbage_response_rejected(logged_in):
    options = logged_in.post("/api/v1/auth/passkeys/options", json={})
    payload = options.json()

    def attempt(raw_id: str, client_data: str):
        return logged_in.post(
            "/api/v1/auth/passkeys",
            json={
                "label": "x",
                "challenge": payload["challenge"],
                "id": raw_id,
                "rawId": raw_id,
                "type": "public-key",
                "response": {
                    "clientDataJSON": client_data,
                    "attestationObject": "AAAA",
                },
            },
        )

    # 长度足够的垃圾内容 → fido2 验证失败的稳定 400；
    # 形状不合法的 id → 422 边界校验（到不了验证路径）。
    unparseable = attempt(
        _secrets.token_urlsafe(16), _secrets.token_urlsafe(16)
    )
    assert unparseable.status_code == 400
    assert unparseable.json()["error"]["type"] == "verification_failed"
    short = attempt("AAAA", "AAAA")
    assert short.status_code == 422
    # 挑战已被烧掉：修好内容也不能复用同一挑战。
    auth = VirtualAuthenticator(origin=ORIGIN, rp_id=RP_ID)
    retry = logged_in.post(
        "/api/v1/auth/passkeys",
        json={
            "label": "x",
            "challenge": payload["challenge"],
            **auth.make_registration(payload["challenge"]),
        },
    )
    assert retry.status_code == 400
    assert retry.json()["error"]["type"] == "challenge_invalid"


# ---- 登录 -----------------------------------------------------------------


def test_login_full_flow_mints_working_session(session_env):
    _install_password(session_env)
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(client).status_code == 200
        _row, auth = register_passkey(client)
        client.post("/api/v1/auth/logout")  # password session revoked
        assert client.get("/api/v1/settings").status_code == 401
        response = passkey_login(client, auth)
        assert response.status_code == 200, response.text
        assert response.json()["authenticated"] is True
        # Same cookie flow as password login → protected routes work.
        assert client.get("/api/v1/settings").status_code == 200
        listing = client.get("/api/v1/auth/passkeys").json()
        assert listing[0]["lastUsedAt"] is not None


def test_login_options_unknown_username_is_generic(logged_in):
    known_no_keys = logged_in.post(
        "/api/v1/auth/passkeys/login/options", json={"username": "owner"}
    ).json()
    unknown = logged_in.post(
        "/api/v1/auth/passkeys/login/options", json={"username": _secrets.token_hex(6)}
    ).json()
    assert set(unknown) == set(known_no_keys)
    assert unknown["passkeyAvailable"] is False
    assert unknown["publicKey"]["allowCredentials"] in (None, [])
    # 已注册用户 → honest available + allowCredentials 指向其凭据。
    register_passkey(logged_in)
    available = logged_in.post(
        "/api/v1/auth/passkeys/login/options", json={"username": "owner"}
    ).json()
    assert available["passkeyAvailable"] is True
    assert len(available["publicKey"]["allowCredentials"]) == 1


def test_login_wrong_origin_rejected(logged_in):
    _row, auth = register_passkey(logged_in)
    response = passkey_login(logged_in, auth, origin="http://evil.example")
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "invalid_credentials"


def test_login_replayed_challenge_rejected(logged_in):
    _row, auth = register_passkey(logged_in)
    options = logged_in.post(
        "/api/v1/auth/passkeys/login/options", json={"username": "owner"}
    ).json()
    assertion = auth.make_assertion(options["challenge"])
    body = {"username": "owner", "challenge": options["challenge"], **assertion}
    first = logged_in.post("/api/v1/auth/passkeys/login", json=body)
    assert first.status_code == 200
    replay = logged_in.post("/api/v1/auth/passkeys/login", json=body)
    assert replay.status_code == 401
    assert replay.json()["error"]["type"] == "invalid_credentials"


def test_login_cloned_authenticator_counter_regression_rejected(logged_in):
    _row, auth = register_passkey(logged_in)
    first = passkey_login(logged_in, auth)  # counter 1
    assert first.status_code == 200
    second = passkey_login(logged_in, auth)  # counter 2
    assert second.status_code == 200
    # Cloned device: a copied credential asserts with an OLD counter.
    clone = passkey_login(logged_in, auth, counter=1)
    assert clone.status_code == 401
    assert clone.json()["error"]["type"] == "invalid_credentials"
    # The REAL device (monotonic counter) still works.
    assert passkey_login(logged_in, auth).status_code == 200


def test_login_bad_signature_rejected(logged_in):
    _row, auth = register_passkey(logged_in)
    response = passkey_login(logged_in, auth, corrupt_signature=True)
    assert response.status_code == 401


def test_login_expired_challenge_rejected(logged_in):
    _row, auth = register_passkey(logged_in)
    options = logged_in.post(
        "/api/v1/auth/passkeys/login/options", json={"username": "owner"}
    ).json()

    async def expire():
        db = Database(logged_in.app.state.control_db.path)
        await db.migrate()
        await db.execute("UPDATE webauthn_challenges SET expires_at = 1", ())

    asyncio.run(expire())
    assertion = auth.make_assertion(options["challenge"])
    response = logged_in.post(
        "/api/v1/auth/passkeys/login",
        json={"username": "owner", "challenge": options["challenge"], **assertion},
    )
    assert response.status_code == 401


def test_login_other_users_credential_rejected(session_env):
    """Challenge bound to owner (allowCredentials) + member's credential
    must fail — the server enforces the binding the browser only hints."""
    from lumirss.accounts_store import AccountsStore, hash_password

    database = Database(session_env / "lumi.sqlite")

    async def create_member():
        await database.migrate()
        await AccountsStore(database).create_user(
            username="member1", password_hash=hash_password(PASSWORD), role="member"
        )

    asyncio.run(create_member())
    _install_password(session_env)
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(client).status_code == 200
        register_passkey(client)
        client.post("/api/v1/auth/logout")
        # Log in as the member, register their own authenticator.
        assert _login(client, username="member1").status_code == 200
        _mrow, member_auth = register_passkey(client, label="成员钥匙")
        client.post("/api/v1/auth/logout")
        # Owner's challenge + member's credential → rejected.
        response = passkey_login(client, member_auth, username="owner")
        assert response.status_code == 401
        # Member's own challenge + member's credential → fine.
        assert passkey_login(client, member_auth, username="member1").status_code == 200


def test_login_rate_limit_shared_with_password(logged_in):
    _row, auth = register_passkey(logged_in)
    for _ in range(middleware.LOGIN_FAILURE_LIMIT):
        failed = passkey_login(logged_in, auth, corrupt_signature=True)
        assert failed.status_code == 401
    throttled = passkey_login(logged_in, auth)
    assert throttled.status_code == 429
    assert throttled.json()["error"]["type"] == "rate_limited"
    # 密码登录共享同一预算。
    password_login = _login(logged_in)
    assert password_login.status_code == 429


# ---- 删除 -----------------------------------------------------------------


def test_delete_requires_current_password(logged_in):
    row, _auth = register_passkey(logged_in)
    wrong = logged_in.request(
        "DELETE",
        f"/api/v1/auth/passkeys/{row['id']}",
        json={"currentPassword": _secrets.token_urlsafe(9)},
    )
    assert wrong.status_code == 401
    ok = logged_in.request(
        "DELETE", f"/api/v1/auth/passkeys/{row['id']}", json={"currentPassword": PASSWORD}
    )
    assert ok.status_code == 204
    assert logged_in.get("/api/v1/auth/passkeys").json() == []


def test_delete_other_users_credential_is_404(session_env):
    from lumirss.accounts_store import AccountsStore, hash_password

    database = Database(session_env / "lumi.sqlite")

    async def create_member():
        await database.migrate()
        await AccountsStore(database).create_user(
            username="member2", password_hash=hash_password(PASSWORD), role="member"
        )

    asyncio.run(create_member())
    _install_password(session_env)
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert _login(client).status_code == 200
        row, _auth = register_passkey(client)
        client.post("/api/v1/auth/logout")
        assert _login(client, username="member2").status_code == 200
        stolen = client.request(
            "DELETE",
            f"/api/v1/auth/passkeys/{row['id']}",
            json={"currentPassword": PASSWORD},
        )
        assert stolen.status_code == 404
        assert stolen.json()["error"]["type"] == "passkey_not_found"


# ---- 模式/会话门槛 -----------------------------------------------------------


def test_session_required_without_cookie(session_env):
    _install_password(session_env)
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.db = Database(session_env / "lumi.sqlite")
        assert client.get("/api/v1/auth/passkeys").status_code == 401
        assert client.post("/api/v1/auth/passkeys/options", json={}).status_code == 401
        # 公共登录面仍可达（诚实通用响应）。
        options = client.post(
            "/api/v1/auth/passkeys/login/options", json={"username": "owner"}
        )
        assert options.status_code == 200
        assert options.json()["passkeyAvailable"] is False


def test_expired_challenges_purged_on_next_options(logged_in):
    logged_in.post("/api/v1/auth/passkeys/options", json={})

    async def stale_count():
        db = Database(logged_in.app.state.control_db.path)
        await db.migrate()
        await db.execute(
            "INSERT INTO webauthn_challenges (challenge, user_id, purpose, expires_at) VALUES ('stale', '', 'login', 1)",
            (),
        )

    asyncio.run(stale_count())
    logged_in.post("/api/v1/auth/passkeys/options", json={})

    async def remaining():
        db = Database(logged_in.app.state.control_db.path)
        await db.migrate()
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM webauthn_challenges WHERE expires_at <= ?",
            (int(time.time()),),
        )
        return row["n"]

    assert asyncio.run(remaining()) == 0
