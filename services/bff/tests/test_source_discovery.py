"""0014 — source discovery: website → RSS/Atom candidates.

No real network: httpx.MockTransport serves page bytes, DNS is a fake
resolver, and the discovery service holds NO FreshRSS reference at all
(read-only by construction — there is nothing to assert against a control
adapter here, by design).
"""

import socket

import httpx
import pytest

from lumirss.feed_preview import FeedFetchError, FeedTooLarge, NotAFeedError, UnsafeFeedUrl
from lumirss.source_discovery import (
    COMMON_FEED_PATHS,
    DiscoveryCandidate,
    InvalidSourceUrl,
    NoFeedDiscovered,
    SourceDiscoveryService,
    extract_declared_feed_links,
)

PAGE_URL = "https://blog.example/posts/hello"
PUBLIC = "93.184.216.34"
PRIVATE = "10.0.0.8"

RSS_DOC = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Blog Feed</title><link>https://blog.example/</link>
  <description>d</description>
</channel></rss>"""

ATOM_DOC = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title><link href="https://blog.example/"/>
</feed>"""

HTML_DECLARED = b"""<!DOCTYPE html><html><head>
<title>Blog</title>
<link rel="alternate" type="application/rss+xml" title="RSS 2.0"
      href="/rss.xml">
<link rel="alternate" type="application/atom+xml" title="Atom"
      href="https://cdn.example/atom.xml">
</head><body><p>hi</p></body></html>"""

HTML_NO_FEED = b"<!DOCTYPE html><html><head><title>X</title></head><body></body></html>"


class FakeResolver:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self.mapping = dict(mapping)
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> list[str]:
        self.calls.append((host, port))
        if host not in self.mapping:
            raise socket.gaierror(8, "Name or service not known")
        return self.mapping[host]


def html_response(body: bytes, content_type: str = "text/html; charset=utf-8") -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": content_type})


def xml_response(body: bytes = RSS_DOC) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": "application/rss+xml"})


@pytest.mark.anyio
async def discover_with(
    handler,
    *,
    url: str = PAGE_URL,
    resolver_map: dict[str, list[str]] | None = None,
    common_feed_paths: tuple[str, ...] = COMMON_FEED_PATHS,
):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resolver = FakeResolver(
        resolver_map if resolver_map is not None else {"blog.example": [PUBLIC]}
    )
    service = SourceDiscoveryService(
        client, resolver=resolver, common_feed_paths=common_feed_paths
    )
    try:
        result = await service.discover(url)
        return result, resolver
    finally:
        await client.aclose()


# --- declared link extraction (pure function) ------------------------------


def test_extract_declared_links_resolves_relative_and_absolute():
    candidates = extract_declared_feed_links(HTML_DECLARED, PAGE_URL)
    assert [c.feed_url for c in candidates] == [
        "https://blog.example/rss.xml",
        "https://cdn.example/atom.xml",
    ]
    assert [c.source for c in candidates] == ["declared", "declared"]
    assert [c.format for c in candidates] == [None, None]
    assert candidates[0].title == "RSS 2.0"


def test_extract_declared_links_deduplicates():
    html = b"""<html><head>
<link rel="alternate" type="application/rss+xml" href="/feed.xml">
<link rel="alternate" type="application/rss+xml" href="/feed.xml#frag">
<link rel="alternate" type="application/rss+xml" href="/feed.xml">
</head></html>"""
    candidates = extract_declared_feed_links(html, "https://site.example/index.html")
    assert len(candidates) == 1
    assert candidates[0].feed_url == "https://site.example/feed.xml"


def test_extract_declared_links_skips_malformed_and_non_feed():
    html = b"""<html><head>
<link rel="alternate" type="application/rss+xml" href="javascript:alert(1)">
<link rel="alternate" type="application/rss+xml" href="ftp://x.example/f">
<link rel="alternate" type="application/rss+xml" href="">
<link rel="alternate" type="application/json" href="/data.json">
<link rel="alternate" href="/page.html">
<link rel="stylesheet" type="text/css" href="/site.css">
</head></html>"""
    assert extract_declared_feed_links(html, "https://site.example/") == []


def test_extract_declared_links_accepts_typeless_feedish_href():
    html = b"""<html><head>
<link rel="alternate" href="/index.xml">
<link rel="alternate" href="/notes">
</head></html>"""
    candidates = extract_declared_feed_links(html, "https://site.example/")
    assert [c.feed_url for c in candidates] == ["https://site.example/index.xml"]


def test_extract_declared_links_skips_credentialed_href():
    html = b"""<html><head>
<link rel="alternate" type="application/rss+xml" href="https://u:p@evil.example/f.xml">
</head></html>"""
    assert extract_declared_feed_links(html, "https://site.example/") == []


# --- service: direct feed URL ----------------------------------------------


@pytest.mark.anyio
async def test_discover_direct_feed_url_returns_single_candidate():
    result, _ = await discover_with(lambda request: xml_response())
    assert result == [
        DiscoveryCandidate(
            feed_url=PAGE_URL, title="Blog Feed", source="declared", format="rss"
        )
    ]


@pytest.mark.anyio
async def test_discover_declared_links_without_fetching_them():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return html_response(HTML_DECLARED)

    result, _ = await discover_with(handler)
    assert [c.feed_url for c in result] == [
        "https://blog.example/rss.xml",
        "https://cdn.example/atom.xml",
    ]
    # Only the page itself was fetched — declared candidates are NOT fetched.
    assert [r.url.path for r in requests] == ["/posts/hello"]


# --- service: probing ------------------------------------------------------


@pytest.mark.anyio
async def test_discover_probes_when_no_declared_links():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/posts/hello":
            return html_response(HTML_NO_FEED)
        if request.url.path == "/feed":
            return xml_response(ATOM_DOC)
        return httpx.Response(404)

    result, _ = await discover_with(handler)
    assert len(result) == 1
    assert result[0].feed_url == "https://blog.example/feed"
    assert result[0].source == "probed"
    assert result[0].format == "atom"
    assert result[0].title == "Atom Feed"


@pytest.mark.anyio
async def test_discover_probe_first_success_wins():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/posts/hello":
            return html_response(HTML_NO_FEED)
        if request.url.path == "/rss.xml":
            return xml_response()
        return httpx.Response(404)

    result, _ = await discover_with(handler)
    assert result[0].feed_url == "https://blog.example/rss.xml"
    # /feed failed first, /rss failed second, /rss.xml succeeded: probing
    # stopped there — /atom.xml and /feed.xml were never attempted.
    assert seen == ["/posts/hello", "/feed", "/rss", "/rss.xml"]


@pytest.mark.anyio
async def test_discover_probing_skips_non_feed_endpoints():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/posts/hello":
            return html_response(HTML_NO_FEED)
        if request.url.path == "/feed":
            return html_response(b"<html>not a feed</html>")
        if request.url.path == "/atom.xml":
            return xml_response(ATOM_DOC)
        return httpx.Response(404)

    result, _ = await discover_with(handler)
    assert result[0].feed_url == "https://blog.example/atom.xml"


@pytest.mark.anyio
async def test_discover_no_feed_anywhere():
    def handler(request: httpx.Request) -> httpx.Response:
        return (
            html_response(HTML_NO_FEED)
            if request.url.path == "/posts/hello"
            else httpx.Response(404)
        )

    with pytest.raises(NoFeedDiscovered):
        await discover_with(handler)


@pytest.mark.anyio
async def test_discover_non_html_non_feed_does_not_probe():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"ok": true}',
            headers={"content-type": "application/json"},
        )

    with pytest.raises(NoFeedDiscovered):
        await discover_with(handler)


# --- service: URL / network failures ---------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "file:///etc/passwd",
        "not-a-url",
        "",
        "https://",
    ],
)
@pytest.mark.anyio
async def test_discover_invalid_url(url):
    with pytest.raises(InvalidSourceUrl):
        await discover_with(lambda request: html_response(HTML_NO_FEED), url=url)


@pytest.mark.anyio
async def test_discover_credentialed_url_is_unsafe():
    with pytest.raises(UnsafeFeedUrl):
        await discover_with(
            lambda request: html_response(HTML_NO_FEED),
            url="https://user:pass@example.com/",
        )


@pytest.mark.anyio
async def test_discover_unsafe_destination():
    def handler(request: httpx.Request) -> httpx.Response:
        return html_response(HTML_NO_FEED)

    with pytest.raises(UnsafeFeedUrl):
        await discover_with(
            handler, resolver_map={"blog.example": [PRIVATE]}
        )


@pytest.mark.anyio
async def test_discover_redirect_to_private_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://intranet.example/admin"},
        )

    with pytest.raises(UnsafeFeedUrl):
        await discover_with(
            handler,
            resolver_map={
                "blog.example": [PUBLIC],
                "intranet.example": [PRIVATE],
            },
        )


@pytest.mark.anyio
async def test_discover_resolves_relative_links_after_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/posts/hello":
            return httpx.Response(302, headers={"location": "https://blog.example/new-home"})
        if request.url.path == "/new-home":
            return html_response(
                b'<html><head><link rel="alternate" type="application/rss+xml" href="feed.xml"></head></html>'
            )
        return httpx.Response(404)

    result, _ = await discover_with(handler)
    assert result[0].feed_url == "https://blog.example/feed.xml"


@pytest.mark.anyio
async def test_discover_timeout_maps_to_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(FeedFetchError):
        await discover_with(handler)


@pytest.mark.anyio
async def test_discover_http_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(FeedFetchError):
        await discover_with(handler)


@pytest.mark.anyio
async def test_discover_oversized_page():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"x" * (2 * 1024 * 1024 + 1), headers={"content-type": "text/html"}
        )

    with pytest.raises(FeedTooLarge):
        await discover_with(handler)


# --- route level ------------------------------------------------------------


from lumirss.main import app  # noqa: E402


def ok_json(data: httpx.Response):
    assert data.status_code == 200


async def post_discovery(url: str, handler, resolver_map=None):
    """Route-level call with injected MockTransport + fake resolver."""
    from lumirss.source_discovery import SourceDiscoveryService as Svc

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resolver = FakeResolver(
        resolver_map if resolver_map is not None else {"blog.example": [PUBLIC]}
    )
    app.state.http_client = client
    app.state.source_discovery_service = Svc(client, resolver=resolver)
    try:
        from httpx import ASGITransport

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as route_client:
            return await route_client.post(
                "/api/v1/source-discovery", json={"url": url}
            )
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_route_returns_candidates():
    def handler(request: httpx.Request) -> httpx.Response:
        return html_response(HTML_DECLARED)

    response = await post_discovery(PAGE_URL, handler)
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert candidates == [
        {
            "feedUrl": "https://blog.example/rss.xml",
            "title": "RSS 2.0",
            "source": "declared",
            "format": None,
        },
        {
            "feedUrl": "https://cdn.example/atom.xml",
            "title": "Atom",
            "source": "declared",
            "format": None,
        },
    ]


@pytest.mark.anyio
async def test_route_no_feed_discovered_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return (
            html_response(HTML_NO_FEED)
            if request.url.path == "/posts/hello"
            else httpx.Response(404)
        )

    response = await post_discovery(PAGE_URL, handler)
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "no_feed_discovered"


@pytest.mark.anyio
async def test_route_invalid_url_400():
    response = await post_discovery("ftp://x", lambda request: html_response(HTML_NO_FEED))
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_source_url"


@pytest.mark.anyio
async def test_route_unsafe_url_400():
    def handler(request: httpx.Request) -> httpx.Response:
        return html_response(HTML_NO_FEED)

    response = await post_discovery(
        PAGE_URL, handler, resolver_map={"blog.example": [PRIVATE]}
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "unsafe_feed_url"
