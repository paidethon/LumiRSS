"""N191 用户额度策略包 — admin set/clear + 服务端执行 + 成员不可自助提升。

覆盖：
- 策略端点：GET/PUT/DELETE /admin/users/{id}/quota；member 403；未知
  用户 404；非法上限（0/负数/超大）→ 400/422；
- 订阅执行：maxSources=2 时第 3 个来源 → 429 quota_exceeded（上游
  FreshRSS 零请求）；提高上限后同一请求成功；清除策略后恢复；
- 「新会话同样拦截」：重登后的会话依旧被服务端拦截（执行不在会话侧）；
- AI 配额合成：管理员 aiQuotaPerDay 与成员自设取更低者；成员未配置时
  管理员上限单独生效；GET /settings/ai/quota 如实反映有效口径；
- 审计：user_quota_set / user_quota_cleared 落 audit_log。
"""

import asyncio
import secrets as _secrets
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app

PASSWORD = "quota-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"


class _StubSubscribeAdapter:
    """订阅替身：记录调用次数——429 时必须为零请求。"""

    def __init__(self) -> None:
        self.calls = 0

    async def subscribe(self, feed_url, category_id=None, title=None):
        self.calls += 1
        return SimpleNamespace(
            subscription_ref=f"ref/{self.calls}",
            title="stub",
            feed_url=feed_url,
            category_id=None,
            category_label=None,
        )


@pytest.fixture()
def quota_env(monkeypatch, tmp_path):
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
        owner_headers = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = client.post(
            "/api/v1/admin/invites", json={"label": A_USER}, headers=owner_headers
        )
        assert invite.status_code == 200, invite.text
        activation = client.post(
            "/api/v1/auth/activate",
            json={"token": invite.json()["token"], "username": A_USER, "password": PASSWORD},
        )
        assert activation.status_code == 200, activation.text
        alice_headers = {"cookie": activation.headers["set-cookie"].split(";")[0]}
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        ids = {row["username"]: row["id"] for row in users}
        yield {
            "client": client,
            "owner": owner_headers,
            "alice": alice_headers,
            "ids": ids,
            "db_path": tmp_path,
            "stub": _StubSubscribeAdapter(),
        }
        app.state.freshrss_control_adapter = None


def _set_owner_password(db_path) -> None:
    async def run():
        from lumirss.storage import Database

        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(PASSWORD))
                return
        raise AssertionError("owner migration did not run")

    asyncio.run(run())


def _seed_projection_feeds(env, username: str, count: int) -> None:
    """直接向该成员的用户库投影写入 N 行 search_feeds（订阅计数口径）。"""

    async def run():
        from lumirss.storage import Database

        uid = env["ids"][username]
        database = Database(env["db_path"] / "users" / uid / "lumi.sqlite")
        await database.migrate()
        for i in range(count):
            await database.execute(
                "INSERT OR REPLACE INTO search_feeds (feed_url, feed_title, category_id, refreshed_at)"
                " VALUES (?, ?, NULL, 0)",
                (f"https://example.test/feed-{i}.xml", f"feed-{i}"),
            )

    asyncio.run(run())


def _put_quota(env, who: str, user_id: str, body: dict):
    return env["client"].put(
        f"/api/v1/admin/users/{user_id}/quota", json=body, headers={"cookie": env[who]["cookie"]}
    )


def _subscribe(env, who: str, url: str):
    return env["client"].post(
        "/api/v1/subscriptions",
        json={"feedUrl": url},
        headers={"cookie": env[who]["cookie"]},
    )


# ---- 端点基础行为 ------------------------------------------------------------


def test_member_gets_403_on_quota_endpoints(quota_env):
    env = quota_env
    member_id = env["ids"][A_USER]
    get_response = env["client"].get(
        f"/api/v1/admin/users/{member_id}/quota", headers=env["alice"]
    )
    assert get_response.status_code == 403
    assert get_response.json()["error"]["type"] == "forbidden"
    put_response = env["client"].put(
        f"/api/v1/admin/users/{member_id}/quota",
        json={"maxSources": 5},
        headers=env["alice"],
    )
    assert put_response.status_code == 403
    assert put_response.json()["error"]["type"] == "forbidden"
    delete_response = env["client"].delete(
        f"/api/v1/admin/users/{member_id}/quota", headers=env["alice"]
    )
    assert delete_response.status_code == 403
    assert delete_response.json()["error"]["type"] == "forbidden"


def test_unknown_user_404(quota_env):
    env = quota_env
    response = _put_quota(env, "owner", "u00000000000000000000000000000000", {"maxSources": 5})
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "user_not_found"


def test_set_get_clear_roundtrip_and_audit(quota_env):
    env = quota_env
    member_id = env["ids"][A_USER]
    set_response = _put_quota(env, "owner", member_id, {"maxSources": 7, "aiQuotaPerDay": 9})
    assert set_response.status_code == 200, set_response.text
    body = set_response.json()
    assert body["caps"] == {"maxSources": 7, "aiQuotaPerDay": 9}
    assert body["backgroundPaused"] is False
    assert body["updatedBy"] == env["ids"][OWNER_USER]

    get_response = env["client"].get(
        f"/api/v1/admin/users/{member_id}/quota", headers=env["owner"]
    )
    assert get_response.status_code == 200
    assert get_response.json()["caps"] == {"maxSources": 7, "aiQuotaPerDay": 9}

    clear_response = env["client"].delete(
        f"/api/v1/admin/users/{member_id}/quota", headers=env["owner"]
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["caps"] == {}
    audit = env["client"].get("/api/v1/admin/audit?limit=50", headers=env["owner"]).json()
    actions = {row["action"] for row in audit}
    assert "user_quota_set" in actions and "user_quota_cleared" in actions


def test_invalid_caps_rejected(quota_env):
    env = quota_env
    member_id = env["ids"][A_USER]
    for body in ({"maxSources": 0}, {"maxSources": -3}, {"aiQuotaPerDay": 10**7}):
        response = _put_quota(env, "owner", member_id, body)
        assert response.status_code in (400, 422), body


# ---- 订阅执行 ----------------------------------------------------------------


def test_cap_blocks_n_plus_1th_source_upstream_untouched(quota_env):
    env = quota_env
    member_id = env["ids"][A_USER]
    assert _put_quota(env, "owner", member_id, {"maxSources": 2}).status_code == 200
    _seed_projection_feeds(env, A_USER, 2)
    app.state.freshrss_control_adapter = env["stub"]

    blocked = _subscribe(env, "alice", "https://example.test/feed-new.xml")
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error"]["type"] == "quota_exceeded"
    assert blocked.json()["error"]["maxSources"] == 2
    assert blocked.json()["error"]["current"] == 2
    assert env["stub"].calls == 0, "超额订阅绝不触碰上游 FreshRSS"


def test_raising_cap_lets_the_same_subscribe_through(quota_env):
    env = quota_env
    member_id = env["ids"][A_USER]
    _put_quota(env, "owner", member_id, {"maxSources": 2})
    _seed_projection_feeds(env, A_USER, 2)
    app.state.freshrss_control_adapter = env["stub"]
    assert _subscribe(env, "alice", "https://example.test/feed-new.xml").status_code == 429

    _put_quota(env, "owner", member_id, {"maxSources": 3})
    allowed = _subscribe(env, "alice", "https://example.test/feed-new.xml")
    assert allowed.status_code in (200, 201), allowed.text
    assert env["stub"].calls == 1


def test_clear_quota_restores_subscribe(quota_env):
    env = quota_env
    member_id = env["ids"][A_USER]
    _put_quota(env, "owner", member_id, {"maxSources": 1})
    _seed_projection_feeds(env, A_USER, 2)
    app.state.freshrss_control_adapter = env["stub"]
    assert _subscribe(env, "alice", "https://example.test/feed-new.xml").status_code == 429

    env["client"].delete(f"/api/v1/admin/users/{member_id}/quota", headers=env["owner"])
    allowed = _subscribe(env, "alice", "https://example.test/feed-new.xml")
    assert allowed.status_code in (200, 201), allowed.text


def test_new_session_same_block(quota_env):
    """重登后的新会话依旧被拦截——执行在服务端策略上，不在会话侧。"""
    env = quota_env
    member_id = env["ids"][A_USER]
    _put_quota(env, "owner", member_id, {"maxSources": 2})
    _seed_projection_feeds(env, A_USER, 2)
    app.state.freshrss_control_adapter = env["stub"]
    assert _subscribe(env, "alice", "https://example.test/feed-new.xml").status_code == 429

    fresh_login = env["client"].post(
        "/api/v1/auth/login", json={"username": A_USER, "password": PASSWORD}
    )
    assert fresh_login.status_code == 200, fresh_login.text
    env["alice"] = {"cookie": fresh_login.headers["set-cookie"].split(";")[0]}
    assert _subscribe(env, "alice", "https://example.test/feed-new.xml").status_code == 429
    assert env["stub"].calls == 0


# ---- AI 配额合成 --------------------------------------------------------------


def _set_member_ai_quota(env, username: str, window: str, max_calls: int) -> None:
    """以成员身份写自设 AI 配额（走 AiSettingsStore.save 的真实路径）。"""

    async def run():
        from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
        from lumirss.storage import Database
        from lumirss.user_scope import user_context

        uid = env["ids"][username]
        database = Database(env["db_path"] / "users" / uid / "lumi.sqlite")
        await database.migrate()
        with user_context(uid):
            await AiSettingsStore(database).save(
                AiSettingsUpdate(quotaWindow=window, quotaMaxCalls=str(max_calls))
            )

    asyncio.run(run())


def test_admin_ai_cap_overrides_lower_user_setting(quota_env):
    env = quota_env
    member_id = env["ids"][A_USER]
    _set_member_ai_quota(env, A_USER, "day", 10)
    assert _put_quota(env, "owner", member_id, {"aiQuotaPerDay": 3}).status_code == 200
    snapshot = env["client"].get("/api/v1/settings/ai/quota", headers=env["alice"]).json()
    assert snapshot["maxCalls"] == 3, snapshot


def test_admin_ai_cap_applies_when_member_unconfigured(quota_env):
    env = quota_env
    member_id = env["ids"][A_USER]
    assert _put_quota(env, "owner", member_id, {"aiQuotaPerDay": 5}).status_code == 200
    snapshot = env["client"].get("/api/v1/settings/ai/quota", headers=env["alice"]).json()
    assert snapshot["maxCalls"] == 5
    assert snapshot["window"] == "day"


def test_member_lower_setting_wins_over_higher_admin_cap(quota_env):
    env = quota_env
    member_id = env["ids"][A_USER]
    _set_member_ai_quota(env, A_USER, "day", 2)
    assert _put_quota(env, "owner", member_id, {"aiQuotaPerDay": 8}).status_code == 200
    snapshot = env["client"].get("/api/v1/settings/ai/quota", headers=env["alice"]).json()
    assert snapshot["maxCalls"] == 2
