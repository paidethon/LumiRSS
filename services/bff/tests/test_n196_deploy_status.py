"""N196 升级任务进度 — GET /admin/deploy-status 只读透传 lumirss 阶段 JSON。

覆盖：
- LUMIRSS_DEPLOY_STATUS_FILE 未配置 → available:false + 诚实 reason；
- 文件不存在（尚无升级）→ available:false；
- 有效阶段文件（脚本契约形状）→ available:true 且内容原样透传
  （stages/result/imageTag/时间戳）；坏 JSON / schema 不符 → 诚实拒绝；
- member 403。脚本写入端的行为在 tests/deploy/run-deploy-tests.sh 里
  以 stub docker 全链路验证（本套件只测 BFF 读取面）。
"""

import asyncio
import json
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app
from lumirss.storage import Database

PASSWORD = "dep-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"

STATUS_SCHEMA = "lumirss-deploy-status/v1"


@pytest.fixture()
def deploy_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_DEPLOY_STATUS_FILE", "")  # 显式未配置起点
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
        yield {
            "client": client,
            "owner": owner_headers,
            "alice": {"cookie": activation.headers["set-cookie"].split(";")[0]},
            "db_path": tmp_path,
        }


def _set_owner_password(db_path) -> None:
    async def run():
        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        for row in await AccountsStore(database).list_users(limit=50):
            if row["role"] == "owner":
                await AccountsStore(database).set_password_hash(str(row["id"]), hash_password(PASSWORD))
                return
        raise AssertionError("owner migration did not run")

    asyncio.run(run())


def _status_payload() -> dict:
    """./lumirss update 成功完成后应有的文件形状（脚本契约）。"""
    return {
        "schema": STATUS_SCHEMA,
        "command": "update",
        "imageTag": "abc1234cafe",
        "startedAt": "2026-09-25T08:00:00Z",
        "updatedAt": "2026-09-25T08:03:00Z",
        "stages": {
            "backup": {"status": "ok", "startedAt": "2026-09-25T08:00:00Z", "finishedAt": "2026-09-25T08:01:00Z"},
            "pull": {"status": "ok", "startedAt": "2026-09-25T08:01:00Z", "finishedAt": "2026-09-25T08:02:00Z"},
            "migrate": {
                "status": "ok",
                "startedAt": "2026-09-25T08:02:00Z",
                "finishedAt": "2026-09-25T08:02:30Z",
                "note": "containers recreated; the BFF applies SQLite migrations at startup",
            },
            "health": {"status": "ok", "startedAt": "2026-09-25T08:02:30Z", "finishedAt": "2026-09-25T08:03:00Z"},
        },
        "result": {"status": "success", "finishedAt": "2026-09-25T08:03:00Z"},
    }


def _get(env):
    response = env["client"].get("/api/v1/admin/deploy-status", headers=env["owner"])
    assert response.status_code == 200, response.text
    return response.json()


def test_unconfigured_is_honest(deploy_env):
    env = deploy_env
    data = _get(env)
    assert data["available"] is False
    assert "LUMIRSS_DEPLOY_STATUS_FILE" in data["reason"]
    assert data["deploy"] is None


def test_missing_file_means_no_update_yet(deploy_env, monkeypatch):
    env = deploy_env
    monkeypatch.setenv("LUMIRSS_DEPLOY_STATUS_FILE", str(env["db_path"] / "nope.json"))
    data = _get(env)
    assert data["available"] is False
    assert "No update has run yet" in data["reason"]


def test_valid_status_file_is_passed_through(deploy_env, monkeypatch):
    env = deploy_env
    path = env["db_path"] / "deploy-status.json"
    path.write_text(json.dumps(_status_payload()), encoding="utf-8")
    monkeypatch.setenv("LUMIRSS_DEPLOY_STATUS_FILE", str(path))
    data = _get(env)
    assert data["available"] is True
    deploy = data["deploy"]
    assert deploy["schema"] == STATUS_SCHEMA
    assert deploy["imageTag"] == "abc1234cafe"
    assert set(deploy["stages"]) == {"backup", "pull", "migrate", "health"}
    assert all(stage["status"] == "ok" for stage in deploy["stages"].values())
    assert deploy["result"]["status"] == "success"


def test_broken_files_are_refused_honestly(deploy_env, monkeypatch):
    env = deploy_env
    bad_json = env["db_path"] / "bad.json"
    bad_json.write_text("{oops", encoding="utf-8")
    monkeypatch.setenv("LUMIRSS_DEPLOY_STATUS_FILE", str(bad_json))
    assert _get(env)["available"] is False

    wrong_schema = env["db_path"] / "wrong.json"
    wrong_schema.write_text(json.dumps({"schema": "other/v1", "stages": {}}), encoding="utf-8")
    monkeypatch.setenv("LUMIRSS_DEPLOY_STATUS_FILE", str(wrong_schema))
    data = _get(env)
    assert data["available"] is False
    assert "schema" in data["reason"]


def test_member_403(deploy_env):
    env = deploy_env
    response = env["client"].get("/api/v1/admin/deploy-status", headers=env["alice"])
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "forbidden"
