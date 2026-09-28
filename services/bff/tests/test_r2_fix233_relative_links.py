"""FIX-233 — Atom 相对链接的基址解析（xml:base 语义）。

缺陷：上游条目的 alternate href 是相对链接时（畸形/截断 feed 常见），
适配层原样透传，点击正文链接会落到 LumiRSS 自己的路径上。

承诺：适配后的条目 url 必须以正确的基址（feed 来源信息）解析成绝对
URL；基址不可知时诚实降级为 None（绝不发出指向 LumiRSS 自身的假链接）。

基址优先级（与上游 origin 形状一致）：origin.htmlUrl（站点 URL）→
origin.streamId 的 feed/<url>（feed 自身 URL）；仅接受绝对 http(s)。
"""

import secrets as _secrets

import httpx
import pytest

from lumirss.adapters.freshrss import FreshRSSAdapter
from lumirss.config import FreshRSSSettings

FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)
FAKE_TOKEN = "fake-test-token-fix233"
BASE_URL = "http://freshrss-test.local"


def item_with_href(href, origin) -> dict:
    return {
        "id": "user/-/state/com.google/reading-list",
        "items": [
            {
                "id": "tag:google.com,2005:reader/item/0000000000000042",
                "title": "相对链接条目",
                "published": 1787270034,
                "alternate": [{"href": href}],
                "origin": origin,
                "categories": [],
            }
        ],
    }


def make_adapter(handler) -> FreshRSSAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    settings = FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )
    return FreshRSSAdapter(client, settings)


def full_handler(payload: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if request.url.path.endswith("/subscription/list"):
            return httpx.Response(200, json={"subscriptions": []})
        return httpx.Response(200, json=payload)

    return handler


@pytest.mark.anyio
async def test_fix233_relative_href_resolves_against_origin_html_url():
    payload = item_with_href(
        "/weekly/410",
        {"streamId": "feed/2", "htmlUrl": "http://example.com/blog/", "title": "周报"},
    )
    adapter = make_adapter(full_handler(payload))
    entries = (await adapter.list_entries()).items
    assert entries[0].url == "http://example.com/weekly/410"


@pytest.mark.anyio
async def test_fix233_relative_href_resolves_against_feed_stream_url_without_htmlurl():
    payload = item_with_href(
        "post.html",
        {"streamId": "feed/https://feeds.example.com/blog/", "title": "博客"},
    )
    adapter = make_adapter(full_handler(payload))
    entries = (await adapter.list_entries()).items
    assert entries[0].url == "https://feeds.example.com/blog/post.html"


@pytest.mark.anyio
async def test_fix233_unresolvable_relative_href_degrades_to_none_not_lumi_path():
    """基址不可知：url=None（诚实降级），绝不原样透传相对路径。"""
    payload = item_with_href("/weekly/410", {"streamId": "feed/3", "title": "周报"})
    adapter = make_adapter(full_handler(payload))
    entries = (await adapter.list_entries()).items
    assert entries[0].url is None


@pytest.mark.anyio
async def test_fix233_absolute_and_non_http_hrefs_stay_untouched():
    payload = {
        "id": "user/-/state/com.google/reading-list",
        "items": [
            {
                "id": "tag:google.com,2005:reader/item/0000000000000043",
                "title": "绝对链接",
                "published": 1787270034,
                "alternate": [{"href": "https://example.com/a"}],
                "origin": {"streamId": "feed/2", "htmlUrl": "http://example.com/"},
                "categories": [],
            },
            {
                "id": "tag:google.com,2005:reader/item/0000000000000044",
                "title": "mailto",
                "published": 1787270034,
                "alternate": [{"href": "mailto:hi@example.com"}],
                "origin": {"streamId": "feed/2", "htmlUrl": "http://example.com/"},
                "categories": [],
            },
        ],
    }
    adapter = make_adapter(full_handler(payload))
    entries = (await adapter.list_entries()).items
    assert entries[0].url == "https://example.com/a"
    assert entries[1].url == "mailto:hi@example.com"
