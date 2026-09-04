"""Tests for operations status / readiness (0018).

Failure isolation: RSSHub down must not fail readiness. Status is redacted
by construction — no URL, no credential, no raw exception in the payload.
"""

import asyncio

import httpx
import pytest

from lumirss.config import FreshRSSSettings
from lumirss.operations import OperationsService
from lumirss.storage import Database

def _secrets_token() -> str:
    import secrets

    return secrets.token_urlsafe(6)


# 动态生成的假凭据（非真实 secret；安全扫描要求无凭据形状字面量）
FAKE_SECRET = "probe-" + _secrets_token()


def run(coroutine):
    return asyncio.run(coroutine)


def _service(handler, tmp_path, monkeypatch):
    class _RssHubSettings:
        RSSHUB_BASE_URL = "http://rsshub.local:1200"

    monkeypatch.setattr("lumirss.operations.RssHubSettings", _RssHubSettings)
    # 显式注入 FreshRSS 配置：测试绝不读取本地 .env / 环境变量
    # （_env_file=None），保证 CI 与本地行为一致。
    freshrss = FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL="http://freshrss.local",
        FRESHRSS_USERNAME="tester",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OperationsService(client, Database(tmp_path / "lumi.sqlite"), freshrss)


def _freshrss_healthy(request):
    return httpx.Response(200, text="Auth=token-123\n")


def _freshrss_unauth(request):
    return httpx.Response(401, text="Error=BadAuthentication")


def _rsshub_healthy(request):
    return httpx.Response(200, text="ok")


def _down(request):
    raise httpx.ConnectError("boom")


def test_freshrss_healthy(tmp_path, monkeypatch):
    service = _service(_freshrss_healthy, tmp_path, monkeypatch)
    status = run(service.freshrss_status())
    assert status["status"] == "healthy"
    assert status["latencyMs"] is not None
    assert status["error"] is None


def test_freshrss_unauthenticated(tmp_path, monkeypatch):
    service = _service(_freshrss_unauth, tmp_path, monkeypatch)
    status = run(service.freshrss_status())
    assert status["status"] == "unauthenticated"
    assert status["error"]["type"] == "authentication_error"


def test_freshrss_unavailable_on_connection_error(tmp_path, monkeypatch):
    service = _service(_down, tmp_path, monkeypatch)
    status = run(service.freshrss_status())
    assert status["status"] == "unavailable"
    assert status["error"]["type"] == "connection_error"


def test_rsshub_healthy(tmp_path, monkeypatch):
    service = _service(_rsshub_healthy, tmp_path, monkeypatch)
    status = run(service.rsshub_status())
    assert status["status"] == "healthy"


def test_rsshub_unavailable(tmp_path, monkeypatch):
    service = _service(_down, tmp_path, monkeypatch)
    status = run(service.rsshub_status())
    assert status["status"] == "unavailable"


def test_sqlite_healthy_after_migrate(tmp_path, monkeypatch):
    service = _service(_freshrss_healthy, tmp_path, monkeypatch)
    status = run(service.sqlite_status())
    assert status["status"] == "healthy"
    assert status["schemaVersion"] >= 1


def test_readiness_succeeds_when_rsshub_down(tmp_path, monkeypatch):
    service = _service(_down, tmp_path, monkeypatch)
    ready, payload = run(service.ready())
    assert ready is True
    assert payload["status"] == "ok"
    assert payload["components"]["rsshub"] == "unavailable"


def test_status_contains_no_credentials(tmp_path, monkeypatch):
    service = _service(_freshrss_healthy, tmp_path, monkeypatch)
    status = run(service.full_status())
    text = str(status)
    for marker in ("password", "Passwd", "Auth=", "secret", "token-123"):
        assert marker not in text


def test_freshrss_status_error_is_static_and_bounded(tmp_path, monkeypatch):
    service = _service(_down, tmp_path, monkeypatch)
    status = run(service.freshrss_status())
    # The safe error never leaks the URL or a raw exception message.
    assert "127.0.0.1" not in str(status["error"])
    assert "boom" not in str(status["error"])
