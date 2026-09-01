"""0013 Gate 2 — feed preview: safe-fetch boundary + offline parse + route.

No real network: httpx.MockTransport serves the feed bytes, DNS is a
fake resolver, and the FreshRSS control adapter is a recording fake whose
mutation methods fail the test if preview ever calls them — preview must
be strictly non-mutating.
"""

import socket

import httpx
import pytest

from lumirss.adapters.freshrss_control import InvalidFeedUrl, Subscription
from lumirss.feed_preview import (
    FeedFetchError,
    FeedPreview,
    FeedPreviewService,
    FeedTooLarge,
    NotAFeedError,
    UnsafeFeedUrl,
    ensure_public_address,
    parse_feed_document,
    validate_feed_url,
)
from lumirss.main import app

FEED_URL = "https://feed.example/feed.xml"
PUBLIC = "93.184.216.34"

RSS_DOC = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test RSS Feed</title>
  <link>https://example.com/</link>
  <description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
</channel></rss>"""

ATOM_DOC = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Feed</title>
  <subtitle>An atom subtitle</subtitle>
  <link href="https://example.org/"/>
</feed>"""

RDF_DOC = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/">
  <channel rdf:about="https://example.net/">
    <title>Test RDF Feed</title>
    <description>rdf description</description>
  </channel>
</rdf:RDF>"""

HTML_DOC = b"<html><head><title>Just a page</title></head><body><p>hi</p></body></html>"


class FakeControl:
    """Read-only recording control adapter; mutations abort the test."""

    def __init__(self, existing_urls=()) -> None:
        self.existing_urls = list(existing_urls)
        self.calls: list[tuple] = []

    async def list_subscriptions(self):
        self.calls.append(("list_subscriptions",))
        return [
            Subscription(stream_id=f"feed/{i + 1}", title=url, feed_url=url)
            for i, url in enumerate(self.existing_urls)
        ]

    async def subscribe(self, *args, **kwargs):  # pragma: no cover - must not run
        self.calls.append(("subscribe", *args))
        raise AssertionError("preview must never subscribe")

    async def unsubscribe(self, *args, **kwargs):  # pragma: no cover - must not run
        self.calls.append(("unsubscribe", *args))
        raise AssertionError("preview must never unsubscribe")

    async def move_category(self, *args, **kwargs):  # pragma: no cover - must not run
        self.calls.append(("move_category", *args))
        raise AssertionError("preview must never move a subscription")

    async def rename_category(self, *args, **kwargs):  # pragma: no cover - must not run
        self.calls.append(("rename_category", *args))
        raise AssertionError("preview must never rename a category")


class FakeResolver:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self.mapping = dict(mapping)
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> list[str]:
        self.calls.append((host, port))
        if host not in self.mapping:
            raise socket.gaierror(8, "Name or service not known")
        return self.mapping[host]


async def preview_with(
    handler,
    *,
    feed_url: str = FEED_URL,
    existing=(),
    resolver_map: dict[str, list[str]] | None = None,
):
    """Run one preview over MockTransport + fake DNS + recording control."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    control = FakeControl(existing)
    resolver = FakeResolver(
        resolver_map if resolver_map is not None else {"feed.example": [PUBLIC]}
    )
    service = FeedPreviewService(client, control, resolver=resolver)
    try:
        result = await service.preview(feed_url)
        return result, control, resolver
    finally:
        await client.aclose()


def ok(body: bytes = RSS_DOC) -> httpx.Response:
    return httpx.Response(200, content=body)


# --- URL validation ------------------------------------------------------


def test_validate_feed_url_accepts_http_and_https():
    assert validate_feed_url("https://example.com/feed.xml").hostname == "example.com"
    assert validate_feed_url("http://example.com:8080/rss").port == 8080


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/feed.xml",
        "file:///etc/passwd",
        "gopher://example.com",
        "example.com/feed.xml",
        "/feed.xml",
        "https://",
        "",
        "x" * 2049,
        "https://example.com:99999/feed.xml",
    ],
)
def test_validate_feed_url_rejects_malformed(url):
    with pytest.raises(InvalidFeedUrl):
        validate_feed_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@example.com/feed.xml",
        "http://user@example.com/feed.xml",
    ],
)
def test_validate_feed_url_rejects_credentials(url):
    with pytest.raises(UnsafeFeedUrl):
        validate_feed_url(url)


# --- IP boundary ---------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    ["8.8.8.8", "1.1.1.1", "2606:4700::1111", "2600::1"],
)
def test_public_addresses_are_allowed(address):
    ensure_public_address(address)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",  # cloud metadata
        "0.0.0.0",
        "100.64.0.1",  # carrier-grade NAT
        "224.0.0.1",
        "255.255.255.255",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",  # IPv4-mapped
        "64:ff9b::7f00:1",  # NAT64 → 127.0.0.1
    ],
)
def test_unsafe_addresses_are_rejected(address):
    with pytest.raises(UnsafeFeedUrl):
        ensure_public_address(address)


# --- offline parse -------------------------------------------------------


def test_parse_rss_document_metadata():
    title, site_url, description, feed_format = parse_feed_document(RSS_DOC)
    assert title == "Test RSS Feed"
    assert site_url == "https://example.com/"
    assert description == "Hello world"  # HTML stripped
    assert feed_format == "rss"


def test_parse_atom_document_metadata():
    title, site_url, description, feed_format = parse_feed_document(ATOM_DOC)
    assert title == "Test Atom Feed"
    assert site_url == "https://example.org/"
    assert description == "An atom subtitle"
    assert feed_format == "atom"


def test_parse_rdf_document_is_rss():
    title, _, _, feed_format = parse_feed_document(RDF_DOC)
    assert title == "Test RDF Feed"
    assert feed_format == "rss"


def test_parse_html_page_is_not_a_feed():
    with pytest.raises(NotAFeedError):
        parse_feed_document(HTML_DOC)


def test_parse_feed_without_title_is_not_a_feed():
    doc = b"<rss version='2.0'><channel><link>https://x.example/</link></channel></rss>"
    with pytest.raises(NotAFeedError):
        parse_feed_document(doc)


def test_parse_feed_ignores_unsafe_site_link():
    doc = (
        b"<rss version='2.0'><channel><title>T</title>"
        b"<link>javascript:alert(1)</link></channel></rss>"
    )
    _, site_url, _, _ = parse_feed_document(doc)
    assert site_url is None


# --- service: happy paths ------------------------------------------------


@pytest.mark.anyio
async def test_preview_rss_returns_metadata_and_is_non_mutating():
    result, control, _ = await preview_with(lambda request: ok())
    assert result == FeedPreview(
        title="Test RSS Feed",
        feed_url=FEED_URL,
        site_url="https://example.com/",
        description="Hello world",
        format="rss",
        already_subscribed=False,
    )
    # 无副作用证明：preview 只读了订阅列表，从未触碰任何 mutation。
    assert control.calls == [("list_subscriptions",)]


@pytest.mark.anyio
async def test_preview_atom_returns_metadata():
    result, control, _ = await preview_with(lambda request: ok(ATOM_DOC))
    assert result.format == "atom"
    assert result.title == "Test Atom Feed"
    assert control.calls == [("list_subscriptions",)]


@pytest.mark.anyio
async def test_preview_flags_already_subscribed_by_exact_url():
    result, _, _ = await preview_with(
        lambda request: ok(), existing=[FEED_URL]
    )
    assert result.already_subscribed is True


@pytest.mark.anyio
async def test_preview_works_over_ipv6_host():
    result, _, _ = await preview_with(
        lambda request: ok(),
        feed_url="https://v6.example/feed.xml",
        resolver_map={"v6.example": ["2606:4700::1111"]},
    )
    assert result.format == "rss"


# --- service: fetch boundary ----------------------------------------------


@pytest.mark.anyio
async def test_preview_follows_redirect_and_revalidates_each_hop():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed.xml":
            return httpx.Response(
                301, headers={"Location": "https://hop.example/moved.xml"}
            )
        return ok()

    result, _, resolver = await preview_with(
        handler,
        resolver_map={
            "feed.example": [PUBLIC],
            "hop.example": ["1.2.3.4"],
        },
    )
    assert result.title == "Test RSS Feed"
    # 每一跳都重新做了 DNS/IP 校验（不是只验第一跳）。
    assert resolver.calls == [
        ("feed.example", 443),
        ("hop.example", 443),
    ]


@pytest.mark.anyio
async def test_preview_blocks_redirect_to_private_address():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://internal.example/x.xml"})

    with pytest.raises(UnsafeFeedUrl):
        await preview_with(
            handler,
            resolver_map={
                "feed.example": [PUBLIC],
                "internal.example": ["10.0.0.5"],
            },
        )


@pytest.mark.anyio
async def test_preview_blocks_redirect_to_localhost():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://localhost/feed.xml"})

    with pytest.raises(UnsafeFeedUrl):
        await preview_with(
            handler,
            resolver_map={
                "feed.example": [PUBLIC],
                "localhost": ["127.0.0.1"],
            },
        )


@pytest.mark.anyio
async def test_preview_rejects_redirect_loop_after_bound():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": FEED_URL})

    with pytest.raises(FeedFetchError):
        await preview_with(handler)


@pytest.mark.anyio
async def test_preview_rejects_non_http_redirect_target():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "ftp://feed.example/x.xml"})

    with pytest.raises(InvalidFeedUrl):
        await preview_with(handler)


@pytest.mark.anyio
async def test_preview_blocks_localhost_host_before_any_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not be reached")

    with pytest.raises(UnsafeFeedUrl):
        await preview_with(
            handler,
            feed_url="http://127.0.0.1:8000/feed.xml",
            resolver_map={"127.0.0.1": ["127.0.0.1"]},
        )


@pytest.mark.anyio
async def test_preview_unresolvable_host_is_fetch_error():
    with pytest.raises(FeedFetchError):
        await preview_with(lambda request: ok(), resolver_map={})


@pytest.mark.anyio
async def test_preview_http_error_status_is_fetch_error():
    with pytest.raises(FeedFetchError):
        await preview_with(lambda request: httpx.Response(404, text="nope"))


@pytest.mark.anyio
async def test_preview_connection_timeout_is_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(FeedFetchError):
        await preview_with(handler)


@pytest.mark.anyio
async def test_preview_oversized_content_length_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"Content-Length": str(3 * 1024 * 1024)}
        )

    with pytest.raises(FeedTooLarge):
        await preview_with(handler)


@pytest.mark.anyio
async def test_preview_oversized_streamed_body_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (3 * 1024 * 1024))

    with pytest.raises(FeedTooLarge):
        await preview_with(handler)


@pytest.mark.anyio
async def test_preview_html_page_is_not_a_feed():
    with pytest.raises(NotAFeedError):
        await preview_with(lambda request: ok(HTML_DOC))


@pytest.mark.anyio
async def test_preview_malformed_url_is_rejected_before_any_fetch():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not be reached")

    control = FakeControl()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FeedPreviewService(client, control)
    try:
        with pytest.raises(InvalidFeedUrl):
            await service.preview("javascript:alert(1)")
        assert control.calls == []
    finally:
        await client.aclose()


# --- route wiring ---------------------------------------------------------


class FakePreviewService:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    async def preview(self, feed_url: str) -> FeedPreview:
        self.calls.append(feed_url)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def call(service, json_body):
    from fastapi.testclient import TestClient

    try:
        with TestClient(app) as client:
            app.state.feed_preview_service = service
            return client.post("/api/v1/feed-preview", json=json_body)
    finally:
        app.state.feed_preview_service = None


def sample_preview() -> FeedPreview:
    return FeedPreview(
        title="Test RSS Feed",
        feed_url=FEED_URL,
        site_url="https://example.com/",
        description="Hello world",
        format="rss",
        already_subscribed=False,
    )


def test_preview_route_returns_metadata_shape():
    service = FakePreviewService(result=sample_preview())
    response = call(service, {"feedUrl": FEED_URL})

    assert response.status_code == 200
    assert response.json() == {
        "title": "Test RSS Feed",
        "feedUrl": FEED_URL,
        "siteUrl": "https://example.com/",
        "description": "Hello world",
        "format": "rss",
        "alreadySubscribed": False,
    }
    assert service.calls == [FEED_URL]


@pytest.mark.parametrize(
    "error,status,error_type",
    [
        (InvalidFeedUrl("bad"), 400, "invalid_feed_url"),
        (UnsafeFeedUrl("private"), 400, "unsafe_feed_url"),
        (NotAFeedError("not feed"), 400, "not_a_feed"),
        (FeedFetchError("timeout"), 502, "feed_fetch_error"),
        (FeedTooLarge("too big"), 413, "feed_too_large"),
    ],
)
def test_preview_route_maps_stable_errors(error, status, error_type):
    service = FakePreviewService(error=error)
    response = call(service, {"feedUrl": FEED_URL})

    assert response.status_code == status
    assert response.json()["error"]["type"] == error_type


def test_preview_route_missing_body_is_422_without_service():
    service = FakePreviewService(result=sample_preview())
    response = call(service, {})

    assert response.status_code == 422
    assert service.calls == []


def test_preview_route_is_non_mutating_end_to_end():
    """Route-level 无副作用证明：真实 FeedPreviewService + MockTransport +
    记录型 control —— POST preview 后 FreshRSS 侧只有一次订阅列表读取，
    订阅数量不变，无任何 mutation 调用。"""
    from fastapi.testclient import TestClient

    control = FakeControl(existing_urls=[FEED_URL])
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: ok()))
    service = FeedPreviewService(
        client, control, resolver=FakeResolver({"feed.example": [PUBLIC]})
    )
    try:
        with TestClient(app) as client:
            app.state.feed_preview_service = service
            app.state.freshrss_control_adapter = control
            before = client.get("/api/v1/subscriptions").json()
            response = client.post("/api/v1/feed-preview", json={"feedUrl": FEED_URL})
            after = client.get("/api/v1/subscriptions").json()
    finally:
        app.state.feed_preview_service = None
        app.state.freshrss_control_adapter = None

    assert response.status_code == 200
    assert response.json()["alreadySubscribed"] is True
    # 订阅数量与内容完全未变；control 只被读过列表（before + preview 内部 + after）。
    assert before == after
    assert control.calls == [
        ("list_subscriptions",),
        ("list_subscriptions",),
        ("list_subscriptions",),
    ]
