"""F087 书签失效检查 — 分类 fixtures、重定向不改书签（负向）、SSRF 拒绝、
去重、超时分类。探测经注入的 MockTransport，绝不触网。"""

import asyncio

import httpx

from lumirss.bookmarks_check import LinkCheckService, SsrfBlocked
from lumirss.main import app

OK_URL = "https://ok.example/page"
REDIRECT_URL = "https://red.example/old"
NF_URL = "https://nf.example/gone"
AUTH_URL = "https://auth.example/locked"
RATE_URL = "https://rate.example/busy"
TIMEOUT_URL = "https://slow.example/wait"
PRIVATE_URL = "http://127.0.0.1:8080/admin"


def run(coro):
    return asyncio.run(coro)


def _mock_client_factory(handler):
    transport = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self):
            super().__init__(transport=transport, trust_env=False)

    return _Client


def _service(handler):
    return LinkCheckService(client_factory=_mock_client_factory(handler))


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url == REDIRECT_URL:
        return httpx.Response(302, headers={"location": "https://final.example/here"})
    if url == NF_URL:
        return httpx.Response(404)
    if url == AUTH_URL:
        return httpx.Response(403)
    if url == RATE_URL:
        return httpx.Response(429)
    if url == TIMEOUT_URL:
        raise httpx.ConnectTimeout("timeout")
    return httpx.Response(200)


def test_f087_status_classification_via_route(client):
    ref = client.post(
        "/api/v1/library/bookmarks",
        json={"url": REDIRECT_URL, "title": "跳转书签"},
    ).json()["ref"]
    ref2 = client.post(
        "/api/v1/library/bookmarks",
        json={"url": NF_URL, "title": "失效书签"},
    ).json()["ref"]
    monkey = _service(_handler)
    import lumirss.routers.library_w5 as lw5

    original = lw5.LinkCheckService
    lw5.LinkCheckService = lambda **kw: monkey
    try:
        result = client.post(
            "/api/v1/library/bookmarks/check-links",
            json={"refs": [ref, ref2]},
        )
    finally:
        lw5.LinkCheckService = original
    assert result.status_code == 200, result.text
    items = {i["ref"]: i for i in result.json()["items"]}
    assert items[ref]["status"] == "redirect"
    assert items[ref]["finalUrl"] == "https://final.example/here"
    assert items[ref2]["status"] == "not_found"
    # 负向：重定向绝不改写书签 URL
    row = run(
        app.state.db.fetch_one(
            "SELECT url FROM library_bookmarks WHERE url = ?", (REDIRECT_URL,)
        )
    )
    assert row["url"] == REDIRECT_URL


def test_f087_dedupe_and_more_classes_unit(client):
    seen_urls = []

    def counting_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen_urls.append(url)
        if url == RATE_URL:
            return httpx.Response(429)
        if url == AUTH_URL:
            return httpx.Response(403)
        if url == TIMEOUT_URL:
            raise httpx.ConnectTimeout("timeout")
        return httpx.Response(200)

    service = _service(counting_handler)
    results = run(
        service.check_many([OK_URL, OK_URL, RATE_URL, TIMEOUT_URL, AUTH_URL])
    )
    by_url = {r["ref"]: r for r in results}
    assert len(results) == 4  # 重复 ref 去重
    assert by_url[OK_URL]["status"] == "ok"
    assert by_url[RATE_URL]["status"] == "rate_limited"
    assert by_url[TIMEOUT_URL]["status"] == "timeout"
    assert by_url[AUTH_URL]["status"] == "auth_required"
    # 每个 URL 只探测一次
    assert len([u for u in seen_urls if u == OK_URL]) == 1


def test_f087_ssrf_private_network_rejected(client):
    async def _always_block(url):
        raise SsrfBlocked("private address")

    class _BlockingClient(httpx.AsyncClient):
        def __init__(self):
            super().__init__(trust_env=False)

        async def request(self, *a, **kw):
            raise SsrfBlocked("private address")

    service = LinkCheckService(client_factory=lambda: _BlockingClient())
    result = run(service.check_one(PRIVATE_URL))
    assert result["status"] == "blocked_ssrf"


def test_f087_head_fallback_get_bounded_read(client):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(200, content=b"x" * 1024)

    service = _service(handler)
    result = run(service.check_one(OK_URL))
    assert result["status"] == "ok"
    assert requests_seen[0] == "HEAD"
    assert "GET" in requests_seen
