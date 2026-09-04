"""Tests E / F / H + route query tests — pagination via cursor.

Two layers: the adapter against a mocked FreshRSS (continuation mapping)
and the route with an injected fake adapter (query parsing, cursor scope
rules, invalid cursor → 400 before touching FreshRSS).
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.adapters.freshrss import FreshRSSAdapter
from lumirss.config import FreshRSSSettings
from lumirss.cursor import encode_cursor
from lumirss.main import app
from lumirss.models import EntryDetail, EntryListItem, EntryPage

import secrets as _secrets
# 动态生成的假凭据（非真实 secret；安全扫描要求无凭据形状字面量）
FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)

FAKE_TOKEN = "fake-test-token-0004"
BASE_URL = "http://freshrss-test.local"
FEED_URL = "https://example.com/releases.xml"

PAGE1_ITEM = {
    "id": "tag:google.com,2005:reader/item/000659e07aaee24d",
    "title": "第一页文章",
    "author": None,
    "published": 1787270034,
    "summary": {"content": "<p>body</p>"},
    "alternate": [{"href": "http://example.com/1"}],
    "origin": {"streamId": "feed/2", "htmlUrl": "http://example.com/", "title": "Feed"},
    "categories": ["user/-/state/com.google/reading-list"],
}
PAGE2_ITEM = dict(PAGE1_ITEM, id="tag:google.com,2005:reader/item/000659e07aaee24e", title="第二页文章")


def make_settings() -> FreshRSSSettings:
    return FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )


def make_adapter(handler) -> tuple[FreshRSSAdapter, list[httpx.Request]]:
    requested: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording_handler), trust_env=False)
    return FreshRSSAdapter(client, make_settings()), requested


# --- Test E — continuation mapping (adapter level) --------------------------


@pytest.mark.anyio
async def test_upstream_continuation_is_returned_as_upstream_continuation():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        return httpx.Response(200, json={"items": [PAGE1_ITEM], "continuation": "12345"})

    adapter, _ = make_adapter(handler)

    page = await adapter.list_entries()

    assert page.upstreamContinuation == "12345"


@pytest.mark.anyio
async def test_continuation_is_forwarded_upstream_as_c_parameter():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        return httpx.Response(200, json={"items": [PAGE2_ITEM]})

    adapter, requested = make_adapter(handler)

    await adapter.list_entries(view="unread", feed_url=FEED_URL, continuation="12345")

    stream = requested[-1]
    assert stream.url.params["c"] == "12345"
    assert stream.url.params["it"] == "user/-/state/com.google/unread"


# --- Test F — no continuation ------------------------------------------------


@pytest.mark.anyio
async def test_missing_continuation_yields_none():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        return httpx.Response(200, json={"items": [PAGE1_ITEM]})

    adapter, _ = make_adapter(handler)

    page = await adapter.list_entries()

    assert page.upstreamContinuation is None


@pytest.mark.anyio
async def test_empty_final_page_with_no_continuation_is_valid():
    """nextCursor=null + empty items is a legal final page, not an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        return httpx.Response(200, json={"items": []})

    adapter, _ = make_adapter(handler)

    page = await adapter.list_entries(continuation="99999")

    assert page.items == []
    assert page.upstreamContinuation is None


# --- Route-level pagination (fake adapter) -----------------------------------


class FakePageAdapter:
    def __init__(self) -> None:
        self.calls = []  # (view, feed_url, continuation)

    async def list_feeds(self):
        return []

    async def list_entries(self, *, view="all", feed_url=None, category_id=None, source_type=None, continuation=None):
        self.calls.append((view, feed_url, continuation))
        if continuation is None:
            return EntryPage(
                items=[
                    EntryListItem(
                        entryRef="e1.abc",
                        title="第一页文章",
                        feedTitle="Feed",
                        read=False,
                        starred=False,
                    )
                ],
                upstreamContinuation="12345",
            )
        return EntryPage(items=[], upstreamContinuation=None)

    async def get_entry(self, item_id: str) -> EntryDetail:
        raise AssertionError("not under test")


def run_client(fake, method, url):
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            return getattr(client, method)(url)
    finally:
        app.state.freshrss_adapter = None


def test_route_page1_produces_next_cursor():
    fake = FakePageAdapter()
    response = run_client(fake, "get", "/api/v1/entries")

    assert response.status_code == 200
    body = response.json()
    assert body["nextCursor"].startswith("c1.")
    assert fake.calls == [("all", None, None)]


def test_route_cursor_alone_requests_next_page_with_cursor_scope():
    fake = FakePageAdapter()
    cursor = encode_cursor("12345", "unread", FEED_URL)

    response = run_client(fake, "get", f"/api/v1/entries?cursor={cursor}")

    assert response.status_code == 200
    body = response.json()
    # Cursor scope was adopted: unread + feed URL + continuation replayed.
    assert fake.calls == [("unread", FEED_URL, "12345")]
    assert body["nextCursor"] is None  # final page with no items is legal


def test_route_cursor_with_matching_explicit_scope_is_accepted():
    fake = FakePageAdapter()
    cursor = encode_cursor("12345", "unread", FEED_URL)

    response = run_client(
        fake, "get", f"/api/v1/entries?view=unread&feedUrl={FEED_URL}&cursor={cursor}"
    )

    assert response.status_code == 200
    assert fake.calls == [("unread", FEED_URL, "12345")]


# --- Test H — cursor scope mismatch → 400, never touching FreshRSS -----------


def test_route_cursor_view_mismatch_is_400_without_adapter_call():
    fake = FakePageAdapter()
    cursor = encode_cursor("12345", "unread", None)

    response = run_client(fake, "get", f"/api/v1/entries?view=starred&cursor={cursor}")

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_cursor"
    assert fake.calls == []  # FreshRSS was never contacted


def test_route_cursor_feed_mismatch_is_400_without_adapter_call():
    fake = FakePageAdapter()
    cursor = encode_cursor("12345", "all", "https://example.com/a.xml")

    response = run_client(
        fake, "get", f"/api/v1/entries?feedUrl=https://example.com/b.xml&cursor={cursor}"
    )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_cursor"
    assert fake.calls == []


def test_route_cursor_feed_scope_against_no_feed_request_is_allowed():
    """Explicit feedUrl absent → cursor's feed scope is adopted, not a mismatch."""
    fake = FakePageAdapter()
    cursor = encode_cursor("12345", "all", FEED_URL)

    response = run_client(fake, "get", f"/api/v1/entries?cursor={cursor}")

    assert response.status_code == 200
    assert fake.calls == [("all", FEED_URL, "12345")]


def test_route_invalid_cursor_string_is_400_without_adapter_call():
    fake = FakePageAdapter()

    response = run_client(fake, "get", "/api/v1/entries?cursor=not-a-cursor")

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_cursor"
    assert fake.calls == []


def test_route_invalid_view_value_is_422():
    fake = FakePageAdapter()

    response = run_client(fake, "get", "/api/v1/entries?view=bogus")

    assert response.status_code == 422
    assert fake.calls == []
