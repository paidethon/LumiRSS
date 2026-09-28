"""End-to-end clip fetch pipeline tests (phase2 recovery P0-03).

Exercises fetch_page / fetch_extract_sanitize against a real local HTTP
origin through the PINNED transport (stub resolver + loopback-permitting
policy — production keeps the feed-preview baseline). Covers: the FINAL
url after redirects (audit issue #4), the chain-level time budget, bad
MIME refusal, and the full fetch → extract → sanitize → text pipeline.
"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

import lumirss.clip_fetch as clip_fetch
from lumirss.clip_fetch import (
    ClipFetchError,
    ClipForbidden,
    fetch_extract_sanitize,
    fetch_page,
)
from lumirss.ssrf_transport import PinnedAddressTransport

ARTICLE_HTML = (
    "<html><head><title>测试文章标题</title>"
    '<meta name="author" content="李四"></head><body>'
    "<nav><a href='/nav'>导航噪音</a></nav>"
    "<article><p>这是服务器提取出的正文第一段，句子足够长并且带有标点符号，用于评分。</p>"
    "<p>第二段正文，继续讲述完整的内容，保证段落评分足够高。</p>"
    "<script>alert('must-not-survive')</script></article>"
    "<footer>页脚噪音</footer></body></html>"
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — stdlib API
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/final")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/binary":
            body = b"\x89PNG-not-html"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/empty":
            body = b"<html><head></head><body></body></html>"
        else:
            body = ARTICLE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def origin_port():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _loopback_policy(address: str) -> None:
    return  # tests dial the local origin through the pinned transport


def _transport_factory():
    def make(*, resolver, ensure_public):
        return PinnedAddressTransport(
            resolver=resolver,
            ensure_public=ensure_public,
        )

    return make


def _resolver_for(port):
    async def resolver(host, port_):
        return ["127.0.0.1"]  # stub "DNS": the public name IS loopback here

    return resolver


def _run(coro):
    return asyncio.run(coro)


def test_fetch_page_returns_final_url_after_redirect(origin_port):
    url = f"http://web.example:{origin_port}/redirect"
    page = _run(
        fetch_page(
            url,
            resolver=_resolver_for(origin_port),
            ensure_public=_loopback_policy,
            pin_factory=_transport_factory(),
        )
    )
    assert page.final_url == f"http://web.example:{origin_port}/final"
    assert "测试文章标题" in page.html


def test_fetch_page_refuses_non_html(origin_port):
    url = f"http://web.example:{origin_port}/binary"
    with pytest.raises(ClipForbidden) as excinfo:
        _run(
            fetch_page(
                url,
                resolver=_resolver_for(origin_port),
                ensure_public=_loopback_policy,
                pin_factory=_transport_factory(),
            )
        )
    assert excinfo.value.reason == "bad_mime"


def test_chain_level_time_budget(origin_port, monkeypatch):
    """One slow hop eats the WHOLE chain budget — the pre-recovery code
    allowed per-request timeouts to stack (5 hops ≈ 2 minutes)."""
    monkeypatch.setattr(clip_fetch, "_CHAIN_BUDGET_SECONDS", 0.3)

    class _SlowTransport(PinnedAddressTransport):
        async def handle_async_request(self, request):
            await asyncio.sleep(1.0)
            return await super().handle_async_request(request)

    def slow_factory(*, resolver, ensure_public):
        return _SlowTransport(resolver=resolver, ensure_public=ensure_public)

    url = f"http://web.example:{origin_port}/article"
    with pytest.raises(ClipFetchError) as excinfo:
        _run(
            fetch_page(
                url,
                resolver=_resolver_for(origin_port),
                ensure_public=_loopback_policy,
                pin_factory=slow_factory,
            )
        )
    assert excinfo.value.reason == "timeout"


def test_full_pipeline_extracts_sanitizes_and_derives_text(origin_port):
    url = f"http://web.example:{origin_port}/article"
    page = _run(
        fetch_extract_sanitize(
            url,
            resolver=_resolver_for(origin_port),
            ensure_public=_loopback_policy,
        )
    )
    assert page.final_url == url  # no redirect: final == requested
    assert page.title == "测试文章标题"
    assert page.byline == "李四"
    assert "服务器提取出的正文第一段" in page.content_html
    assert "must-not-survive" not in page.content_html  # sanitized server-side
    assert "<script" not in page.content_html
    assert "导航噪音" not in page.content_html  # chrome pruned
    assert "页脚噪音" not in page.content_html
    assert "服务器提取出的正文第一段" in page.content_text


def test_full_pipeline_fails_honestly_on_bodyless_page(origin_port):
    url = f"http://web.example:{origin_port}/empty"
    with pytest.raises(ClipFetchError) as excinfo:
        _run(
            fetch_extract_sanitize(
                url,
                resolver=_resolver_for(origin_port),
                ensure_public=_loopback_policy,
            )
        )
    assert excinfo.value.reason == "extract_failed"


# --- FIX-250 基线核验：重定向每一跳都重过 URL/DNS/IP 安检 -------------------
#
# 审计场景：首跳公网、重定向落向 169.254.169.254（云元数据地址）必须被
# 拒；逐跳放行链必须照常工作。全部走 MockTransport 委托的 pinned 传输，
# 绝无真实网络。feed_preview 侧已有 private/localhost 重定向拒绝测试
# （test_feed_preview.py），此处补页面抓取路径。

_METADADATA_HOST = "169.254.169.254"


def _mock_resolver_map():
    return {
        "public.example": ["93.184.216.34"],
        "other.example": ["93.184.216.35"],
        _METADADATA_HOST: [_METADADATA_HOST],
    }


def _pinned_mock_factory(handler):
    """pin_factory：真实 pinned 逻辑 + MockTransport 委托（不拨真实网）。"""

    def make(*, resolver, ensure_public):
        return PinnedAddressTransport(
            resolver=resolver,
            ensure_public=ensure_public,
            delegate=httpx.MockTransport(handler),
        )

    return make


def test_redirect_chain_into_metadata_address_is_blocked():
    """重定向落向云元数据地址：在 validate_hop 处被拒，且该地址从未被
    拨号（pinned 传输里也无人替它发起请求）。"""
    dialed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        dialed.append(str(request.url))
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=ARTICLE_HTML
        )

    async def resolver(host, port):
        return _mock_resolver_map()[host]

    def redirector(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34" and request.url.path == "/redirect":
            return httpx.Response(
                302,
                headers={"Location": f"http://{_METADADATA_HOST}/latest/meta-data/"},
            )
        return handler(request)

    with pytest.raises(ClipForbidden) as excinfo:
        _run(
            fetch_page(
                "http://public.example/redirect",
                resolver=resolver,
                pin_factory=_pinned_mock_factory(redirector),
            )
        )
    assert excinfo.value.reason == "unsafe_address"
    # 元数据地址一跳都没有真正发出（连接层零请求）。
    assert all(_METADADATA_HOST not in url for url in dialed)


def test_redirect_chain_through_public_hops_is_allowed():
    """逐跳放行链：公网 → 公网重定向 → 200 HTML 照常工作，final_url
    记录最终落点。"""

    async def resolver(host, port):
        return _mock_resolver_map()[host]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34" and request.url.path == "/redirect":
            return httpx.Response(
                302, headers={"Location": "http://other.example/final"}
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=ARTICLE_HTML,
        )

    page = _run(
        fetch_page(
            "http://public.example/redirect",
            resolver=resolver,
            pin_factory=_pinned_mock_factory(handler),
        )
    )
    assert page.final_url == "http://other.example/final"
    assert "测试文章标题" in page.html
