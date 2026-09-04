"""Tests B / C / D — FreshRSSAdapter behavior against a mocked FreshRSS.

Every fake value here is clearly test data; no real credentials are used.
"""

import httpx
import pytest
from pydantic import ValidationError

from lumirss.adapters.freshrss import (
    AuthenticationError,
    Feed,
    FreshRSSAdapter,
    UpstreamConnectionError,
    UpstreamError,
)
from lumirss.config import FreshRSSSettings

import secrets as _secrets
# 动态生成的假凭据（非真实 secret；安全扫描要求无凭据形状字面量）
FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)

FAKE_TOKEN = "fake-test-token-0002"

BASE_URL = "http://freshrss-test.local"

SUBSCRIPTIONS_FIXTURE = {
    "subscriptions": [
        {"id": "feed/1", "title": "FreshRSS releases", "url": "https://example.com/releases.xml"},
        {"id": "feed/2", "title": "阮一峰的网络日志", "url": "https://example.com/ruanyifeng.xml"},
    ]
}


def make_settings() -> FreshRSSSettings:
    """Explicit env, no .env file — tests must never read real secrets."""
    return FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )


def make_adapter(handler) -> FreshRSSAdapter:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    return FreshRSSAdapter(client, make_settings())


# --- Test B — ClientLogin parsing -------------------------------------


@pytest.mark.anyio
async def test_clientlogin_token_is_parsed_and_cached():
    login_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        login_calls.append(request.url.path)
        return httpx.Response(200, text=f"SID=unused\nLSID=unused\nAuth={FAKE_TOKEN}\n")

    adapter = make_adapter(handler)

    token = await adapter._get_auth_token()

    assert token == FAKE_TOKEN
    assert adapter._auth_token == FAKE_TOKEN  # token lives in memory only

    # Second call reuses the cached token — no second ClientLogin request.
    assert await adapter._get_auth_token() == FAKE_TOKEN
    assert len(login_calls) == 1


@pytest.mark.anyio
async def test_clientlogin_401_raises_authentication_error_without_password():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    adapter = make_adapter(handler)

    with pytest.raises(AuthenticationError) as exc_info:
        await adapter._get_auth_token()

    assert FAKE_SECRET not in str(exc_info.value)


@pytest.mark.anyio
async def test_clientlogin_500_raises_upstream_error_not_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    adapter = make_adapter(handler)

    with pytest.raises(UpstreamError):
        await adapter._get_auth_token()


# --- Test C — subscription mapping -------------------------------------


@pytest.mark.anyio
async def test_list_feeds_maps_subscriptions_to_lumirss_model():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        assert request.headers["Authorization"] == f"GoogleLogin auth={FAKE_TOKEN}"
        return httpx.Response(200, json=SUBSCRIPTIONS_FIXTURE)

    adapter = make_adapter(handler)

    feeds = await adapter.list_feeds()

    assert feeds == [
        Feed(title="FreshRSS releases", feed_url="https://example.com/releases.xml"),
        Feed(title="阮一峰的网络日志", feed_url="https://example.com/ruanyifeng.xml"),
    ]


@pytest.mark.anyio
async def test_list_feeds_relogin_once_on_401():
    """Subscription/list 401 (e.g. password changed) → clear token,
    ClientLogin once, retry once. No loop."""
    subscription_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        subscription_calls.append(request.headers.get("Authorization"))
        if len(subscription_calls) == 1:
            return httpx.Response(401)  # stale token
        return httpx.Response(200, json=SUBSCRIPTIONS_FIXTURE)

    adapter = make_adapter(handler)

    feeds = await adapter.list_feeds()

    assert len(subscription_calls) == 2
    assert feeds[0].title == "FreshRSS releases"


@pytest.mark.anyio
async def test_list_feeds_unexpected_json_shape_raises_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        return httpx.Response(200, json={"unexpected": "shape"})

    adapter = make_adapter(handler)

    with pytest.raises(UpstreamError):
        await adapter.list_feeds()


@pytest.mark.anyio
async def test_list_feeds_connection_error_maps_to_upstream_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    adapter = make_adapter(handler)

    with pytest.raises(UpstreamConnectionError):
        await adapter.list_feeds()


# --- Test D — secret / config behavior ---------------------------------


def test_settings_missing_password_is_rejected():
    with pytest.raises(ValidationError):
        FreshRSSSettings(
            _env_file=None,
            FRESHRSS_BASE_URL=BASE_URL,
            FRESHRSS_USERNAME="test-user",
            FRESHRSS_API_PASSWORD="",
        )


def test_settings_blank_username_is_rejected():
    with pytest.raises(ValidationError):
        FreshRSSSettings(
            _env_file=None,
            FRESHRSS_BASE_URL=BASE_URL,
            FRESHRSS_USERNAME="",
            FRESHRSS_API_PASSWORD=FAKE_SECRET,
        )


def test_settings_secret_is_masked_in_repr():
    settings = FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )

    assert FAKE_SECRET not in repr(settings)
