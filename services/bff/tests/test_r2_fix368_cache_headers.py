"""FIX-368: 私有 API 响应必须带 Cache-Control: no-store（共享缓存不可存）。

背景：admin/auth 路由里只有显式走 ``JSONResponse(headers=_NO_STORE)`` 的
响应带了 no-store；同样敏感的用户数据/管理面响应（经 FastAPI
response_model 直接返回 dict）完全没有任何缓存头——在共享缓存/CDN 后面
会被按 URL 公开缓存。修复：边缘中间件给所有 /api/* 响应统一盖章
no-store（保持既有显式头不变），单条路由逐一补头的做法注定有缺口。
"""

import pytest
from fastapi.testclient import TestClient

from lumirss.main import app

# 代表性私有响应面：管理面（成员/邀请/审计）、认证状态、用户数据。
_PRIVATE_PATHS = [
    "/api/v1/admin/users",
    "/api/v1/admin/invites",
    "/api/v1/admin/audit",
    "/api/v1/auth/session",
    "/api/v1/operations/status",
]


@pytest.mark.parametrize("path", _PRIVATE_PATHS)
def test_private_api_responses_carry_no_store(path):
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 200, path
    assert response.headers.get("cache-control") == "no-store", path


def test_csrf_rejection_envelope_carry_no_store(monkeypatch):
    """中间件自产的 403（CSRF）此前没有缓存头。Origin 检查属于 session
    认证层（basic 模式不做 Origin 检查），所以这里显式切 session 模式。"""
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    with TestClient(app) as client:
        cross_origin = client.post(
            "/api/v1/auth/login",
            json={"username": "x", "password": "y"},
            headers={"Origin": "https://evil.example"},
        )
        assert cross_origin.status_code == 403
        assert cross_origin.headers.get("cache-control") == "no-store"


def test_rate_limit_envelope_carries_no_store(monkeypatch):
    """中间件自产的 429（限速）同样不可被共享缓存存储。"""
    monkeypatch.setattr(
        "lumirss.middleware._RATE_RULES",
        (("POST", "/api/v1/auth/login", "login_limit", 0, 60),),
    )
    with TestClient(app) as client:
        limited = client.post(
            "/api/v1/auth/login",
            json={"username": "x", "password": "y"},
        )
        assert limited.status_code == 429
        assert limited.headers.get("cache-control") == "no-store"
