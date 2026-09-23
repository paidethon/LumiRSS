"""N026 — RSSHub 路由上游故障分辨。

覆盖（4 类故障 → 4 个不同 failureClass，绝不全部坍缩成 network_error）：
- rsshub_unreachable：连接/超时到 RSSHub 源站；
- upstream_reject：RSSHub 把上游错误页（200 HTML「RSSHub 内部错误」）
  或其它 4xx/5xx 原样吐回；
- auth_failure：RSSHub 对 Lumi 返回 401/403（如 access key 错）；
- no_new_content：feed 正常但 0 条目、且窗口内曾有内容（新路由首次
  0 条目是正常 ok，不算故障）。

服务级用 httpx.MockTransport 注入故障；路由级走 app.state.rsshub_route_probe
（F050 health_probe 同一注入模式）驱动完整 HTTP 面：错误体 failureClass
+ 时间线行分类。全程无真实网络。
"""

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.feed_preview import FeedPreview, NotAFeedError
from lumirss.main import app
from lumirss.rsshub import (
    FAILURE_AUTH_FAILURE,
    FAILURE_NO_NEW_CONTENT,
    FAILURE_NOT_FOUND,
    FAILURE_RATE_LIMITED,
    FAILURE_RSSHUB_UNREACHABLE,
    FAILURE_UPSTREAM_REJECT,
    RssHubFetchError,
    RssHubPreviewCache,
    RssHubService,
    looks_like_rsshub_error_page,
)
from lumirss.storage import Database

BASE_URL = "http://rsshub.test:1200"

FEED_DOC = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>RSSHub Feed</title><link>https://example.com/</link>
  <description>desc</description>
</channel></rss>"""

RSSHUB_ERROR_PAGE = (
    "<!DOCTYPE html><html><head><title>Error</title></head><body>"
    "<h1>RSSHub 内部错误</h1><p>parse timed out</p></body></html>"
).encode()


class FakeSettings:
    def __init__(self, base: str = BASE_URL) -> None:
        self.RSSHUB_BASE_URL = base
        self.RSSHUB_FRESHRSS_BASE_URL = ""

    @property
    def freshrss_base_url(self) -> str:
        return self.RSSHUB_FRESHRSS_BASE_URL or self.RSSHUB_BASE_URL


async def preview_with(handler, *, route_id: str = "hackernews"):
    """Service-level fault injection: the MockTransport handler IS the fault."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def _list():
        return []

    service = RssHubService(client, SimpleNamespace(list_subscriptions=_list))
    service.load_settings = lambda: FakeSettings()  # type: ignore[method-assign]
    try:
        return await service.preview(route_id, {})
    finally:
        await client.aclose()


# ---- 服务级分类（MockTransport 即故障源） -----------------------------------


@pytest.mark.anyio
async def test_connect_timeout_classified_rsshub_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(RssHubFetchError) as exc_info:
        await preview_with(handler)
    assert exc_info.value.failure_class == FAILURE_RSSHUB_UNREACHABLE


@pytest.mark.anyio
async def test_rsshub_401_classified_auth_failure():
    with pytest.raises(RssHubFetchError) as exc_info:
        await preview_with(lambda r: httpx.Response(401, content=b"denied"))
    assert exc_info.value.failure_class == FAILURE_AUTH_FAILURE


@pytest.mark.anyio
async def test_rsshub_404_classified_not_found():
    with pytest.raises(RssHubFetchError) as exc_info:
        await preview_with(lambda r: httpx.Response(404, content=b"no route"))
    assert exc_info.value.failure_class == FAILURE_NOT_FOUND


@pytest.mark.anyio
async def test_rsshub_429_classified_rate_limited():
    with pytest.raises(RssHubFetchError) as exc_info:
        await preview_with(lambda r: httpx.Response(429, content=b"slow down"))
    assert exc_info.value.failure_class == FAILURE_RATE_LIMITED


@pytest.mark.anyio
async def test_rsshub_500_classified_upstream_reject():
    with pytest.raises(RssHubFetchError) as exc_info:
        await preview_with(lambda r: httpx.Response(500, content=b"boom"))
    assert exc_info.value.failure_class == FAILURE_UPSTREAM_REJECT


@pytest.mark.anyio
async def test_error_page_200_classified_upstream_reject():
    """200 + HTML 错误页（RSSHub 内部错误）→ upstream_reject，而非 not_a_feed。"""
    with pytest.raises(RssHubFetchError) as exc_info:
        await preview_with(lambda r: httpx.Response(200, content=RSSHUB_ERROR_PAGE))
    assert exc_info.value.failure_class == FAILURE_UPSTREAM_REJECT


@pytest.mark.anyio
async def test_plain_garbage_stays_not_a_feed():
    """无 RSSHub 错误页特征的 200 垃圾 → 保持既有 not_a_feed 稳定契约。"""
    with pytest.raises(NotAFeedError):
        await preview_with(lambda r: httpx.Response(200, content=b"<html>nope</html>"))


def test_error_page_sniffer_bounded_and_specific():
    assert looks_like_rsshub_error_page(RSSHUB_ERROR_PAGE) is True
    assert looks_like_rsshub_error_page(FEED_DOC) is False
    assert looks_like_rsshub_error_page(b"<html>plain garbage</html>") is False


# ---- 路由级故障注入（app.state.rsshub_route_probe，F050 模式） ---------------


@pytest.fixture()
def probe_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    with TestClient(app) as test_client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        # N027：本套件关注故障分类——预览缓存禁用（TTL=0 即未命中）
        app.state.rsshub_preview_cache = RssHubPreviewCache(ttl_s=0.0)
        yield test_client
    app.state.rsshub_route_probe = None


def _probe_raising(failure_class: str):
    async def probe(route_id, params, *, base_override=None):
        raise RssHubFetchError("injected fault", failure_class=failure_class)

    return probe


def _probe_ok(entry_count: int):
    async def probe(route_id, params, *, base_override=None):
        return FeedPreview(
            title="t",
            feed_url=f"{BASE_URL}/hackernews",
            site_url=None,
            description=None,
            format="rss",
            already_subscribed=False,
            entry_count=entry_count,
        )

    return probe


def test_four_scenarios_yield_four_distinct_classes(probe_client):
    """4 个受控故障场景 → 4 个互不相同的 failureClass（错误体 + 时间线一致）。"""
    key = "hackernews"
    scenarios = [
        (FAILURE_RSSHUB_UNREACHABLE, 502),
        (FAILURE_UPSTREAM_REJECT, 502),
        (FAILURE_AUTH_FAILURE, 502),
        (FAILURE_NOT_FOUND, 502),
    ]
    seen: set[str] = set()
    for failure_class, expected_status in scenarios:
        app.state.rsshub_route_probe = _probe_raising(failure_class)
        response = probe_client.post(
            "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
        )
        assert response.status_code == expected_status
        error = response.json()["error"]
        # 稳定错误类型不变；failureClass 精确区分故障
        assert error["type"] == "rsshub_fetch_error"
        assert error["failureClass"] == failure_class
        seen.add(error["failureClass"])
        rows = probe_client.get(
            "/api/v1/rsshub/routes/history", params={"routeKey": key}
        ).json()["items"]
        assert rows[0]["failureClass"] == failure_class
        assert rows[0]["status"] == "failed"
    assert len(seen) == 4  # 绝不全部坍缩成 network_error
    app.state.rsshub_route_probe = None


def test_no_new_content_on_dried_up_route(probe_client):
    """窗口内曾有内容、现在 0 条目 → no_new_content（status 仍 ok）。"""
    key = "hackernews"
    app.state.rsshub_route_probe = _probe_ok(entry_count=5)
    first = probe_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    assert first.status_code == 200
    assert (
        probe_client.get(
            "/api/v1/rsshub/routes/history", params={"routeKey": key}
        ).json()["items"][0]["failureClass"]
        is None
    )

    # 上游枯竭：同一路由 0 条目 → no_new_content
    app.state.rsshub_route_probe = _probe_ok(entry_count=0)
    second = probe_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    assert second.status_code == 200
    row = probe_client.get(
        "/api/v1/rsshub/routes/history", params={"routeKey": key}
    ).json()["items"][0]
    assert row["status"] == "ok"
    assert row["entryCount"] == 0
    assert row["failureClass"] == FAILURE_NO_NEW_CONTENT

    # 对照：全新路由首次 0 条目是正常状态，不是故障
    app.state.rsshub_route_probe = _probe_ok(entry_count=0)
    fresh = probe_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "cnbeta", "params": {}}
    )
    assert fresh.status_code == 200
    fresh_row = probe_client.get(
        "/api/v1/rsshub/routes/history", params={"routeKey": "cnbeta"}
    ).json()["items"][0]
    assert fresh_row["status"] == "ok"
    assert fresh_row["failureClass"] is None
    app.state.rsshub_route_probe = None
