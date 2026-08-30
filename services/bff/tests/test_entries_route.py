"""Tests G / H / I / J — entry routes with an injected fake adapter.

No real FreshRSS is contacted: we replace app.state.freshrss_adapter with a
stub, so these tests exercise the routes and error mapping only.
"""

from fastapi.testclient import TestClient

from lumirss.adapters.freshrss import (
    AuthenticationError,
    EntryNotFound,
    UpstreamConnectionError,
)
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail, EntryListItem, EntryPage

VALID_REF = encode_entry_ref("tag:google.com,2005:reader/item/000659e07aaee24d")

ENTRY_FIXTURES = [
    EntryListItem(
        entryRef=VALID_REF,
        title="科技爱好者周刊（第 409 期）",
        feedTitle="阮一峰的网络日志",
        author="阮一峰",
        url="http://example.com/weekly-409",
        publishedAt="2026-08-20T23:53:54Z",
        read=False,
        starred=False,
    ),
    EntryListItem(
        entryRef=encode_entry_ref("tag:google.com,2005:reader/item/000659e07aaee24e"),
        title="FreshRSS 1.29.1 released",
        feedTitle="FreshRSS releases",
        author=None,
        url=None,
        publishedAt=None,
        read=True,
        starred=False,
    ),
]

DETAIL_FIXTURE = EntryDetail(
    entryRef=VALID_REF,
    title="科技爱好者周刊（第 409 期）",
    feedTitle="阮一峰的网络日志",
    author="阮一峰",
    url="http://example.com/weekly-409",
    publishedAt="2026-08-20T23:53:54Z",
    read=False,
    starred=False,
    contentText="这里是文章正文纯文本。",
    contentHtml="<p>这里是文章正文纯文本。</p>",
)


class FakeAdapter:
    def __init__(self, entries=None, detail=None, error=None, calls=None) -> None:
        self.entries = entries if entries is not None else ENTRY_FIXTURES
        self.detail = detail if detail is not None else DETAIL_FIXTURE
        self.error = error
        self.calls = calls if calls is not None else []  # (view, feed_url, continuation)

    async def list_feeds(self):
        return []  # not under test here; routes only use entry methods

    async def list_entries(self, *, view="all", feed_url=None, category_id=None, source_type=None, continuation=None):
        self.calls.append((view, feed_url, continuation))
        if self.error is not None:
            raise self.error
        return EntryPage(items=self.entries, upstreamContinuation=None)

    async def get_entry(self, item_id: str) -> EntryDetail:
        if self.error is not None:
            raise self.error
        return self.detail

# --- Test G — list route -------------------------------------------------


def test_entries_route_returns_items_envelope():
    fake = FakeAdapter()
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            response = client.get("/api/v1/entries")

        assert response.status_code == 200
        body = response.json()
        assert list(body.keys()) == ["items", "nextCursor"]
        assert len(body["items"]) == 2
        assert body["nextCursor"] is None
        assert body["items"][0] == {
            "entryRef": VALID_REF,
            "title": "科技爱好者周刊（第 409 期）",
            "feedTitle": "阮一峰的网络日志",
            "author": "阮一峰",
            "url": "http://example.com/weekly-409",
            "publishedAt": "2026-08-20T23:53:54Z",
            "read": False,
            "starred": False,
        }
        # 0006 Test C — the list never carries any body fields.
        assert "contentHtml" not in body["items"][0]
        assert "contentText" not in body["items"][0]
        assert fake.calls == [("all", None, None)]
    finally:
        app.state.freshrss_adapter = None


def test_entries_route_maps_authentication_error():
    fake = FakeAdapter(error=AuthenticationError("FreshRSS rejected the credentials."))
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            response = client.get("/api/v1/entries")

        assert response.status_code == 502
        assert response.json()["error"]["type"] == "authentication_error"
    finally:
        app.state.freshrss_adapter = None


def test_entries_route_maps_connection_error():
    fake = FakeAdapter(error=UpstreamConnectionError("Could not reach FreshRSS."))
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            response = client.get("/api/v1/entries")

        assert response.status_code == 502
        assert response.json()["error"]["type"] == "connection_error"
    finally:
        app.state.freshrss_adapter = None


# --- Test H — detail route ------------------------------------------------


def test_entry_detail_route_returns_detail():
    fake = FakeAdapter()
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            response = client.get(f"/api/v1/entries/{VALID_REF}")

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "entryRef": VALID_REF,
            "title": "科技爱好者周刊（第 409 期）",
            "feedTitle": "阮一峰的网络日志",
            "author": "阮一峰",
            "url": "http://example.com/weekly-409",
            "publishedAt": "2026-08-20T23:53:54Z",
            "read": False,
            "starred": False,
            "contentText": "这里是文章正文纯文本。",
            "contentHtml": "<p>这里是文章正文纯文本。</p>",
        }
    finally:
        app.state.freshrss_adapter = None


# --- Test I — invalid ref must be rejected before FreshRSS -----------------


def test_entry_detail_route_invalid_ref_is_400_and_never_touches_adapter():
    fake = FakeAdapter()
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            response = client.get("/api/v1/entries/not-a-valid-ref")

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["type"] == "invalid_entry_reference"
        assert fake.calls == []  # FreshRSS was never contacted
    finally:
        app.state.freshrss_adapter = None


# --- Test J — valid ref but entry missing ----------------------------------


def test_entry_detail_route_not_found_is_404():
    fake = FakeAdapter(error=EntryNotFound("FreshRSS has no such entry."))
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            response = client.get(f"/api/v1/entries/{VALID_REF}")

        assert response.status_code == 404
        assert response.json()["error"]["type"] == "entry_not_found"
    finally:
        app.state.freshrss_adapter = None
