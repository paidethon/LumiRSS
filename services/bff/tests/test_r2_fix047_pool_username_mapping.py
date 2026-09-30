"""FIX-047 — FreshRSS 池用户映射：大小写/空白变体不得复用同一后端账号。

上游事实（FreshRSS app/Controllers/userController.php createUser）：
``$ok &= !in_array(strtoupper($new_user_name), array_map('strtoupper',
self::listUsers()), true);  // Not an existing user, case-insensitive``
—— FreshRSS 用户名唯一性本身就是大小写不敏感的；``"Alice"`` 与
``"alice"`` 在 FreshRSS 上不可能同时存在。因此 Lumi 池若把它们登记成
两条 ready 记录，两个成员激活时会被分配到**同一个** FreshRSS 后端
账号（订阅源/已读状态互相可见）——正是「串用他人的订阅后端」。

已有覆盖（不重复钉定）：
- 精确重名 → UNIQUE → 409 pool_conflict（accounts_store.pool_add）；
- 绑定失败可重试：FIX-032 中点恢复（pool_release 回 ready + 诚实
  binding_pending，test_r2_bff13）；
- 并发激活原子分配、到期 hold 清扫（test_invite_schemes N003）。

本文件钉定残留缺口（红先行）：
- 登记时 trim 用户名（FreshRSS 用户名也是目录名/表名片段，含空白
  本身不合法）；trim 后为空 → 409 pool_conflict；
- 与既有记录仅大小写不同 → 409 pool_conflict（同一后端账号）；
- 池 API 密码仍只写不读，且 secrets 键 ``freshrss_pool:<username>``
  使用与池行一致的规范化用户名——绑定读取（bind_freshrss_account）
  按池行用户名逐字取密，键错位会让成员激活后认证失败。
"""

import asyncio
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app

PASSWORD = "fix-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"


@pytest.fixture()
def pool_env(monkeypatch, tmp_path):
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
        yield {
            "client": client,
            "owner": owner_headers,
            "db_path": tmp_path,
        }


def _set_owner_password(db_path) -> None:
    async def run():
        from lumirss.storage import Database

        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        store = AccountsStore(database)
        owner = None
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                owner = row
                break
        assert owner is not None, "owner migration did not run"
        await store.set_password_hash(str(owner["id"]), hash_password(PASSWORD))

    asyncio.run(run())


def _add_pool(env, username):
    return env["client"].post(
        "/api/v1/admin/pool",
        json={
            "freshrssUsername": username,
            "freshrssBaseUrl": "http://freshrss.test",
            "apiPassword": "pool-" + _secrets.token_hex(12),
        },
        headers=env["owner"],
    )


def test_trims_surrounding_whitespace(pool_env):
    response = _add_pool(pool_env, "  frss-mia  ")
    assert response.status_code == 200, response.text
    row = response.json()
    # 池行存规范化用户名——绑定/取密都用它。
    assert row["freshrss_username"] == "frss-mia"
    # secrets 键与池行逐字一致（绑定按池行用户名取密）。
    assert app.state.control_secrets.get("freshrss_pool:frss-mia") is not None
    assert app.state.control_secrets.get("freshrss_pool: frss-mia ") is None


def test_case_variant_duplicate_is_rejected(pool_env):
    first = _add_pool(pool_env, "frss-mia")
    assert first.status_code == 200, first.text
    # FreshRSS 用户名唯一性大小写不敏感（上游 createUser 逐字证据）；
    # 大小写变体 = 同一后端账号，绝不能登记成第二条 ready 记录。
    variant = _add_pool(pool_env, "FRSS-MIA")
    assert variant.status_code == 409, variant.text
    assert variant.json()["error"]["type"] == "pool_conflict"
    # 精确重名同样 409（既有行为回归守卫）。
    exact = _add_pool(pool_env, "frss-mia")
    assert exact.status_code == 409, exact.text


def test_blank_after_trim_is_rejected(pool_env):
    response = _add_pool(pool_env, "   ")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["type"] == "pool_conflict"
