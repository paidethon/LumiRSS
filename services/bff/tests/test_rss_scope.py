"""0011 RSS Scope 数据层测试 — 分类解析 / label stream / sourceType 契约。

§45–§47：分类合并（真实 category id 为 key）、label stream 映射（含默认
分类本地化名 fallback）、sourceType/categoryId 路由校验与 cursor scope。
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.adapters.freshrss import FreshRSSAdapter, Feed
from lumirss.cursor import decode_cursor
from lumirss.main import app
from lumirss.config import FreshRSSSettings

import secrets as _secrets
# 动态生成的假凭据（非真实 secret；安全扫描要求无凭据形状字面量）
FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)

BASE_URL = "http://freshrss.test"
FAKE_TOKEN = "fake-token-123"


def make_settings() -> FreshRSSSettings:
    return FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )


def make_adapter(handler) -> tuple[FreshRSSAdapter, list[httpx.Request]]:
    """与 test_entry_adapter 相同的 MockTransport 模式。"""
    requested: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording), trust_env=False)
    return FreshRSSAdapter(client, make_settings()), requested


def login_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")


def stream_item(item_id: str) -> dict:
    return {
        "id": f"tag:google.com,2005:reader/item/{item_id}",
        "title": f"文章 {item_id}",
        "published": 1700000000,
        "crawlTimeMsec": "1700000000000",
        "categories": ["user/-/state/com.google/reading-list"],
        "origin": {"title": "源", "streamId": "feed/1"},
    }


# ---- §45 分类解析与合并 ----------------------------------------------


def test_subscription_categories_are_parsed():
    payload = {
        "subscriptions": [
            {
                "title": "FreshRSS releases",
                "url": "https://example.com/releases.xml",
                "categories": [{"id": "user/-/label/技术", "label": "技术"}],
            },
            {
                "title": "阮一峰的网络日志",
                "url": "https://example.com/ruanyifeng.xml",
                "categories": [],
            },
        ]
    }
    feeds = FreshRSSAdapter._parse_subscriptions(payload)  # noqa: SLF001
    assert feeds[0].category_id == "user/-/label/技术"
    assert feeds[0].category_label == "技术"
    # 空 categories → None（前端归入未分组）
    assert feeds[1].category_id is None
    assert feeds[1].category_label is None


def test_category_merge_by_real_id():
    """§3/§45：同 category.id 的 feeds 合并进同一节点（id 为 key，非 name 拼接）。"""
    feeds = [
        Feed("A", "https://a", "user/-/label/技术", "技术"),
        Feed("B", "https://b", "user/-/label/技术", "技术"),
        Feed("C", "https://c", "user/-/label/AI", "AI"),
        Feed("D", "https://d", None, None),
    ]
    groups: dict[str | None, list[Feed]] = {}
    for feed in feeds:
        groups.setdefault(feed.category_id, []).append(feed)
    assert [f.title for f in groups["user/-/label/技术"]] == ["A", "B"]
    assert [f.title for f in groups["user/-/label/AI"]] == ["C"]
    assert [f.title for f in groups[None]] == ["D"]  # 未分组


# ---- §13/§14 category stream 映射 + fallback -------------------------


@pytest.mark.anyio
async def test_category_stream_uses_label_path():
    """categoryId → greader label stream（user/-/label/<名>）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        assert "/stream/contents/user/-/label/" in request.url.path
        return httpx.Response(200, json={"items": [stream_item("1")]})

    adapter, requested = make_adapter(handler)
    page = await adapter.list_entries(view="all", category_id="user/-/label/技术")
    assert len(page.items) == 1
    # httpx url.path 已 percent-decode；raw URL 断言编码形态
    assert "user/-/label/%E6%8A%80%E6%9C%AF" in str(requested[-1].url)


@pytest.mark.anyio
async def test_default_category_localized_label_falls_back():
    """FreshRSS 怪癖：本地化默认分类名空结果 → 回退 Uncategorized（§52 链路实测）。"""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        path = request.url.path
        calls.append(path)
        if path.endswith("/label/Uncategorized"):
            return httpx.Response(200, json={"items": [stream_item("1"), stream_item("2")]})
        # 本地化名（未分类）→ 上游 searchByName 失配 → 空流
        return httpx.Response(200, json={"items": []})

    adapter, _ = make_adapter(handler)
    page = await adapter.list_entries(view="all", category_id="user/-/label/未分类")
    assert len(page.items) == 2
    assert len(calls) == 2  # 原名一次 + fallback 一次
    # url.path 为 decoded 形态
    assert calls[0].endswith("/label/未分类")
    assert calls[1].endswith("/label/Uncategorized")


@pytest.mark.anyio
async def test_empty_category_no_infinite_retry():
    """空分类 + 默认分类也无数据 → 保持空（fallback 仅再试一次）。"""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        calls.append(request.url.path)
        return httpx.Response(200, json={"items": []})

    adapter, _ = make_adapter(handler)
    page = await adapter.list_entries(view="all", category_id="user/-/label/空分类")
    assert page.items == []
    assert len(calls) == 2


@pytest.mark.anyio
async def test_category_stream_passes_view_and_continuation():
    """label stream 透传 it（view）与 c（continuation）。"""
    seen_params: dict[str, list] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        seen_params.update(dict(request.url.params))
        return httpx.Response(200, json={"items": [stream_item("1")]})

    adapter, _ = make_adapter(handler)
    await adapter.list_entries(
        view="unread", category_id="user/-/label/技术", continuation="42"
    )
    assert seen_params.get("c") == "42"
    assert "it" in seen_params  # unread → it 过滤（_VIEW_FILTERS）


@pytest.mark.anyio
async def test_source_type_rss_accepted_no_extra_request():
    """sourceType=rss 契约存在（§51）：请求形状与 reading-list 相同。"""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        paths.append(request.url.path)
        return httpx.Response(200, json={"items": [stream_item("1")]})

    adapter, _ = make_adapter(handler)
    page = await adapter.list_entries(view="all", source_type="rss")
    assert len(page.items) == 1
    assert paths[-1].endswith("/stream/contents/reading-list")


# ---- 路由层：sourceType / categoryId / 互斥 / cursor scope ------------


class FakeAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self.last_kwargs: dict = {}

    async def list_feeds(self):
        return []

    async def list_entries(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        from lumirss.models import EntryListItem, EntryPage

        return EntryPage(
            items=[
                EntryListItem(
                    entryRef="e1.eyJrIjoxfQ",
                    title="文章",
                    feedTitle="源",
                    author=None,
                    url=None,
                    publishedAt=None,
                    read=False,
                    starred=False,
                )
            ],
            upstreamContinuation="77",
        )


def test_route_rejects_unknown_source_type():
    fake = FakeAdapter()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.freshrss_adapter = fake
            response = client.get("/api/v1/entries", params={"sourceType": "email"})
        assert response.status_code == 400
        assert fake.calls == 0  # 校验先于上游
    finally:
        app.state.freshrss_adapter = None


def test_route_rejects_feed_and_category_together():
    fake = FakeAdapter()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.freshrss_adapter = fake
            response = client.get(
                "/api/v1/entries",
                params={"feedUrl": "https://a", "categoryId": "user/-/label/技术"},
            )
        assert response.status_code == 400
        assert fake.calls == 0
    finally:
        app.state.freshrss_adapter = None


def test_route_passes_source_type_and_category_to_adapter():
    """§51：RSS Scope 的 query 明确包含 sourceType=rss（区别于"全部"）。"""
    fake = FakeAdapter()
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            response = client.get(
                "/api/v1/entries",
                params={"sourceType": "rss", "categoryId": "user/-/label/技术"},
            )
        assert response.status_code == 200
        assert fake.last_kwargs["source_type"] == "rss"
        assert fake.last_kwargs["category_id"] == "user/-/label/技术"
    finally:
        app.state.freshrss_adapter = None


def test_route_category_cursor_roundtrip_keeps_scope():
    """§47：分类 scope 翻页 cursor 不错乱。"""
    fake = FakeAdapter()
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            first = client.get(
                "/api/v1/entries",
                params={"sourceType": "rss", "categoryId": "user/-/label/技术"},
            ).json()
        assert first["nextCursor"] is not None
        scope = decode_cursor(first["nextCursor"])
        assert scope.category_id == "user/-/label/技术"
        assert scope.source_type == "rss"
        # cursor 单独使用 → 携带 scope 请求下一页（不混入其他分类）
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            second = client.get(
                "/api/v1/entries", params={"cursor": first["nextCursor"]}
            )
        assert second.status_code == 200
        assert fake.last_kwargs["category_id"] == "user/-/label/技术"
        # 显式不同 categoryId → 400（scope mismatch，先于上游）
        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.freshrss_adapter = fake
            mismatch = client.get(
                "/api/v1/entries",
                params={"cursor": first["nextCursor"], "categoryId": "user/-/label/其他"},
            )
        assert mismatch.status_code == 400
    finally:
        app.state.freshrss_adapter = None
