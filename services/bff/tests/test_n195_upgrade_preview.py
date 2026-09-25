"""N195 升级影响预览 — GET /admin/upgrade-preview 只读推演。

覆盖：
- LUMIRSS_RELEASE_MANIFEST 未配置 → available:false + 诚实 reason；
- 文件缺失 / 坏 JSON / schema 不符 → available:false；
- 有效清单（fixture）：available:true、currentVersion/targetVersion、
  newMigrations 只含本地未应用的迁移、minCompat 透传；
- 不兼容阻断：目标 == 当前（nothing to upgrade）、目标 < 当前（降级）、
  数据库超前于目标（applied ⊄ target migrations）→ blocked:true+reason；
- member 403。
"""

import asyncio
import json
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app
from lumirss.storage import Database

PASSWORD = "prev-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"
CURRENT_VERSION = "0.2.0"


@pytest.fixture()
def preview_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_RELEASE_MANIFEST", "")  # 显式无清单起点
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


def _write_manifest(env, payload: dict | str) -> str:
    path = env["db_path"] / "release-manifest.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _manifest(version: str, migrations: list[str], min_compat: str | None = None) -> dict:
    return {
        "schema": "lumirss-release-manifest/v1",
        "name": "LumiRSS",
        "version": version,
        "images": {"bff": "ghcr.io/x/bff@sha256:a", "web": "ghcr.io/x/web@sha256:b"},
        "migrations": migrations,
        "min_compat": min_compat,
    }


def _preview(env):
    response = env["client"].get("/api/v1/admin/upgrade-preview", headers=env["owner"])
    assert response.status_code == 200, response.text
    return response.json()


def test_unconfigured_manifest_is_honestly_unavailable(preview_env):
    env = preview_env
    data = _preview(env)
    assert data["available"] is False
    assert data["reason"] is not None and "LUMIRSS_RELEASE_MANIFEST" in data["reason"]
    assert data["targetVersion"] is None
    assert data["newMigrations"] == []
    assert data["blocked"] is False


def _applied_versions(db_path) -> set[int]:
    async def run() -> set[int]:
        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        rows = await database.fetch_all("SELECT version FROM schema_migrations", ())
        return {int(row["version"]) for row in rows}

    return asyncio.run(run())


def test_valid_manifest_shows_target_and_new_migrations(preview_env, monkeypatch):
    env = preview_env
    # 目标树迁移清单 = 全量（CI 枚举整个 migrations 目录）：本地已应用的
    # 全部版本 + 9999（目标新增）。
    target_migrations = [f"{version:04d}_step.sql" for version in sorted(_applied_versions(env["db_path"]))]
    target_migrations.append("9999_future.sql")
    path = _write_manifest(
        env,
        _manifest("0.3.0", target_migrations, min_compat="0.1.0"),
    )
    monkeypatch.setenv("LUMIRSS_RELEASE_MANIFEST", path)
    data = _preview(env)
    assert data["available"] is True
    assert data["currentVersion"] == CURRENT_VERSION
    assert data["targetVersion"] == "0.3.0"
    assert data["newMigrations"] == ["9999_future.sql"]
    assert data["minCompat"] == "0.1.0"
    assert data["blocked"] is False


def test_same_version_is_blocked(preview_env, monkeypatch):
    env = preview_env
    monkeypatch.setenv(
        "LUMIRSS_RELEASE_MANIFEST",
        _write_manifest(env, _manifest(CURRENT_VERSION, [])),
    )
    data = _preview(env)
    assert data["available"] is True
    assert data["blocked"] is True
    assert data["blockedReason"] is not None
    assert "equals" in data["blockedReason"] or "same" in data["blockedReason"].lower()


def test_downgrade_target_is_blocked(preview_env, monkeypatch):
    env = preview_env
    monkeypatch.setenv(
        "LUMIRSS_RELEASE_MANIFEST",
        _write_manifest(env, _manifest("0.1.0", [])),
    )
    data = _preview(env)
    assert data["blocked"] is True
    assert "rollback" in data["blockedReason"].lower() or "older" in data["blockedReason"].lower()


def test_database_ahead_of_target_is_blocked(preview_env, monkeypatch):
    env = preview_env
    # 目标清单只带 0001：本地已应用 0115/0116 → 库超前于目标（升级会把
    # 旧代码跑在新库上）→ 必须阻断。
    monkeypatch.setenv(
        "LUMIRSS_RELEASE_MANIFEST",
        _write_manifest(env, _manifest("0.3.0", ["0001_core.sql"])),
    )
    data = _preview(env)
    assert data["blocked"] is True
    assert "ahead" in data["blockedReason"].lower()


def test_missing_and_broken_files_are_honest(preview_env, monkeypatch):
    env = preview_env
    monkeypatch.setenv("LUMIRSS_RELEASE_MANIFEST", str(env["db_path"] / "missing.json"))
    data = _preview(env)
    assert data["available"] is False
    assert "readable" in data["reason"] or "missing" in data["reason"]

    monkeypatch.setenv("LUMIRSS_RELEASE_MANIFEST", _write_manifest(env, "{not json"))
    data = _preview(env)
    assert data["available"] is False
    assert "JSON" in data["reason"]

    monkeypatch.setenv(
        "LUMIRSS_RELEASE_MANIFEST",
        _write_manifest(env, json.dumps({"schema": "other/v9", "version": "9.9.9"})),
    )
    data = _preview(env)
    assert data["available"] is False
    assert "schema" in data["reason"]


def test_member_403(preview_env):
    env = preview_env
    response = env["client"].get("/api/v1/admin/upgrade-preview", headers=env["alice"])
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "forbidden"
