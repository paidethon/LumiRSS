"""0013 Gate 4 — OPML parse / preview / merge-import / export tests.

Parsing is exercised on untrusted inputs (malformed XML, DTD entity
attacks, deep nesting, oversized payloads). Service-level tests run over
a fake control adapter; route tests inject it onto app.state (no real
FreshRSS is contacted).
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.adapters.freshrss import (
    AdapterError,
    AuthenticationError,
    UpstreamConnectionError,
    UpstreamError,
)
from lumirss.adapters.freshrss_control import (
    Category,
    FeedRejectedError,
    Subscription,
)
from lumirss.main import app
from lumirss.opml import (
    MAX_OPML_DEPTH,
    MAX_OPML_FEEDS,
    OpmlInvalid,
    OpmlService,
    OpmlTooLarge,
    OpmlTooManyFeeds,
    parse_opml,
)

VALID_OPML = b"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>Subscriptions</title></head>
  <body>
    <outline text="Tech">
      <outline text="Feed A" xmlUrl="https://a.example/rss" />
      <outline text="Feed B" xmlUrl="https://b.example/rss" />
    </outline>
    <outline text="News">
      <outline text="Feed C" xmlUrl="https://c.example/rss" />
    </outline>
    <outline text="Feed D" xmlUrl="https://d.example/rss" />
  </body>
</opml>
"""


# --- parse_opml (pure, untrusted input) ------------------------------------


def test_parse_extracts_categories_and_flat_feeds():
    parsed = parse_opml(VALID_OPML)

    assert [(e.title, e.feed_url, e.category_label) for e in parsed.entries] == [
        ("Feed A", "https://a.example/rss", "Tech"),
        ("Feed B", "https://b.example/rss", "Tech"),
        ("Feed C", "https://c.example/rss", "News"),
        ("Feed D", "https://d.example/rss", None),
    ]
    assert parsed.invalid_entries == 0
    assert parsed.duplicate_count == 0


def test_parse_prefers_text_over_title_attribute():
    parsed = parse_opml(
        b'<opml><body><outline title="T" text="Text" xmlUrl="https://x.example/rss" /></body></opml>'
    )
    assert parsed.entries[0].title == "Text"


def test_parse_counts_unusable_feed_urls_as_invalid():
    parsed = parse_opml(
        b"""<opml><body>
        <outline text="ftp feed" xmlUrl="ftp://a.example/rss" />
        <outline text="relative feed" xmlUrl="/feed.xml" />
        <outline text="ok feed" xmlUrl="https://ok.example/rss" />
        </body></opml>"""
    )
    assert len(parsed.entries) == 1
    assert parsed.entries[0].feed_url == "https://ok.example/rss"
    assert parsed.invalid_entries == 2


def test_parse_malformed_xml_is_opml_invalid():
    with pytest.raises(OpmlInvalid):
        parse_opml(b"<opml><body><outline></opml>")


def test_parse_non_opml_root_is_opml_invalid():
    with pytest.raises(OpmlInvalid):
        parse_opml(b"<html><body>nope</body></html>")


def test_parse_missing_body_is_opml_invalid():
    with pytest.raises(OpmlInvalid):
        parse_opml(b"<opml><head><title>x</title></head></opml>")


def test_parse_rejects_dtd_entities():
    """billion-laughs style payloads are rejected by defusedxml."""
    attack = (
        b'<?xml version="1.0"?><!DOCTYPE opml ['
        b'<!ENTITY a "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">'

        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">'
        b']><opml><body><outline text="&b;" /></body></opml>'
    )
    with pytest.raises(OpmlInvalid):
        parse_opml(attack)


def test_parse_deduplicates_repeated_feed_urls():
    parsed = parse_opml(
        b"""<opml><body>
        <outline text="A" xmlUrl="https://dup.example/rss" />
        <outline text="A again" xmlUrl="https://dup.example/rss" />
        </body></opml>"""
    )
    assert len(parsed.entries) == 1
    assert parsed.duplicate_count == 1
    assert parsed.file_duplicates[0].title == "A again"


def test_parse_too_many_feeds_is_rejected():
    feed = '<outline text="f" xmlUrl="https://x.example/%d" />'
    body = "".join(feed % i for i in range(MAX_OPML_FEEDS + 1))
    with pytest.raises(OpmlTooManyFeeds):
        parse_opml(f"<opml><body>{body}</body></opml>".encode())


def test_parse_too_deep_nesting_is_rejected():
    depth = MAX_OPML_DEPTH + 2
    xml = "<opml><body>" + '<outline text="l">' * depth + "</outline>" * depth
    with pytest.raises(OpmlInvalid):
        parse_opml(xml.encode())


def test_parse_oversized_payload_is_rejected_at_parse_level_too():
    with pytest.raises(OpmlTooLarge):
        parse_opml(b"<opml>" + b"x" * (2 * 1024 * 1024 + 1))


def test_parse_flattens_nested_containers_onto_outermost_label():
    parsed = parse_opml(
        b"""<opml><body>
        <outline text="Outer"><outline text="Inner">
          <outline text="Feed" xmlUrl="https://x.example/rss" />
        </outline></outline>
        </body></opml>"""
    )
    assert parsed.entries[0].category_label == "Outer"


# --- fake control adapter ---------------------------------------------------


class FakeControlAdapter:
    def __init__(self) -> None:
        self.subscriptions = [
            Subscription(
                stream_id="feed/7",
                title="Existing Feed",
                feed_url="https://existing.example/rss",
            )
        ]
        self.categories = [Category("user/-/label/未分类", "未分类")]
        self.calls: list[tuple] = []
        # URL → exception to raise on subscribe
        self.subscribe_errors: dict[str, AdapterError] = {}
        # (stream_id, label) → exception on category move
        self.move_errors: dict[tuple, AdapterError] = {}
        self.next_id = 100

    async def list_subscriptions(self):
        self.calls.append(("list_subscriptions",))
        return list(self.subscriptions)

    async def list_categories(self):
        self.calls.append(("list_categories",))
        return list(self.categories)

    async def subscribe(self, feed_url, *, category_id=None, title=None):
        self.calls.append(("subscribe", feed_url, title))
        if feed_url in self.subscribe_errors:
            raise self.subscribe_errors[feed_url]
        self.next_id += 1
        subscription = Subscription(
            stream_id=f"feed/{self.next_id}",
            title=title or feed_url,
            feed_url=feed_url,
        )
        self.subscriptions.append(subscription)
        return subscription

    async def move_category(self, stream_id, category_id):
        self.calls.append(("move_category", stream_id, category_id))
        if (stream_id, category_id) in self.move_errors:
            raise self.move_errors[(stream_id, category_id)]

    async def move_to_new_category(self, stream_id, label):
        self.calls.append(("move_to_new_category", stream_id, label))
        if (stream_id, label) in self.move_errors:
            raise self.move_errors[(stream_id, label)]
        self.categories.append(
            Category(f"user/-/label/{label}", label)
        )


OPML_MIX = b"""<?xml version="1.0"?>
<opml version="2.0"><body>
  <outline text="Tech">
    <outline text="New Feed" xmlUrl="https://new.example/rss" />
    <outline text="Existing Feed" xmlUrl="https://existing.example/rss" />
    <outline text="Broken Feed" xmlUrl="https://broken.example/rss" />
    <outline text="Dupe" xmlUrl="https://new.example/rss" />
  </outline>
  <outline text="Feed Flat" xmlUrl="https://flat.example/rss" />
</body></opml>
"""


@pytest.mark.anyio
async def test_preview_counts_without_any_mutation():
    fake = FakeControlAdapter()
    fake.subscribe_errors["https://broken.example/rss"] = FeedRejectedError("no")
    service = OpmlService(fake)

    preview = await service.preview(OPML_MIX)

    assert preview == {
        "totalFeeds": 4,
        "newFeeds": 3,
        "duplicates": 2,  # already-subscribed + in-file repeat
        "invalidEntries": 0,
        "categories": [{"label": "Tech", "feedCount": 3}],
    }
    # strictly read-only: only the list call happened
    assert fake.calls == [("list_subscriptions",)]


@pytest.mark.anyio
async def test_import_merges_new_feeds_and_reports_everything():
    fake = FakeControlAdapter()
    fake.subscribe_errors["https://broken.example/rss"] = FeedRejectedError(
        "FreshRSS refused to add this feed."
    )
    service = OpmlService(fake)

    result = await service.import_opml(OPML_MIX)

    assert [a["feedUrl"] for a in result["added"]] == [
        "https://new.example/rss",
        "https://flat.example/rss",
    ]
    # New Feed carries its OPML title
    assert result["added"][0]["title"] == "New Feed"
    # duplicates reported honestly (already-subscribed + in-file repeat),
    # never subscribed
    assert result["duplicates"] == [
        {"feedUrl": "https://new.example/rss", "title": "Dupe"},
        {"feedUrl": "https://existing.example/rss", "title": "Existing Feed"},
    ]
    assert result["failed"] == [
        {
            "feedUrl": "https://broken.example/rss",
            "title": "Broken Feed",
            "error": "feed_rejected",
        }
    ]
    # Tech was created by the first move; the flat feed stays uncategorized
    assert result["categoriesCreated"] == ["Tech"]
    assert result["added"][0]["categoryLabel"] == "Tech"
    assert result["added"][0]["categoryApplied"] is True
    assert result["added"][1]["categoryLabel"] is None
    assert result["added"][1]["categoryApplied"] is False
    # subscribe exactly once per new feed (the broken one fails AFTER its
    # single attempt — no retry); the existing one is never subscribed
    subscribes = [c for c in fake.calls if c[0] == "subscribe"]
    assert subscribes == [
        ("subscribe", "https://new.example/rss", "New Feed"),
        ("subscribe", "https://broken.example/rss", "Broken Feed"),
        ("subscribe", "https://flat.example/rss", "Feed Flat"),
    ]


@pytest.mark.anyio
async def test_import_reuses_created_category_for_second_feed():
    """Two feeds of the same NEW category: one create-move, one plain move."""
    opml = b"""<opml><body><outline text="AI">
      <outline text="A" xmlUrl="https://a.example/rss" />
      <outline text="B" xmlUrl="https://b.example/rss" />
    </outline></body></opml>"""
    fake = FakeControlAdapter()
    service = OpmlService(fake)

    result = await service.import_opml(opml)

    moves = [c for c in fake.calls if c[0].startswith("move_")]
    assert moves[0] == ("move_to_new_category", "feed/101", "AI")
    assert moves[1] == ("move_category", "feed/102", "user/-/label/AI")
    assert result["categoriesCreated"] == ["AI"]


@pytest.mark.anyio
async def test_import_reuses_existing_category_by_label():
    opml = """<opml><body><outline text="未分类">
      <outline text="A" xmlUrl="https://a.example/rss" />
    </outline></body></opml>""".encode()
    fake = FakeControlAdapter()
    service = OpmlService(fake)

    result = await service.import_opml(opml)

    moves = [c for c in fake.calls if c[0].startswith("move_")]
    assert moves == [("move_category", "feed/101", "user/-/label/未分类")]
    assert result["categoriesCreated"] == []
    assert result["added"][0]["categoryApplied"] is True


@pytest.mark.anyio
async def test_import_reserved_english_default_label_means_no_move():
    """OPML label "Uncategorized" = FreshRSS default category — subscribe
    already lands there, no move is attempted (and no duplicate-looking
    real category can be minted)."""
    opml = b"""<opml><body><outline text="Uncategorized">
      <outline text="A" xmlUrl="https://a.example/rss" />
    </outline></body></opml>"""
    fake = FakeControlAdapter()
    service = OpmlService(fake)

    result = await service.import_opml(opml)

    assert [c for c in fake.calls if c[0].startswith("move_")] == []
    assert result["added"][0]["categoryLabel"] == "Uncategorized"
    assert result["added"][0]["categoryApplied"] is False


@pytest.mark.anyio
async def test_import_survives_category_move_failure():
    """A failed category move never undoes the subscription — the feed
    stays in the default category and the result says so honestly."""
    opml = b"""<opml><body><outline text="Tech">
      <outline text="A" xmlUrl="https://a.example/rss" />
    </outline></body></opml>"""
    fake = FakeControlAdapter()
    fake.move_errors[("feed/101", "Tech")] = UpstreamError("nope")
    service = OpmlService(fake)

    result = await service.import_opml(opml)

    assert len(result["added"]) == 1
    assert result["added"][0]["categoryApplied"] is False
    assert result["categoriesCreated"] == []


@pytest.mark.anyio
async def test_import_maps_failure_codes_honestly():
    opml = b"""<opml><body>
      <outline text="A" xmlUrl="https://conn.example/rss" />
      <outline text="B" xmlUrl="https://auth.example/rss" />
      <outline text="C" xmlUrl="https://up.example/rss" />
    </body></opml>"""
    fake = FakeControlAdapter()
    fake.subscribe_errors["https://conn.example/rss"] = UpstreamConnectionError(
        "down"
    )
    fake.subscribe_errors["https://auth.example/rss"] = AuthenticationError("bad")
    fake.subscribe_errors["https://up.example/rss"] = UpstreamError("weird")
    service = OpmlService(fake)

    result = await service.import_opml(opml)

    assert [f["error"] for f in result["failed"]] == [
        "connection_error",
        "authentication_error",
        "upstream_error",
    ]
    assert result["added"] == []


@pytest.mark.anyio
async def test_import_propagates_upstream_failure_before_any_write():
    fake = FakeControlAdapter()
    fake.calls.clear()

    class DownControl(FakeControlAdapter):
        async def list_subscriptions(self):
            raise UpstreamConnectionError("FreshRSS is down.")

    service = OpmlService(DownControl())
    with pytest.raises(UpstreamConnectionError):
        await service.import_opml(VALID_OPML)


# --- export via control adapter (mocked FreshRSS) ---------------------------

EXPORT_BODY = b'<?xml version="1.0"?><opml version="2.0"><body><outline text="f" xmlUrl="https://a.example/rss"/></body></opml>'


def make_export_control(handler) -> object:
    from lumirss.adapters.freshrss import FreshRSSAdapter
    from lumirss.adapters.freshrss_control import FreshRSSControlAdapter
    from lumirss.config import FreshRSSSettings

    settings = FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL="http://freshrss-test.local",
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD="fake-test-password",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    return FreshRSSControlAdapter(FreshRSSAdapter(client, settings))


def export_handler(status: int = 200, body: bytes = EXPORT_BODY):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text="Auth=fake-token\n")
        if path.endswith("/reader/api/0/subscription/export"):
            if status == 401 and request.headers.get("Authorization") == "GoogleLogin auth=fake-token":
                # stale token once, then the re-login retry succeeds
                return httpx.Response(401)
            return httpx.Response(status, content=body)
        raise AssertionError(f"unexpected endpoint: {path}")

    return handler


@pytest.mark.anyio
async def test_export_opml_returns_upstream_document():
    control = make_export_control(export_handler())
    assert await control.export_opml() == EXPORT_BODY


@pytest.mark.anyio
async def test_export_opml_retries_once_on_stale_auth_token():
    control = make_export_control(export_handler())
    # first auth token is rejected once → re-login → retry succeeds
    assert await control.export_opml() == EXPORT_BODY


@pytest.mark.anyio
async def test_export_opml_non_200_is_upstream_error():
    control = make_export_control(export_handler(status=500))
    with pytest.raises(UpstreamError):
        await control.export_opml()


@pytest.mark.anyio
async def test_export_opml_garbage_body_is_upstream_error():
    control = make_export_control(
        export_handler(body=b"<html>not opml at all</html>")
    )
    with pytest.raises(UpstreamError):
        await control.export_opml()


# --- routes (fake adapter injected onto app.state) --------------------------


class RouteControlAdapter(FakeControlAdapter):
    async def export_opml(self):
        self.calls.append(("export_opml",))
        return EXPORT_BODY


def call(fake, method, path, **kwargs):
    try:
        with TestClient(app) as client:
            app.state.freshrss_control_adapter = fake
            return client.request(method, path, **kwargs)
    finally:
        app.state.freshrss_control_adapter = None


def test_export_route_streams_attachment():
    fake = RouteControlAdapter()
    response = call(fake, "GET", "/api/v1/opml/export")

    assert response.status_code == 200
    assert response.text.encode() == EXPORT_BODY
    assert response.headers["content-type"].startswith("text/x-opml")
    assert response.headers["content-disposition"] == (
        'attachment; filename="LumiRSS-subscriptions.opml"'
    )
    assert fake.calls == [("export_opml",)]


def test_preview_route_is_non_mutating():
    fake = RouteControlAdapter()
    response = call(fake, "POST", "/api/v1/opml/import/preview", content=VALID_OPML)

    assert response.status_code == 200
    assert response.json() == {
        "totalFeeds": 4,
        "newFeeds": 4,
        "duplicates": 0,
        "invalidEntries": 0,
        "categories": [
            {"label": "News", "feedCount": 1},
            {"label": "Tech", "feedCount": 2},
        ],
    }
    # read-only proof: only the list call, no subscribe/move/export
    assert fake.calls == [("list_subscriptions",)]


def test_import_route_merges_and_reports():
    fake = RouteControlAdapter()
    response = call(fake, "POST", "/api/v1/opml/import", content=OPML_MIX)

    assert response.status_code == 200
    body = response.json()
    assert [a["feedUrl"] for a in body["added"]] == [
        "https://new.example/rss",
        "https://broken.example/rss",
        "https://flat.example/rss",
    ]
    assert len(body["duplicates"]) == 2
    assert body["categoriesCreated"] == ["Tech"]
    # merge proof: the existing subscription was never touched
    unsubscribes = [c for c in fake.calls if c[0] == "unsubscribe"]
    assert unsubscribes == []


def test_preview_route_malformed_xml_is_400_opml_invalid():
    fake = RouteControlAdapter()
    response = call(
        fake, "POST", "/api/v1/opml/import/preview", content=b"<not-xml"
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "opml_invalid"
    # rejected before any FreshRSS call
    assert fake.calls == []


def test_import_route_malformed_xml_is_400_opml_invalid():
    fake = RouteControlAdapter()
    response = call(fake, "POST", "/api/v1/opml/import", content=b"garbage")
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "opml_invalid"
    assert fake.calls == []


def test_preview_route_oversized_upload_is_413():
    fake = RouteControlAdapter()
    big = b"<opml><body>" + b"x" * (2 * 1024 * 1024 + 10) + b"</body></opml>"
    response = call(fake, "POST", "/api/v1/opml/import/preview", content=big)
    assert response.status_code == 413
    assert response.json()["error"]["type"] == "opml_too_large"
    assert fake.calls == []


def test_import_route_too_many_feeds_is_400():
    fake = RouteControlAdapter()
    feed = '<outline text="f" xmlUrl="https://x.example/%d" />'
    body = "".join(feed % i for i in range(MAX_OPML_FEEDS + 1))
    xml = f"<opml><body>{body}</body></opml>".encode()
    response = call(fake, "POST", "/api/v1/opml/import", content=xml)
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "opml_too_many_feeds"
    assert fake.calls == []


def test_export_route_maps_upstream_error():
    class Broken(RouteControlAdapter):
        async def export_opml(self):
            raise UpstreamError("FreshRSS export failed.")

    response = call(Broken(), "GET", "/api/v1/opml/export")
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "upstream_error"


def test_freshrss_ui_route_returns_configured_public_url(monkeypatch):
    monkeypatch.setenv("FRESHRSS_BASE_URL", "http://freshrss:80")  # internal
    monkeypatch.setenv("FRESHRSS_USERNAME", "user")
    monkeypatch.setenv("FRESHRSS_API_PASSWORD", "pw")
    monkeypatch.setenv("FRESHRSS_PUBLIC_URL", "https://rss.example.com")
    response = call(RouteControlAdapter(), "GET", "/api/v1/freshrss-ui")
    assert response.status_code == 200
    # the internal base URL is never exposed — only the explicit public URL
    assert response.json() == {"url": "https://rss.example.com"}


def test_freshrss_ui_route_returns_null_when_unset(monkeypatch):
    monkeypatch.setenv("FRESHRSS_BASE_URL", "http://freshrss:80")
    monkeypatch.setenv("FRESHRSS_USERNAME", "user")
    monkeypatch.setenv("FRESHRSS_API_PASSWORD", "pw")
    monkeypatch.delenv("FRESHRSS_PUBLIC_URL", raising=False)
    response = call(RouteControlAdapter(), "GET", "/api/v1/freshrss-ui")
    assert response.status_code == 200
    assert response.json() == {"url": None}


def test_freshrss_ui_route_ignores_unsafe_public_url(monkeypatch):
    monkeypatch.setenv("FRESHRSS_BASE_URL", "http://freshrss:80")
    monkeypatch.setenv("FRESHRSS_USERNAME", "user")
    monkeypatch.setenv("FRESHRSS_API_PASSWORD", "pw")
    monkeypatch.setenv("FRESHRSS_PUBLIC_URL", "https://user:pw@rss.example.com")
    response = call(RouteControlAdapter(), "GET", "/api/v1/freshrss-ui")
    assert response.status_code == 200
    assert response.json() == {"url": None}
