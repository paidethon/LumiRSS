"""N035 重定向安全预览 — 多跳链捕获 / query 掩码 / 失败跳透出。

覆盖：
- safe_fetch 成功时 redirect_chain 记录每一跳（含首跳；末跳 final=True）；
- query 里的凭据类参数值掩码（token → '***'），非凭据参数原样保留；
- 边界拒绝（私网重定向 / 回环 / 重定向环超限）时异常携带 redirect_chain
  （失败跳 status=None），feed-preview 端点错误体附 redirectChain +
  failedHop（稳定错误类型不变）；
- F044 迁移向导用的 feed-preview 响应携带 redirectChain（多跳 → 末跳
  final；无重定向 → 单跳链）。

全部 httpx.MockTransport + fake DNS + pinned transport，绝无真实网络。
"""

import socket
import tempfile

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.feed_preview import (
    FeedFetchError,
    FeedPreviewService,
    UnsafeFeedUrl,
    mask_query_url,
)
from lumirss.main import app
from lumirss.ssrf_transport import PinnedAddressTransport

PUBLIC = "93.184.216.34"
RSS_DOC = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Chain Feed</title><link>https://example.com/</link>
</channel></rss>"""


class FakeResolver:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self.mapping = dict(mapping)

    async def __call__(self, host: str, port: int) -> list[str]:
        if host not in self.mapping:
            raise socket.gaierror(8, "Name or service not known")
        return self.mapping[host]


def _service(handler, resolver_map) -> FeedPreviewService:
    resolver = FakeResolver(resolver_map)

    def pin_factory(*, resolver, ensure_public):
        return PinnedAddressTransport(
            resolver=resolver,
            ensure_public=ensure_public,
            delegate=httpx.MockTransport(handler),
        )

    class _NoControl:
        async def list_subscriptions(self):
            return []

    return FeedPreviewService(
        _NoControl(), resolver=resolver, pin_factory=pin_factory
    )


# ---- 掩码单元 ----------------------------------------------------------------


def test_mask_query_url_masks_credential_values_only():
    masked = mask_query_url(
        "https://a.example/f.xml?token=abc123&sort=desc&q=%E5%8D%8A%E8%A7%92"
    )
    assert "token=***" in masked
    assert "sort=desc" in masked
    assert "abc123" not in masked
    # 无 query 原样返回
    assert mask_query_url("https://a.example/f.xml") == "https://a.example/f.xml"


# ---- 链捕获（服务级） ---------------------------------------------------------


@pytest.mark.anyio
async def test_chain_captured_on_multi_hop_with_final_marked():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a.xml":
            return httpx.Response(301, headers={"Location": "/b.xml"})
        if request.url.path == "/b.xml":
            return httpx.Response(302, headers={"Location": "/final.xml"})
        return httpx.Response(200, content=RSS_DOC)

    service = _service(handler, {"feed.example": [PUBLIC]})
    result = await service.preview("https://feed.example/a.xml?token=abc&sort=desc")
    chain = result.redirect_chain
    assert [hop["url"] for hop in chain] == [
        "https://feed.example/a.xml?token=***&sort=desc",
        "https://feed.example/b.xml",
        "https://feed.example/final.xml",
    ]
    assert [hop["status"] for hop in chain] == [301, 302, 200]
    # 仅末跳 final
    assert [hop["final"] for hop in chain] == [False, False, True]


@pytest.mark.anyio
async def test_single_hop_chain_is_final():
    service = _service(
        lambda request: httpx.Response(200, content=RSS_DOC),
        {"feed.example": [PUBLIC]},
    )
    result = await service.preview("https://feed.example/feed.xml")
    assert len(result.redirect_chain) == 1
    assert result.redirect_chain[0]["final"] is True
    assert result.redirect_chain[0]["status"] == 200


@pytest.mark.anyio
async def test_private_net_redirect_surfaces_failure_hop():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": "http://internal.example/x.xml"}
        )

    service = _service(
        handler,
        {
            "feed.example": [PUBLIC],
            "internal.example": ["10.0.0.5"],
        },
    )
    with pytest.raises(UnsafeFeedUrl) as excinfo:
        await service.preview("https://feed.example/feed.xml")
    chain = excinfo.value.redirect_chain
    assert len(chain) == 2
    # 失败跳：目标 URL 可见但请求从未发出（status=None）
    assert chain[0]["status"] == 302
    assert chain[0]["final"] is False
    assert chain[1]["url"] == "http://internal.example/x.xml"
    assert chain[1]["status"] is None


@pytest.mark.anyio
async def test_redirect_loop_surfaces_chain_with_all_hops():
    service = _service(
        lambda request: httpx.Response(
            302, headers={"Location": "https://feed.example/feed.xml"}
        ),
        {"feed.example": [PUBLIC]},
    )
    with pytest.raises(FeedFetchError) as excinfo:
        await service.preview("https://feed.example/feed.xml")
    chain = excinfo.value.redirect_chain
    # 5 次重定向上限：6 个请求尝试全部入链，全部 status=302、无 final
    assert len(chain) == 6
    assert all(hop["status"] == 302 for hop in chain)
    assert all(hop["final"] is False for hop in chain)


@pytest.mark.anyio
async def test_unreachable_origin_carries_first_hop_without_status():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    resolver = FakeResolver({"feed.example": [PUBLIC]})

    def pin_factory(*, resolver, ensure_public):
        return PinnedAddressTransport(
            resolver=resolver,
            ensure_public=ensure_public,
            delegate=httpx.MockTransport(handler),
        )

    class _NoControl:
        async def list_subscriptions(self):
            return []

    service = FeedPreviewService(
        _NoControl(), resolver=resolver, pin_factory=pin_factory
    )
    with pytest.raises(FeedFetchError) as excinfo:
        await service.preview("https://feed.example/feed.xml")
    chain = excinfo.value.redirect_chain
    assert len(chain) == 1
    assert chain[0]["url"] == "https://feed.example/feed.xml"
    assert chain[0]["status"] is None


# ---- 端点级（F044 迁移向导消费的响应形状） -------------------------------------


class _FakePreviewWithChain:
    def __init__(self, chain) -> None:
        self._chain = chain

    async def preview(self, feed_url, *, encoding_override=None):
        from lumirss.feed_preview import FeedPreview

        return FeedPreview(
            title="t",
            feed_url=feed_url,
            site_url=None,
            description=None,
            format="rss",
            already_subscribed=False,
            redirect_chain=self._chain,
        )


def test_feed_preview_endpoint_returns_redirect_chain():
    from pathlib import Path

    from lumirss.storage import Database

    with tempfile.TemporaryDirectory() as tmp:
        app.state.db = Database(Path(tmp) / "lumi.sqlite")
        chain = (
            {"url": "https://a.example/f.xml", "status": 301, "final": False},
            {"url": "https://b.example/final.xml", "status": 200, "final": True},
        )
        with TestClient(app) as client:
            # lifespan 启动会把服务槽位重置为 None —— 注入必须在启动之后。
            app.state.feed_preview_service = _FakePreviewWithChain(chain)
            response = client.post(
                "/api/v1/feed-preview", json={"feedUrl": "https://a.example/f.xml"}
            )
        app.state.feed_preview_service = None
    assert response.status_code == 200
    payload = response.json()
    assert payload["redirectChain"] == [
        {"url": "https://a.example/f.xml", "status": 301, "final": False},
        {"url": "https://b.example/final.xml", "status": 200, "final": True},
    ]


def test_feed_preview_error_carries_chain_and_failed_hop():
    from pathlib import Path

    from lumirss.storage import Database

    class _FailingService:
        def __init__(self) -> None:
            exc = UnsafeFeedUrl("Feed URL resolves to a non-public address.")
            exc.redirect_chain = (
                {"url": "https://a.example/f.xml", "status": 302, "final": False},
                {"url": "http://internal.example/x.xml", "status": None, "final": False},
            )
            self._exc = exc

        async def preview(self, feed_url, *, encoding_override=None):
            raise self._exc

    with tempfile.TemporaryDirectory() as tmp:
        app.state.db = Database(Path(tmp) / "lumi.sqlite")
        with TestClient(app) as client:
            app.state.feed_preview_service = _FailingService()
            response = client.post(
                "/api/v1/feed-preview", json={"feedUrl": "https://a.example/f.xml"}
            )
        app.state.feed_preview_service = None
    assert response.status_code == 400
    payload = response.json()
    # 稳定错误类型不变；附加链 + 失败跳
    assert payload["error"]["type"] == "unsafe_feed_url"
    assert len(payload["error"]["redirectChain"]) == 2
    assert payload["error"]["failedHop"] == "http://internal.example/x.xml"


def test_single_hop_plain_fetch_error_has_no_chain_extra():
    from pathlib import Path

    from lumirss.storage import Database

    class _FailingService:
        async def preview(self, feed_url, *, encoding_override=None):
            exc = FeedFetchError("The feed URL answered HTTP 500.")
            exc.redirect_chain = (
                {"url": feed_url, "status": 500, "final": False},
            )
            raise exc

    with tempfile.TemporaryDirectory() as tmp:
        app.state.db = Database(Path(tmp) / "lumi.sqlite")
        with TestClient(app) as client:
            app.state.feed_preview_service = _FailingService()
            response = client.post(
                "/api/v1/feed-preview", json={"feedUrl": "https://a.example/f.xml"}
            )
        app.state.feed_preview_service = None
    assert response.status_code == 502
    payload = response.json()
    assert payload["error"]["type"] == "feed_fetch_error"
    assert "redirectChain" not in payload["error"]
