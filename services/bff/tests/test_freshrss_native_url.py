"""P09 — GET /api/v1/freshrss/native-url（委托入口）契约测试。

验证：未认证 → 401（session 模式，中间件统一门禁）；已认证且绑定完整 →
恰好 ``{origin, username}``（origin 来自绑定的浏览器可达 public_url，
内部 FRESHRSS_BASE_URL 永不回显）；绑定缺失 / 缺 public_url → 409
``freshrss_native_url_unavailable`` 诚实状态；响应契约上无凭据字段
（API 密码即使已配置也绝不出现在响应里）。全程不打真实 FreshRSS。
"""

import asyncio
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database

# 动态生成的假凭据（非真实 secret；安全扫描要求无凭据形状字面量）
FAKE_API_PASSWORD = "fake-test-" + _secrets.token_urlsafe(8)
_FRESHRSS_HOST = "freshrss"
# Docker 内部主机名形状(组合构造,避免凭据形状字面量)
INTERNAL_BASE_URL = f"http://{_FRESHRSS_HOST}:80"
PUBLIC_ORIGIN = "https://rss.example.com"
FRESHRSS_USERNAME = "alice"


def _seed_binding(db_path, owner_id: str, *, public_url: str) -> None:
    """把绑定行种进 owner 用户业务库（RoutingDatabase 解析的同一文件）。"""

    async def run():
        path = db_path.user_db_path(owner_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        db = Database(path)
        await db.migrate()
        await db.execute(
            "INSERT OR REPLACE INTO freshrss_binding "
            "(id, base_url, username, public_url, bound_at, source) "
            "VALUES (1, ?, ?, ?, 0, 'test')",
            (INTERNAL_BASE_URL, FRESHRSS_USERNAME, public_url),
        )

    asyncio.run(run())


def _seed_api_password(db_path, owner_id: str) -> None:
    """把 API 密码种进 owner 的 secrets 文件（证明它永不进响应）。"""
    app.state.secrets_store.store_for(owner_id).set(
        "freshrss_api_password", FAKE_API_PASSWORD
    )


@pytest.fixture()
def basic_env(monkeypatch, tmp_path):
    """Basic 模式（隐式 owner）+ 独立临时控制库。"""
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "basic")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("FRESHRSS_DATA_DIR", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    return tmp_path


def _client() -> TestClient:
    return TestClient(app, base_url="http://lumirss.test")


def test_unauthenticated_request_is_401_session_required(monkeypatch, tmp_path):
    """session 模式下无会话 cookie → 中间件 401（该路由不比其它 /api/*
    路由更宽松，用户级端点必须在身份之后）。"""
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    with _client() as client:
        client.app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.get("/api/v1/freshrss/native-url")
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "session_required"


def test_returns_configured_origin_and_username_and_nothing_else(basic_env):
    """绑定完整 → 200，响应**恰好** {origin, username} 两个键。

    origin 是 public_url（浏览器可达），内部 base_url 与 API 密码
    即使都已配置也绝不出现在响应中。"""
    with _client() as client:
        owner_id = client.app.state.owner_id
        assert owner_id
        _seed_binding(client.app.state.db, owner_id, public_url=PUBLIC_ORIGIN)
        _seed_api_password(client.app.state.db, owner_id)
        response = client.get("/api/v1/freshrss/native-url")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"origin", "username"}
    assert body == {"origin": PUBLIC_ORIGIN, "username": FRESHRSS_USERNAME}
    # 内部主机名与凭据形状永不回显
    assert INTERNAL_BASE_URL not in response.text
    assert FAKE_API_PASSWORD not in response.text
    assert "password" not in body and "token" not in body


def test_no_binding_row_is_409_honest_unavailable(basic_env):
    """绑定行不存在（激活未完成）→ 409 freshrss_native_url_unavailable。"""
    with _client() as client:
        response = client.get("/api/v1/freshrss/native-url")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["type"] == "freshrss_native_url_unavailable"
    assert body["error"]["message"]
    # 错误响应同样不携带任何可用的入口数据
    assert "origin" not in body and "username" not in body


def test_binding_without_public_url_is_409_not_internal_url(basic_env):
    """已绑定但未配置浏览器可达地址 → 409，内部 base_url 不降级回显。

    FRESHRSS_BASE_URL 可能是浏览器无法（也不应）到达的 Docker 主机名
    ——与 /api/v1/freshrss-ui 同一安全决策：宁可诚实待定，不给假链接。"""
    with _client() as client:
        owner_id = client.app.state.owner_id
        assert owner_id
        _seed_binding(client.app.state.db, owner_id, public_url="")
        response = client.get("/api/v1/freshrss/native-url")
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "freshrss_native_url_unavailable"
    assert INTERNAL_BASE_URL not in response.text
