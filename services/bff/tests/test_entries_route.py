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
from lumirss.models import EntryDetail, EntryListItem

VALID_REF = encode_entry_ref("tag:google.com,2005:reader/item/000659e07aaee24d")

ENTRY_FIXTURES = [
    EntryListItem(
        entryRef=VALID_REF,
        title="科技爱好者周刊（第 409 期）",
        feedTitle="阮一峰的网络日志",
        author="阮一峰",
        url="http://example.com/weekly-409",
        publishedAt="2026-08-20T23:53:54Z",
    ),
    EntryListItem(
        entryRef=encode_entry_ref("tag:google.com,2005:reader/item/000659e07aaee24e"),
        title="FreshRSS 1.29.1 released",
        feedTitle="FreshRSS releases",
        author=None,
        url=None,
        publishedAt=None,
    ),
]

DETAIL_FIXTURE = EntryDetail(
    entryRef=VALID_REF,
    title="科技爱好者周刊（第 409 期）",
    feedTitle="阮一峰的网络日志",
    author="阮一峰",
    url="http://example.com/weekly-409",
    publishedAt="2026-08-20T23:53:54Z",
    contentText="这里是文章正文纯文本。",
)


class FakeAdapter:
    def __init__(self, entries=None, detail=None, error=None) -> None:
        self.entries = entries if entries is not None else ENTRY_FIXTURES
        self.detail = detail if detail is not None else DETAIL_FIXTURE
        self.error = error
        self.list_calls = 0
        self.detail_calls: list[str] = []

    async def list_feeds(self):
        return []  # not under test here; routes only use entry methods

    async def list_entries(self) -> list[EntryListItem]:
        self.list_calls += 1
        if self.error is not None:
            raise self.error
        return self.entries

    async def get_entry(self, item_id: str) -> EntryDetail:
        self.detail_calls.append(item_id)
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
        assert list(body.keys()) == ["items"]
        assert len(body["items"]) == 2
        assert body["items"][0] == {
            "entryRef": VALID_REF,
            "title": "科技爱好者周刊（第 409 期）",
            "feedTitle": "阮一峰的网络日志",
            "author": "阮一峰",
            "url": "http://example.com/weekly-409",
            "publishedAt": "2026-08-20T23:53:54Z",
        }
        assert fake.list_calls == 1
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
            "contentText": "这里是文章正文纯文本。",
        }
        assert fake.detail_calls == [
            "tag:google.com,2005:reader/item/000659e07aaee24d"
        ]
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
        assert fake.list_calls == 0
        assert fake.detail_calls == []  # FreshRSS was never contacted
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
