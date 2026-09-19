"""Tests A / B / F (list part) — FreshRSSAdapter entry reading vs mocked FreshRSS.

Also asserts the read-only property: list/detail only ever hit reading
endpoints (never edit-tag / token / subscription/edit). Every fake value is
clearly test data; no real credentials are used.
"""

import secrets as _secrets

import httpx
import pytest

from lumirss.adapters.freshrss import (
    EntryNotFound,
    FreshRSSAdapter,
    UpstreamConnectionError,
    UpstreamError,
)
from lumirss.config import FreshRSSSettings

# 动态生成的假凭据（非真实 secret；安全扫描要求无凭据形状字面量）
FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)

FAKE_TOKEN = "fake-test-token-0003"

BASE_URL = "http://freshrss-test.local"

WRITE_ENDPOINTS = ("/edit-tag", "/token", "/subscription/edit")

# Field shape frozen by the 0003 live probe against real FreshRSS 1.29.1.
READING_LIST_FIXTURE = {
    "id": "user/-/state/com.google/reading-list",
    "updated": 1787270034,
    "items": [
        {
            "id": "tag:google.com,2005:reader/item/000659e07aaee24d",
            "title": "科技爱好者周刊（第 409 期）",
            "author": "阮一峰",
            "published": 1787270034,
            "summary": {"content": "<p>SECRET_BODY_ONE full article body</p>"},
            "alternate": [{"href": "http://example.com/weekly-409"}],
            "origin": {"streamId": "feed/2", "htmlUrl": "http://example.com/", "title": "阮一峰的网络日志"},
            "categories": ["user/-/state/com.google/reading-list", "Weekly"],
        },
        {
            "id": "tag:google.com,2005:reader/item/000659e07aaee24e",
            "title": "FreshRSS 1.29.1 released",
            "author": "FreshRSS",
            "published": 1787183634,
            "summary": {"content": "<p>SECRET_BODY_TWO release notes body</p>"},
            "alternate": [{"href": "http://example.com/release"}],
            "origin": {"streamId": "feed/1", "htmlUrl": "http://example.com/", "title": "FreshRSS releases"},
            "categories": ["user/-/state/com.google/reading-list"],
        },
    ],
}

# Minimal item: everything optional is missing (Test F shape).
MISSING_FIELDS_ITEM = {
    "id": "tag:google.com,2005:reader/item/000659e07aaee24f",
    "title": "只有标题的文章",
    "origin": {"streamId": "feed/2"},
}

# Detail fixture: body HTML must become safe plain text (Test D).
# Carries the read marker (no starred marker) so state mapping is exercised.
DETAIL_ITEM = {
    "id": "tag:google.com,2005:reader/item/000659e07aaee24d",
    "title": "科技爱好者周刊（第 409 期）",
    "author": "阮一峰",
    "published": 1787270034,
    "crawlTimestampMsec": "1787270100000",
    "summary": {
        "content": (
            "<p>这里记录每周值得分享的科技内容，&amp; 周五发布。</p>"
            "<script>alert(1)</script>"
            "<p>第二段正文。</p>"
        )
    },
    "alternate": [{"href": "http://example.com/weekly-409"}],
    "origin": {"streamId": "feed/2", "htmlUrl": "http://example.com/", "title": "阮一峰的网络日志"},
    "categories": ["user/-/state/com.google/reading-list", "user/-/state/com.google/read"],
}


def item_contents_response(items: list[dict]) -> dict:
    return {"id": "items", "updated": 1787270034, "items": items}


# 2026-09 移动端专项 P2：订阅清单（标题→URL 映射，feedUrl enrich 用）。
SUBSCRIPTION_LIST_FIXTURE = {
    "subscriptions": [
        {
            "id": "feed/2",
            "title": "阮一峰的网络日志",
            "url": "https://www.ruanyifeng.com/blog/atom.xml",
            "categories": [{"id": "user/-/label/tech", "label": "tech"}],
        },
        {
            "id": "feed/1",
            "title": "FreshRSS releases",
            "url": "https://freshrss.org/feed",
            "categories": [{"id": "user/-/label/tech", "label": "tech"}],
        },
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


def make_adapter(handler) -> tuple[FreshRSSAdapter, list[httpx.Request]]:
    """Adapter on MockTransport; requested paths are recorded for assertions."""
    requested_paths: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request)
        return handler(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(recording_handler),
        trust_env=False,
    )
    return FreshRSSAdapter(client, make_settings()), requested_paths


def login_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")


# --- Test A — list mapping ---------------------------------------------


@pytest.mark.anyio
async def test_list_entries_maps_fields_correctly():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        return httpx.Response(200, json=READING_LIST_FIXTURE)

    adapter, requested = make_adapter(handler)

    page = await adapter.list_entries()
    entries = page.items

    assert len(entries) == 2
    first = entries[0]
    assert first.title == "科技爱好者周刊（第 409 期）"
    assert first.feedTitle == "阮一峰的网络日志"
    assert first.author == "阮一峰"
    assert first.url == "http://example.com/weekly-409"
    assert first.publishedAt == "2026-08-20T23:53:54Z"  # 1787270034 as RFC3339 UTC
    assert first.read is False  # fixture carries no read/starred markers
    assert first.starred is False
    assert page.upstreamContinuation is None  # fixture has no continuation
    assert first.entryRef.startswith("e1.")
    # Round-trip through the adapter's own ref.
    from lumirss.entryref import decode_entry_ref

    assert decode_entry_ref(first.entryRef) == "tag:google.com,2005:reader/item/000659e07aaee24d"


@pytest.mark.anyio
async def test_list_entries_requests_bounded_n_and_read_only_endpoints():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        if request.url.path.endswith("/subscription/list"):
            return httpx.Response(200, json=SUBSCRIPTION_LIST_FIXTURE)
        assert request.url.params["n"] == "20"
        return httpx.Response(200, json=READING_LIST_FIXTURE)

    adapter, requested = make_adapter(handler)

    await adapter.list_entries()

    paths = [r.url.path for r in requested]
    # 2026-09 P2：enrich 在 stream 前取一次订阅清单（只读，TTL 缓存）。
    assert paths == [
        "/api/greader.php/accounts/ClientLogin",
        "/api/greader.php/reader/api/0/subscription/list",
        "/api/greader.php/reader/api/0/stream/contents/reading-list",
    ]
    assert all(fragment not in path for path in paths for fragment in WRITE_ENDPOINTS)


# --- Test B — list never exposes the body (2026-09 迁移：bounded 摘要除外) ---

LONG_BODY_FIXTURE = {
    "id": "user/-/state/com.google/reading-list",
    "updated": 1787270034,
    "items": [
        {
            "id": "tag:google.com,2005:reader/item/000659e07aaee24d",
            "title": "长文标题",
            "published": 1787270034,
            "summary": {
                "content": (
                    "<p>SECRET_BODY_ONE"
                    + "很长的正文" * 80
                    + "</p><img src=\"https://example.com/cover.jpg\">"
                    "<img src=\"data:image/png;base64,AAAA\">"
                )
            },
            "origin": {"streamId": "feed/2", "title": "阮一峰的网络日志"},
            "categories": [],
        }
    ],
}


@pytest.mark.anyio
async def test_list_entries_never_returns_body():
    """正文契约（2026-09 有意迁移）：列表 DTO 不含 contentHtml/contentText；
    snippet 是 ≤160 字符 + 省略号的纯文本摘要，长正文必须被截断；
    封面只提取首个 http(s) img src（data: 协议被拒绝）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        if request.url.path.endswith("/subscription/list"):
            return httpx.Response(200, json=SUBSCRIPTION_LIST_FIXTURE)
        return httpx.Response(200, json=LONG_BODY_FIXTURE)

    adapter, _ = make_adapter(handler)

    entries = (await adapter.list_entries()).items

    assert "contentHtml" not in entries[0].model_dump()
    assert "contentText" not in entries[0].model_dump()
    snippet = entries[0].snippet
    assert snippet is not None
    assert snippet.startswith("SECRET_BODY_ONE")
    assert len(snippet) <= 161  # 160 字符 + 省略号
    assert snippet.endswith("…")
    assert "很长的正文" * 80 not in snippet  # 完整正文绝不出现在列表摘要里
    # 封面提取：http(s) 才收；data: 被跳过。
    assert entries[0].coverUrl == "https://example.com/cover.jpg"


@pytest.mark.anyio
async def test_list_entries_enrich_feed_url_by_title_and_fail_open():
    """P2 feedUrl enrich：标题→URL 映射命中；未命中为 None；订阅清单
    失败时 fail-open（列表照常返回，feedUrl=None）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        if request.url.path.endswith("/subscription/list"):
            return httpx.Response(200, json=SUBSCRIPTION_LIST_FIXTURE)
        return httpx.Response(200, json=READING_LIST_FIXTURE)

    adapter, _ = make_adapter(handler)
    entries = (await adapter.list_entries()).items
    by_title = {e.feedTitle: e for e in entries}
    assert by_title["阮一峰的网络日志"].feedUrl == (
        "https://www.ruanyifeng.com/blog/atom.xml"
    )
    assert by_title["FreshRSS releases"].feedUrl == "https://freshrss.org/feed"

    def failing_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        if request.url.path.endswith("/subscription/list"):
            return httpx.Response(503)
        return httpx.Response(200, json=READING_LIST_FIXTURE)

    adapter2, _ = make_adapter(failing_handler)
    entries2 = (await adapter2.list_entries()).items
    assert all(e.feedUrl is None for e in entries2)
    assert len(entries2) == 2  # enrich 失败绝不阻塞列表


@pytest.mark.anyio
async def test_snippet_and_cover_helpers_pure():
    from lumirss.adapters.freshrss import cover_url_of, list_snippet_of

    assert list_snippet_of(None) is None
    assert list_snippet_of("") is None
    assert list_snippet_of("<p>短文</p>") == "短文"
    assert list_snippet_of("<p>" + "字" * 300 + "</p>") == "字" * 160 + "…"
    assert cover_url_of(None) is None
    assert cover_url_of('<IMG SRC="https://a.example/x.png">') == "https://a.example/x.png"
    assert cover_url_of('<img src="javascript:alert(1)">') is None
    assert cover_url_of('<img src="/relative.png">') is None
    assert (
        cover_url_of('<img src="data:image/png;base64,AA"><img src="https://ok/2.png">')
        == "https://ok/2.png"
    )


# --- Test F (list part) — missing optional fields ------------------------


@pytest.mark.anyio
async def test_list_entries_tolerates_missing_optional_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        return httpx.Response(200, json={"items": [MISSING_FIELDS_ITEM]})

    adapter, _ = make_adapter(handler)

    entries = (await adapter.list_entries()).items

    assert len(entries) == 1
    entry = entries[0]
    assert entry.title == "只有标题的文章"
    assert entry.feedTitle == ""
    assert entry.author is None
    assert entry.url is None
    assert entry.publishedAt is None
    assert entry.read is False  # missing categories must not 500
    assert entry.starred is False
    assert entry.entryRef.startswith("e1.")


@pytest.mark.anyio
async def test_list_entries_skips_items_without_id():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        return httpx.Response(
            200,
            json={"items": [{"title": "no id"}, READING_LIST_FIXTURE["items"][0]]},
        )

    adapter, _ = make_adapter(handler)

    entries = (await adapter.list_entries()).items

    assert len(entries) == 1
    assert entries[0].title == "科技爱好者周刊（第 409 期）"


# --- Error mapping follows 0002 rules ------------------------------------


@pytest.mark.anyio
async def test_list_entries_connection_error_maps_to_upstream_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    adapter, _ = make_adapter(handler)

    with pytest.raises(UpstreamConnectionError):
        await adapter.list_entries()


@pytest.mark.anyio
async def test_list_entries_relogin_once_on_401():
    reading_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        reading_calls.append(request.headers.get("Authorization"))
        if len(reading_calls) == 1:
            return httpx.Response(401)  # stale token（首个读请求）
        if request.url.path.endswith("/subscription/list"):
            return httpx.Response(200, json=SUBSCRIPTION_LIST_FIXTURE)
        return httpx.Response(200, json=READING_LIST_FIXTURE)

    adapter, _ = make_adapter(handler)

    entries = (await adapter.list_entries()).items

    # 2026-09 P2：subscription/list（401→重登→成功）+ stream/contents。
    assert len(reading_calls) == 3
    assert entries[0].title == "科技爱好者周刊（第 409 期）"


@pytest.mark.anyio
async def test_list_entries_unexpected_shape_raises_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        return httpx.Response(200, json={"items": "not-a-list"})

    adapter, _ = make_adapter(handler)

    with pytest.raises(UpstreamError):
        await adapter.list_entries()


# --- Test D — detail mapping ---------------------------------------------


@pytest.mark.anyio
async def test_get_entry_maps_fields_and_converts_html_to_text():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        if request.url.path.endswith("/subscription/list"):
            return httpx.Response(200, json=SUBSCRIPTION_LIST_FIXTURE)
        assert request.method == "POST"
        assert request.url.path.endswith("/stream/items/contents")
        return httpx.Response(200, json=item_contents_response([DETAIL_ITEM]))

    adapter, requested = make_adapter(handler)

    detail = await adapter.get_entry("tag:google.com,2005:reader/item/000659e07aaee24d")

    assert detail.title == "科技爱好者周刊（第 409 期）"
    assert detail.feedTitle == "阮一峰的网络日志"
    assert detail.author == "阮一峰"
    assert detail.url == "http://example.com/weekly-409"
    assert detail.publishedAt == "2026-08-20T23:53:54Z"
    assert detail.crawledAt == "2026-08-20T23:55:00Z"  # F30：首次收录 ≠ 发布时间
    assert detail.read is True  # fixture carries the read marker
    assert detail.starred is False  # ... but no starred marker
    assert detail.entryRef.startswith("e1.")
    # P2 enrich：订阅清单标题命中 → 真实 feedUrl（未命中为 None）。
    assert detail.feedUrl == "https://www.ruanyifeng.com/blog/atom.xml"
    # HTML is turned into plain text: no tags, entity decoded, script gone.
    assert "alert(1)" not in detail.contentText
    assert "<p>" not in detail.contentText
    assert "这里记录每周值得分享的科技内容，& 周五发布。" in detail.contentText
    assert "第二段正文。" in detail.contentText
    # 0006 Test A — raw upstream HTML is transported verbatim in contentHtml
    # (untrusted; sanitizing is the web client's job — NOT done here).
    assert (
        detail.contentHtml
        == "<p>这里记录每周值得分享的科技内容，&amp; 周五发布。</p>"
        "<script>alert(1)</script>"
        "<p>第二段正文。</p>"
    )
    # Read-only: only ClientLogin + items/contents were hit.
    paths = [r.url.path for r in requested]
    assert all(fragment not in path for path in paths for fragment in WRITE_ENDPOINTS)


@pytest.mark.anyio
async def test_get_entry_empty_items_raises_entry_not_found():
    """FreshRSS answers a missing item with 200 + empty items, not 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        return httpx.Response(200, json=item_contents_response([]))

    adapter, _ = make_adapter(handler)

    with pytest.raises(EntryNotFound):
        await adapter.get_entry("tag:google.com,2005:reader/item/0000000000000001")


@pytest.mark.anyio
async def test_get_entry_multiple_items_raises_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        return httpx.Response(
            200,
            json=item_contents_response([DETAIL_ITEM, READING_LIST_FIXTURE["items"][1]]),
        )

    adapter, _ = make_adapter(handler)

    with pytest.raises(UpstreamError):
        await adapter.get_entry("tag:google.com,2005:reader/item/000659e07aaee24d")


@pytest.mark.anyio
async def test_get_entry_sends_exactly_one_i():
    seen_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        if request.url.path.endswith("/subscription/list"):
            return httpx.Response(200, json=SUBSCRIPTION_LIST_FIXTURE)
        seen_bodies.append(request.read().decode("utf-8"))
        return httpx.Response(200, json=item_contents_response([DETAIL_ITEM]))

    adapter, _ = make_adapter(handler)

    await adapter.get_entry("tag:google.com,2005:reader/item/000659e07aaee24d")

    assert len(seen_bodies) == 1
    assert seen_bodies[0].count("i=") == 1


# --- Test F (detail part) — missing optional fields -----------------------


@pytest.mark.anyio
async def test_get_entry_tolerates_missing_optional_fields():
    item = dict(MISSING_FIELDS_ITEM)
    item["summary"] = {"content": "<p>只有正文。</p>"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        return httpx.Response(200, json=item_contents_response([item]))

    adapter, _ = make_adapter(handler)

    detail = await adapter.get_entry("tag:google.com,2005:reader/item/000659e07aaee24f")

    assert detail.title == "只有标题的文章"
    assert detail.feedTitle == ""
    assert detail.author is None
    assert detail.url is None
    assert detail.publishedAt is None
    assert detail.read is False  # missing categories must not 500
    assert detail.starred is False
    assert detail.contentText == "只有正文。"
    assert detail.contentHtml == "<p>只有正文。</p>"


@pytest.mark.anyio
async def test_get_entry_without_content_yields_empty_content_text():
    item = {"id": "tag:google.com,2005:reader/item/000659e07aaee250", "title": "无正文"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        return httpx.Response(200, json=item_contents_response([item]))

    adapter, _ = make_adapter(handler)

    detail = await adapter.get_entry("tag:google.com,2005:reader/item/000659e07aaee250")

    assert detail.contentText == ""
    # 0006 Test B — missing upstream body normalizes to None (never "").
    assert detail.contentHtml is None


@pytest.mark.anyio
async def test_get_entry_empty_upstream_html_normalizes_to_none():
    """0006 Test B — empty-string upstream HTML also normalizes to None."""
    item = {
        "id": "tag:google.com,2005:reader/item/000659e07aaee251",
        "title": "空正文",
        "summary": {"content": ""},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        return httpx.Response(200, json=item_contents_response([item]))

    adapter, _ = make_adapter(handler)

    detail = await adapter.get_entry("tag:google.com,2005:reader/item/000659e07aaee251")

    assert detail.contentText == ""
    assert detail.contentHtml is None


@pytest.mark.anyio
async def test_get_entry_connection_error_maps_to_upstream_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    adapter, _ = make_adapter(handler)

    with pytest.raises(UpstreamConnectionError):
        await adapter.get_entry("tag:google.com,2005:reader/item/000659e07aaee24d")
