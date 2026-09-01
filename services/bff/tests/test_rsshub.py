"""0014 — RSSHub: catalog contract, server-side construction, preview.

No real network: httpx.MockTransport serves feed bytes, the control
adapter is a recording fake whose mutation methods fail the test if
preview ever calls them (preview is strictly non-mutating). Settings are
injected via monkeypatched RssHubSettings so tests never read the real
.env.
"""

import httpx
import pytest
from pydantic import ValidationError

from lumirss.config import RssHubSettings
from lumirss.feed_preview import FeedPreview
from lumirss.rsshub import (
    CATALOG,
    RssHubFetchError,
    RssHubInvalidParameters,
    RssHubNotConfigured,
    RssHubRouteNotFound,
    RssHubService,
    _quote_segment,
    build_path,
)
from lumirss.main import app

RSS_DOC = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>RSSHub Feed</title><link>https://example.com/</link>
  <description>desc</description>
</channel></rss>"""

BASE_URL = "http://rsshub.test:1200"
FRESHRSS_BASE_URL = "http://rsshub:1200"


class FakeSettings:
    """Stand-in for RssHubSettings with controlled values."""

    def __init__(self, base: str = BASE_URL, freshrss: str = ""):
        self.RSSHUB_BASE_URL = base
        self.RSSHUB_FRESHRSS_BASE_URL = freshrss

    @property
    def freshrss_base_url(self) -> str:
        return self.RSSHUB_FRESHRSS_BASE_URL or self.RSSHUB_BASE_URL


class FakeControl:
    def __init__(self, existing_urls=()) -> None:
        self.existing_urls = list(existing_urls)
        self.calls: list[tuple] = []

    async def list_subscriptions(self):
        self.calls.append(("list_subscriptions",))
        from lumirss.adapters.freshrss_control import Subscription

        return [
            Subscription(stream_id=f"feed/{i + 1}", title=url, feed_url=url)
            for i, url in enumerate(self.existing_urls)
        ]

    async def subscribe(self, *args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("preview must never subscribe")

    async def unsubscribe(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("preview must never unsubscribe")


async def preview_with(
    handler,
    *,
    route_id: str = "github-starred-repos",
    params: dict[str, str] | None = None,
    existing=(),
    base: str = BASE_URL,
    freshrss: str = "",
):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    control = FakeControl(existing)
    service = RssHubService(client, control)
    service.load_settings = lambda: FakeSettings(base, freshrss)
    try:
        result = await service.preview(
            route_id, params if params is not None else {"user": "DIYgod"}
        )
        return result, control
    finally:
        await client.aclose()


# --- catalog contract ------------------------------------------------------


def test_catalog_ids_unique_and_descriptors_complete():
    ids = [route.id for route in CATALOG]
    assert len(ids) == len(set(ids))
    for route in CATALOG:
        assert route.id
        assert route.title
        assert route.description
        assert route.path_template.startswith("/")
        assert "//" not in route.path_template
        for parameter in route.parameters:
            assert parameter.key
            assert parameter.label
            assert parameter.required is True
            assert parameter.pattern
            assert parameter.example
            assert parameter.help
        # template placeholders == declared parameters
        import re

        placeholders = set(re.findall(r"\{(\w+)\}", route.path_template))
        assert placeholders == {p.key for p in route.parameters}


def test_catalog_routes_have_verified_metadata():
    by_id = {route.id: route for route in CATALOG}
    assert by_id["v2ex-topics"].path_template == "/v2ex/topics/{type}"
    assert by_id["hackernews"].parameters == ()
    assert by_id["github-starred-repos"].parameters[0].example == "DIYgod"


# --- path construction -----------------------------------------------------


def test_build_path_valid():
    route = next(r for r in CATALOG if r.id == "github-starred-repos")
    assert build_path(route, {"user": "DIYgod"}) == "/github/starred_repos/DIYgod"


def test_build_path_missing_parameter():
    route = next(r for r in CATALOG if r.id == "github-starred-repos")
    with pytest.raises(RssHubInvalidParameters):
        build_path(route, {})
    with pytest.raises(RssHubInvalidParameters):
        build_path(route, {"user": "   "})


def test_build_path_unknown_parameter():
    route = next(r for r in CATALOG if r.id == "github-starred-repos")
    with pytest.raises(RssHubInvalidParameters):
        build_path(route, {"user": "a", "extra": "b"})


def test_build_path_pattern_rejects_injection():
    route = next(r for r in CATALOG if r.id == "github-starred-repos")
    for evil in ["..", "../etc", "a/b", "a%2Fb", "a?x=1", "a#frag", "a b", "a@evil"]:
        with pytest.raises(RssHubInvalidParameters):
            build_path(route, {"user": evil})


def test_build_path_encodes_allowed_special_chars():
    # v2ex type is constrained to hot|latest; exercise encoding via the
    # primitive + a synthetic route with a permissive pattern.
    assert _quote_segment("a/b c?d") == "a%2Fb%20c%3Fd"
    from lumirss.rsshub import RssHubParameter, RssHubRoute

    synthetic = RssHubRoute(
        id="synth",
        title="t",
        description="d",
        path_template="/synth/{token}",
        parameters=(
            RssHubParameter(
                key="token", label="t", required=True,
                pattern=r"^[\w.-]{1,16}$", example="a", help="h",
            ),
        ),
    )
    assert build_path(synthetic, {"token": "a.b_c-1"}) == "/synth/a.b_c-1"


def test_build_path_empty_template_produces_valid_path():
    route = next(r for r in CATALOG if r.id == "hackernews")
    assert build_path(route, {}) == "/hackernews"


# --- settings --------------------------------------------------------------


def test_rsshub_settings_valid_and_defaults():
    settings = RssHubSettings(
        RSSHUB_BASE_URL="http://127.0.0.1:1200", RSSHUB_FRESHRSS_BASE_URL=""
    )
    assert settings.freshrss_base_url == "http://127.0.0.1:1200"
    settings2 = RssHubSettings(
        RSSHUB_BASE_URL="http://127.0.0.1:1200",
        RSSHUB_FRESHRSS_BASE_URL="http://rsshub:1200",
    )
    assert settings2.freshrss_base_url == "http://rsshub:1200"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://x",
        "https://user:pass@x/",
        "https://x/path",
        "https://x?q=1",
        "https://x/#frag",
        "not a url",
    ],
)
def test_rsshub_settings_rejects_malformed_base(url):
    with pytest.raises(ValidationError):
        RssHubSettings(RSSHUB_BASE_URL=url)


# --- preview ---------------------------------------------------------------


@pytest.mark.anyio
async def test_preview_returns_feed_preview_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "rsshub.test"
        assert request.url.path == "/github/starred_repos/DIYgod"
        return httpx.Response(200, content=RSS_DOC)

    result, control = await preview_with(handler, freshrss=FRESHRSS_BASE_URL)
    assert isinstance(result, FeedPreview)
    assert result.title == "RSSHub Feed"
    assert result.format == "rss"
    assert result.already_subscribed is False
    # feedUrl is the FreshRSS-facing base, NOT the BFF fetch base
    assert result.feed_url == "http://rsshub:1200/github/starred_repos/DIYgod"
    assert control.calls == [("list_subscriptions",)]


@pytest.mark.anyio
async def test_preview_freshrss_base_defaults_to_base():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS_DOC)

    result, _ = await preview_with(handler, freshrss="")
    assert result.feed_url == f"{BASE_URL}/github/starred_repos/DIYgod"


@pytest.mark.anyio
async def test_preview_already_subscribed():
    subscription_url = (
        f"{FRESHRSS_BASE_URL}/github/starred_repos/DIYgod"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS_DOC)

    result, _ = await preview_with(
        handler, existing=[subscription_url], freshrss=FRESHRSS_BASE_URL
    )
    assert result.already_subscribed is True


@pytest.mark.anyio
async def test_preview_not_configured():
    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=RSS_DOC)))
        service = RssHubService(client, FakeControl())
        service.load_settings = lambda: (_ for _ in ()).throw(
            RssHubNotConfigured("not configured")
        )
        try:
            await service.preview("hackernews", {})
        finally:
            await client.aclose()

    with pytest.raises(RssHubNotConfigured):
        await run()


@pytest.mark.anyio
async def test_preview_unknown_route():
    with pytest.raises(RssHubRouteNotFound):
        await preview_with(lambda r: httpx.Response(200, content=RSS_DOC), route_id="nope")


@pytest.mark.anyio
async def test_preview_missing_parameter():
    with pytest.raises(RssHubInvalidParameters):
        await preview_with(lambda r: httpx.Response(200, content=RSS_DOC), params={})


@pytest.mark.anyio
async def test_preview_invalid_parameter():
    with pytest.raises(RssHubInvalidParameters):
        await preview_with(
            lambda r: httpx.Response(200, content=RSS_DOC), params={"user": "a/b"}
        )


@pytest.mark.anyio
async def test_preview_redirect_within_origin_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/github/starred_repos/DIYgod":
            return httpx.Response(302, headers={"location": "/final/feed"})
        return httpx.Response(200, content=RSS_DOC)

    result, _ = await preview_with(handler)
    assert result.title == "RSSHub Feed"


@pytest.mark.anyio
async def test_preview_redirect_outside_origin_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://evil.example/feed"})

    with pytest.raises(RssHubFetchError):
        await preview_with(handler)


@pytest.mark.anyio
async def test_preview_upstream_status_error():
    with pytest.raises(RssHubFetchError):
        await preview_with(lambda r: httpx.Response(503, content=b"boom"))


@pytest.mark.anyio
async def test_preview_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(RssHubFetchError):
        await preview_with(handler)


@pytest.mark.anyio
async def test_preview_invalid_generated_feed():
    from lumirss.feed_preview import NotAFeedError

    with pytest.raises(NotAFeedError):
        await preview_with(lambda r: httpx.Response(200, content=b"<html>nope</html>"))


@pytest.mark.anyio
async def test_preview_oversized_feed():
    from lumirss.feed_preview import FeedTooLarge

    with pytest.raises(FeedTooLarge):
        await preview_with(
            lambda r: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
        )


# --- route level ------------------------------------------------------------


async def route_request(path: str, *, json=None, base: str = BASE_URL):
    from lumirss.source_discovery import SourceDiscoveryService

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=RSS_DOC))
    )
    control = FakeControl()
    service = RssHubService(client, control)
    service.load_settings = lambda: FakeSettings(base)
    app.state.http_client = client
    app.state.rsshub_service = service
    app.state.source_discovery_service = SourceDiscoveryService(client)
    try:
        from httpx import ASGITransport

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as route_client:
            if json is None:
                return await route_client.get(path)
            return await route_client.post(path, json=json)
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_route_routes_catalog():
    response = await route_request("/api/v1/rsshub/routes")
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is True
    assert len(payload["routes"]) == len(CATALOG)
    first = payload["routes"][0]
    assert set(first) == {
        "id", "title", "description", "pathTemplate", "parameters",
    }
    assert set(first["parameters"][0] if first["parameters"] else {}) <= {
        "key", "label", "required", "pattern", "example", "help",
    }


@pytest.mark.anyio
async def test_route_routes_catalog_reports_not_configured():
    async def run():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=RSS_DOC))
        )
        service = RssHubService(client, FakeControl())
        service.load_settings = lambda: (_ for _ in ()).throw(
            RssHubNotConfigured("x")
        )
        app.state.http_client = client
        app.state.rsshub_service = service
        try:
            from httpx import ASGITransport

            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as route_client:
                return await route_client.get("/api/v1/rsshub/routes")
        finally:
            await client.aclose()

    response = await run()
    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert len(response.json()["routes"]) == len(CATALOG)


@pytest.mark.anyio
async def test_route_preview_success():
    response = await route_request(
        "/api/v1/rsshub/preview",
        json={"routeId": "github-starred-repos", "params": {"user": "DIYgod"}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["feedUrl"] == f"{BASE_URL}/github/starred_repos/DIYgod"
    assert payload["title"] == "RSSHub Feed"
    assert payload["alreadySubscribed"] is False


@pytest.mark.anyio
async def test_route_preview_unknown_route_404():
    response = await route_request(
        "/api/v1/rsshub/preview", json={"routeId": "nope", "params": {}}
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "rsshub_route_not_found"


@pytest.mark.anyio
async def test_route_preview_invalid_params_400():
    response = await route_request(
        "/api/v1/rsshub/preview",
        json={"routeId": "github-starred-repos", "params": {"user": "../etc"}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "rsshub_invalid_parameters"


@pytest.mark.anyio
async def test_route_preview_upstream_error_502():
    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, content=b"boom")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        service = RssHubService(client, FakeControl())
        service.load_settings = lambda: FakeSettings()
        app.state.http_client = client
        app.state.rsshub_service = service
        try:
            from httpx import ASGITransport

            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as route_client:
                return await route_client.post(
                    "/api/v1/rsshub/preview",
                    json={"routeId": "hackernews", "params": {}},
                )
        finally:
            await client.aclose()

    response = await run()
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "rsshub_fetch_error"
