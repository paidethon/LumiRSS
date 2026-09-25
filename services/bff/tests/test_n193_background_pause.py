"""N193 单用户后台任务暂停 — background_paused 标志 + 后台循环跳过 + 审计。

覆盖：
- 后台暂停后，active_user_ids()（所有 for_each_active_user 循环的
  唯一用户来源）不再包含该成员——for_each_active_user 的记录函数
  收不到他的 uid（重型工作被源头跳过）；
- 登录与阅读不受影响：暂停后该成员的既有会话仍然有效、能正常读；
- 恢复后 active_user_ids() 重新包含；暂停原因随恢复清空；
- admin pause/resume 落 audit_log（含人读原因）；
- owner 不可定位（403）；原因必填（422）；member 403。
"""

import asyncio
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app

PASSWORD = "bgp-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"


@pytest.fixture()
def bgp_env(monkeypatch, tmp_path):
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
        invite = client.post(
            "/api/v1/admin/invites", json={"label": A_USER}, headers=owner_headers
        )
        assert invite.status_code == 200, invite.text
        activation = client.post(
            "/api/v1/auth/activate",
            json={"token": invite.json()["token"], "username": A_USER, "password": PASSWORD},
        )
        assert activation.status_code == 200, activation.text
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        ids = {row["username"]: row["id"] for row in users}
        yield {
            "client": client,
            "owner": owner_headers,
            "alice": {"cookie": activation.headers["set-cookie"].split(";")[0]},
            "ids": ids,
            "db_path": tmp_path,
        }


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


def _active_ids(db_path) -> list[str]:
    async def run() -> list[str]:
        from lumirss.storage import Database

        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        return await AccountsStore(database).active_user_ids()

    return asyncio.run(run())


def _pause(env, user_id: str, body=None):
    return env["client"].post(
        f"/api/v1/admin/users/{user_id}/background-pause",
        json=body if body is not None else {"reason": "test pause"},
        headers=env["owner"],
    )


def test_paused_user_iteration_skipped_and_sessions_valid(bgp_env):
    env = bgp_env
    alice_id = env["ids"][A_USER]
    assert alice_id in _active_ids(env["db_path"])

    paused = _pause(env, alice_id, {"reason": "降负载：暂停她的重活"})
    assert paused.status_code == 200, paused.text
    assert paused.json()["backgroundPaused"] is True

    # 后台循环的用户来源不再包含 alice（所有 per-user 重活被源头跳过）。
    assert alice_id not in _active_ids(env["db_path"])

    async def record_uids():
        from types import SimpleNamespace

        from lumirss.storage import Database
        from lumirss.user_scope import for_each_active_user

        database = Database(env["db_path"] / "lumi.sqlite")
        await database.migrate()
        seen: list[str] = []
        await for_each_active_user(
            SimpleNamespace(control_db=database), lambda uid: _capture(seen, uid)
        )
        return seen

    async def _capture(seen, uid):
        seen.append(uid)

    seen = asyncio.run(record_uids())
    assert alice_id not in seen

    # 登录/阅读不受影响：既有会话仍然有效（暂停不撤销会话）。
    reading = env["client"].get("/api/v1/search/views", headers=env["alice"])
    assert reading.status_code == 200, reading.text
    # users.status 未被触碰（整账户暂停是另一件事）。
    users = env["client"].get("/api/v1/admin/users", headers=env["owner"]).json()
    assert next(row for row in users if row["id"] == alice_id)["status"] == "active"


def test_resume_restores_iteration_and_clears_reason(bgp_env):
    env = bgp_env
    alice_id = env["ids"][A_USER]
    assert _pause(env, alice_id, {"reason": "maintenance window"}).status_code == 200
    assert alice_id not in _active_ids(env["db_path"])

    resumed = env["client"].post(
        f"/api/v1/admin/users/{alice_id}/background-resume", headers=env["owner"]
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["backgroundPaused"] is False
    assert alice_id in _active_ids(env["db_path"])

    detail = env["client"].get(
        f"/api/v1/admin/users/{alice_id}/quota", headers=env["owner"]
    ).json()
    assert detail["backgroundPaused"] is False
    assert detail["backgroundPauseReason"] is None


def test_pause_and_resume_are_audited_with_reason(bgp_env):
    env = bgp_env
    alice_id = env["ids"][A_USER]
    _pause(env, alice_id, {"reason": "实验：隔离性能干扰"})
    env["client"].post(f"/api/v1/admin/users/{alice_id}/background-resume", headers=env["owner"])
    audit = env["client"].get("/api/v1/admin/audit?limit=50", headers=env["owner"]).json()
    by_action = {row["action"]: row for row in audit}
    assert "user_background_paused" in by_action
    assert by_action["user_background_paused"]["detail"] == "实验：隔离性能干扰"
    assert by_action["user_background_paused"]["object_id"] == alice_id
    assert "user_background_resumed" in by_action


def test_owner_untargetable_and_reason_required(bgp_env):
    env = bgp_env
    owner_id = env["ids"][OWNER_USER]
    forbidden = _pause(env, owner_id, {"reason": "nope"})
    assert forbidden.status_code == 403
    assert "owner" in forbidden.json()["error"]["message"].lower()
    # 原因必填：缺 body / 空 reason → 422。
    missing = env["client"].post(
        f"/api/v1/admin/users/{env['ids'][A_USER]}/background-pause",
        json={},
        headers=env["owner"],
    )
    assert missing.status_code == 422
    # 未知用户 → 404。
    unknown = _pause(env, "u00000000000000000000000000000000", {"reason": "x"})
    assert unknown.status_code == 404


def test_member_gets_403(bgp_env):
    env = bgp_env
    response = env["client"].post(
        f"/api/v1/admin/users/{env['ids'][A_USER]}/background-pause",
        json={"reason": "self-service"},
        headers=env["alice"],
    )
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "forbidden"
