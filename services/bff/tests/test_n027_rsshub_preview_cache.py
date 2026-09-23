"""N027 — RSSHub 路由预览缓存控制。

覆盖：TTL 内第二次 preview 命中缓存（ageS>0、fresh=false、上游调用数
不增加）、refresh 强制绕过缓存重取该路由（返回刷新后条目数）、每用户
令牌桶限速（超限 429 + Retry-After）、其它路由/缓存不受影响、TTL 过期
后重新抓取、敏感哨兵路由拒绝刷新。上游用计数 MockTransport，无真实网络。
"""

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.rsshub import RssHubPreviewCache, RssHubService
from lumirss.storage import Database

BASE_URL = "http://rsshub.test:1200"

RSS_DOC = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>RSSHub Feed</title><link>https://example.com/</link>
  <description>desc</description>
  <item><title>one</title></item>
</channel></rss>"""


class FakeSettings:
    def __init__(self, base: str = BASE_URL) -> None:
        self.RSSHUB_BASE_URL = base
        self.RSSHUB_FRESHRSS_BASE_URL = ""

    @property
    def freshrss_base_url(self) -> str:
        return self.RSSHUB_FRESHRSS_BASE_URL or self.RSSHUB_BASE_URL


def _counting_service(calls: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=RSS_DOC)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def _list():
        return []

    service = RssHubService(client, SimpleNamespace(list_subscriptions=_list))
    service.load_settings = lambda: FakeSettings()  # type: ignore[method-assign]
    return service


@pytest.fixture()
def cache_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    from lumirss.routers import rsshub as rsshub_router

    with TestClient(app) as test_client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        # 每个用例全新的缓存 + 清空的限速桶（app 跨用例共享，必须显式隔离）
        app.state.rsshub_preview_cache = RssHubPreviewCache(ttl_s=300.0)
        rsshub_router._refresh_buckets.clear()
        yield test_client
    app.state.rsshub_service = None
    test_client.app.state.rsshub_refresh_rate = None


# ---- 缓存单元行为 -----------------------------------------------------------


def test_preview_cache_ttl_lru_and_user_isolation():
    import time

    preview = _probe_preview()
    cache = RssHubPreviewCache(ttl_s=0.05, capacity=2)
    cache.put("u1", "a", preview)
    cache.put("u1", "b", preview)
    hit = cache.get("u1", "a")
    assert hit is not None and hit[1] >= 0
    # 用户隔离：u2 看不到 u1 的缓存
    assert cache.get("u2", "a") is None
    # LRU：容量 2，再放 c → 最久未用的 b 被逐出
    cache.put("u1", "c", preview)
    assert cache.get("u1", "b") is None
    assert cache.get("u1", "a") is not None
    assert cache.get("u1", "c") is not None
    # TTL 过期
    time.sleep(0.06)
    assert cache.get("u1", "a") is None
    # invalidate 精确单点
    cache.put("u1", "a", preview)
    assert cache.invalidate("u1", "a") is True
    assert cache.invalidate("u1", "a") is False
    assert cache.get("u1", "a") is None


def _probe_preview():
    from lumirss.feed_preview import FeedPreview

    return FeedPreview(
        title="t",
        feed_url="http://x/feed",
        site_url=None,
        description=None,
        format="rss",
        already_subscribed=False,
        entry_count=1,
    )


# ---- 路由级行为 -------------------------------------------------------------


def test_second_preview_within_ttl_hits_cache_without_upstream_call(cache_client):
    calls = {"n": 0}
    app.state.rsshub_service = _counting_service(calls)
    first = cache_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["cache"] == {"ageS": 0.0, "fresh": True}
    assert calls["n"] == 1

    second = cache_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    assert second.status_code == 200
    cached = second.json()
    assert cached["cache"]["fresh"] is False
    assert cached["cache"]["ageS"] > 0
    assert calls["n"] == 1  # 上游零调用


def test_refresh_bypasses_cache_and_reports_entry_count(cache_client):
    calls = {"n": 0}
    app.state.rsshub_service = _counting_service(calls)
    cache_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    assert calls["n"] == 1
    refreshed = cache_client.post(
        "/api/v1/rsshub/refresh", json={"routeKey": "hackernews"}
    )
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert calls["n"] == 2  # 缓存被绕过
    assert payload["routeKey"] == "hackernews"
    assert payload["entryCount"] == 1
    assert payload["cache"]["fresh"] is True
    assert payload["durationMs"] >= 0
    assert payload["ranAt"]
    # 刷新已用新结果覆盖该路由缓存项 → 紧接的 preview 命中它（非 fresh、零上游调用）
    again = cache_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    assert again.json()["cache"]["fresh"] is False
    assert again.json()["cache"]["ageS"] >= 0
    assert calls["n"] == 2


def test_refresh_rate_limit_per_user_with_retry_after(cache_client):
    calls = {"n": 0}
    app.state.rsshub_service = _counting_service(calls)
    app.state.rsshub_refresh_rate = (2, 60.0)
    for _ in range(2):
        ok = cache_client.post(
            "/api/v1/rsshub/refresh", json={"routeKey": "hackernews"}
        )
        assert ok.status_code == 200
    limited = cache_client.post(
        "/api/v1/rsshub/refresh", json={"routeKey": "hackernews"}
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["type"] == "rsshub_refresh_rate_limited"
    retry_after = limited.headers.get("Retry-After")
    assert retry_after is not None and int(retry_after) >= 1


def test_refresh_leaves_other_routes_cached(cache_client):
    calls = {"n": 0}
    app.state.rsshub_service = _counting_service(calls)
    cache_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    cache_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "cnbeta", "params": {}}
    )
    assert calls["n"] == 2
    refreshed = cache_client.post(
        "/api/v1/rsshub/refresh", json={"routeKey": "hackernews"}
    )
    assert refreshed.status_code == 200
    assert calls["n"] == 3
    # hackernews：refresh 已重取并覆盖缓存 → preview 命中新缓存（零上游调用）
    hackernews = cache_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    assert hackernews.json()["cache"]["fresh"] is False
    assert calls["n"] == 3
    # cnbeta：完全不受影响，仍在缓存内
    cnbeta = cache_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "cnbeta", "params": {}}
    )
    assert cnbeta.json()["cache"]["fresh"] is False
    assert calls["n"] == 3


def test_refresh_rejects_sensitive_sentinel_route(cache_client):
    response = cache_client.post(
        "/api/v1/rsshub/refresh",
        json={"routeKey": "github-starred-repos|accessKey=***&user=DIYgod"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "rsshub_invalid_parameters"


def test_refresh_unknown_route_and_malformed_key(cache_client):
    unknown = cache_client.post(
        "/api/v1/rsshub/refresh", json={"routeKey": "nope"}
    )
    assert unknown.status_code == 404
    malformed = cache_client.post(
        "/api/v1/rsshub/refresh", json={"routeKey": "hackernews|&bad"}
    )
    assert malformed.status_code == 400
