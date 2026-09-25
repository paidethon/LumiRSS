"""N198 版本差异功能导览 — GET /api/v1/whats-new 角色过滤 + 版本语义。

覆盖：
- 数据文件 docs/release-notes.json 随仓库可发现（dev checkout 路径解析）
  且 version/features 结构合法；
- adminOnly 条目只对 owner/admin 出现（成员响应里根本没有这些条目）；
- 未知 sinceVersion / 缺省 → 全部条目（unknown → all）；
- 已知 sinceVersion（== 清单版本）→ 空导览；
- LUMIRSS_RELEASE_NOTES 指向缺失/坏文件 → version:null + 空清单
  （诚实空导览，前端隐藏卡片）。
"""

import asyncio
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app
from lumirss.storage import Database

PASSWORD = "wn-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"


@pytest.fixture()
def whats_env(monkeypatch, tmp_path):
    # 显式清空覆盖，让默认路径发现逻辑命中仓库 docs/release-notes.json。
    monkeypatch.delenv("LUMIRSS_RELEASE_NOTES", raising=False)
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
        yield {
            "client": client,
            "owner": {"cookie": owner_login.headers["set-cookie"].split(";")[0]},
            "alice": {"cookie": activation.headers["set-cookie"].split(";")[0]},
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


def _whats_new(env, who: str, since: str | None = None):
    path = "/api/v1/whats-new" + (f"?sinceVersion={since}" if since is not None else "")
    response = env["client"].get(path, headers={"cookie": env[who]["cookie"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_release_notes_file_discoverable_with_valid_shape(whats_env):
    env = whats_env
    data = _whats_new(env, "owner")
    assert data["version"] is not None, "dev checkout 必须能发现 docs/release-notes.json"
    assert len(data["features"]) > 0
    for feature in data["features"]:
        assert feature["id"] and feature["title"]


def test_admin_only_entries_filtered_by_role(whats_env):
    env = whats_env
    owner_view = _whats_new(env, "owner")
    member_view = _whats_new(env, "alice")
    owner_ids = {feature["id"] for feature in owner_view["features"]}
    member_ids = {feature["id"] for feature in member_view["features"]}
    admin_only_ids = {f["id"] for f in owner_view["features"] if f.get("adminOnly")}
    assert admin_only_ids, "清单里应有 adminOnly 条目（N19x 管理台功能）"
    assert admin_only_ids <= owner_ids
    # 成员响应里「根本没有」这些条目——不是前端隐藏。
    assert admin_only_ids.isdisjoint(member_ids)


def test_unknown_version_returns_all(whats_env):
    env = whats_env
    all_features = _whats_new(env, "alice")["features"]
    unknown = _whats_new(env, "alice", since="0.0.1-unknown")["features"]
    assert len(unknown) == len(all_features) > 0


def test_known_version_returns_empty(whats_env):
    env = whats_env
    current = _whats_new(env, "owner")["version"]
    seen = _whats_new(env, "owner", since=str(current))["features"]
    assert seen == []


def test_missing_or_broken_override_is_empty_not_fake(whats_env, monkeypatch, tmp_path):
    env = whats_env
    monkeypatch.setenv("LUMIRSS_RELEASE_NOTES", str(tmp_path / "missing.json"))
    data = _whats_new(env, "owner")
    assert data["version"] is None
    assert data["features"] == []

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("LUMIRSS_RELEASE_NOTES", str(broken))
    data = _whats_new(env, "owner")
    assert data["version"] is None
    assert data["features"] == []
