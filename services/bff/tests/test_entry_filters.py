"""Tests B / C / D — view / feed / combined filters are translated upstream.

MockTransport asserts what actually reaches FreshRSS: filtering must be
expressed in the upstream request (it param, feed stream path), never done
by post-filtering in Python. Every fake value is clearly test data.
"""

import httpx
import pytest

from lumirss.adapters.freshrss import FreshRSSAdapter
from lumirss.config import FreshRSSSettings

FAKE_TOKEN = "fake-test-token-0004"
BASE_URL = "http://freshrss-test.local"
FEED_URL = "https://example.com/releases.xml"

PAGE_FIXTURE = {
    "id": "user/-/state/com.google/reading-list",
    "updated": 1787270034,
    "items": [
        {
            "id": "tag:google.com,2005:reader/item/000659e07aaee24d",
            "title": "科技爱好者周刊（第 409 期）",
            "author": "阮一峰",
            "published": 1787270034,
            "summary": {"content": "<p>body</p>"},
            "alternate": [{"href": "http://example.com/weekly-409"}],
            "origin": {"streamId": "feed/2", "htmlUrl": "http://example.com/", "title": "阮一峰的网络日志"},
            "categories": ["user/-/state/com.google/reading-list", "user/-/state/com.google/read"],
        },
    ],
}


def make_settings() -> FreshRSSSettings:
    return FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD="fake-test-password",
    )


def make_adapter(handler) -> tuple[FreshRSSAdapter, list[httpx.Request]]:
    requested: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return handler(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(recording_handler),
        trust_env=False,
    )
    return FreshRSSAdapter(client, make_settings()), requested


def page_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/accounts/ClientLogin"):
        return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
    return httpx.Response(200, json=PAGE_FIXTURE)


# --- Test B — view mapping -------------------------------------------------


@pytest.mark.anyio
async def test_view_all_sends_no_state_filter():
    adapter, requested = make_adapter(page_handler)

    await adapter.list_entries(view="all")

    stream = requested[-1]
    assert stream.url.path.endswith("/stream/contents/reading-list")
    assert "it" not in stream.url.params  # all = no upstream state filter


@pytest.mark.anyio
async def test_view_unread_maps_to_upstream_it_filter():
    adapter, requested = make_adapter(page_handler)

    await adapter.list_entries(view="unread")

    stream = requested[-1]
    assert stream.url.path.endswith("/stream/contents/reading-list")
    assert stream.url.params["it"] == "user/-/state/com.google/unread"


@pytest.mark.anyio
async def test_view_starred_maps_to_upstream_it_filter():
    adapter, requested = make_adapter(page_handler)

    await adapter.list_entries(view="starred")

    stream = requested[-1]
    assert stream.url.path.endswith("/stream/contents/reading-list")
    assert stream.url.params["it"] == "user/-/state/com.google/starred"


@pytest.mark.anyio
async def test_view_default_is_all():
    adapter, requested = make_adapter(page_handler)

    await adapter.list_entries()

    stream = requested[-1]
    assert "it" not in stream.url.params


def raw_path_of(request: httpx.Request) -> str:
    """The path exactly as sent on the wire (percent-encoding intact)."""
    return request.url.raw_path.decode("ascii").split("?", 1)[0]


# --- Test C — feed filter --------------------------------------------------


@pytest.mark.anyio
async def test_feed_url_is_encoded_into_feed_stream_path():
    adapter, requested = make_adapter(page_handler)

    await adapter.list_entries(feed_url=FEED_URL)

    stream = requested[-1]
    # ':' and '/' of the feed URL must be percent-encoded on the wire.
    assert raw_path_of(stream).endswith(
        "/stream/contents/feed/https%3A%2F%2Fexample.com%2Freleases.xml"
    )
    assert "it" not in stream.url.params


@pytest.mark.anyio
async def test_feed_filter_does_not_post_filter_items():
    """The feed page is whatever FreshRSS returned — nothing is dropped here."""
    adapter, _ = make_adapter(page_handler)

    page = await adapter.list_entries(feed_url=FEED_URL)

    assert len(page.items) == 1  # fixture has one item, one item comes back


# --- Test D — combined filter ----------------------------------------------


@pytest.mark.anyio
async def test_feed_and_view_filters_go_into_the_same_request():
    adapter, requested = make_adapter(page_handler)

    await adapter.list_entries(view="unread", feed_url=FEED_URL)

    stream = requested[-1]
    assert raw_path_of(stream).endswith(
        "/stream/contents/feed/https%3A%2F%2Fexample.com%2Freleases.xml"
    )
    assert stream.url.params["it"] == "user/-/state/com.google/unread"
    assert stream.url.params["n"] == "20"
    # One stream request only: feed scope + state filter together upstream.
    stream_requests = [r for r in requested if "/stream/contents/" in raw_path_of(r)]
    assert len(stream_requests) == 1


# --- Test A (list part) — state markers --------------------------------------


@pytest.mark.anyio
async def test_state_markers_map_to_read_and_starred():
    adapter, _ = make_adapter(page_handler)

    page = await adapter.list_entries()

    entry = page.items[0]
    assert entry.read is True  # fixture carries the read marker
    assert entry.starred is False  # fixture carries no starred marker
