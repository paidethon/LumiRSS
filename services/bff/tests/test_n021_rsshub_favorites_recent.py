"""N021 — RSSHub 路由收藏与最近使用。

覆盖：收藏 PUT/GET/DELETE 往返与 upsert 语义、未知路由 404、
敏感参数值永不入库（DB 行内只有 '***' 哨兵）、最近使用仅在
preview/subscribe 成功后 upsert（失败不记录）。fetch 全部 mock，
service 走 app.state 注入（F050 health_probe 同一注入模式）。
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.rsshub import RssHubService
from lumirss.storage import Database
from lumirss.subscriptionref import encode_subscription_ref

RSS_DOC = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>RSSHub Feed</title><link>https://example.com/</link>
  <description>desc</description>
</channel></rss>"""

BASE_URL = "http://rsshub.test:1200"


class FakeSettings:
    def __init__(self, base: str = BASE_URL) -> None:
        self.RSSHUB_BASE_URL = base
        self.RSSHUB_FRESHRSS_BASE_URL = ""

    @property
    def freshrss_base_url(self) -> str:
        return self.RSSHUB_FRESHRSS_BASE_URL or self.RSSHUB_BASE_URL


def _fake_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok_service() -> RssHubService:
    client = _fake_client(lambda request: httpx.Response(200, content=RSS_DOC))
    return _service(client)


def _failing_service(status: int = 503) -> RssHubService:
    client = _fake_client(
        lambda request: httpx.Response(status, content=b"boom")
    )
    return _service(client)


def _service(client: httpx.AsyncClient) -> RssHubService:
    async def _list():
        return []

    service = RssHubService(client, SimpleNamespace(list_subscriptions=_list))
    service.load_settings = lambda: FakeSettings()  # type: ignore[method-assign]
    return service


@pytest.fixture()
def rsshub_client(monkeypatch, tmp_path):
    """TestClient + temp per-user DB；服务每次用例注入成功/失败 fake。"""
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    with TestClient(app) as test_client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        yield test_client
    app.state.rsshub_service = None


def test_favorite_roundtrip_upsert_and_delete(rsshub_client):
    put = rsshub_client.put(
        "/api/v1/rsshub/routes/favorites",
        json={"routeId": "github-starred-repos", "params": {"user": "DIYgod"}, "label": "我的星标"},
    )
    assert put.status_code == 200
    item = put.json()
    assert item["templateId"] == "github-starred-repos"
    assert item["routeKey"] == "github-starred-repos|user=DIYgod"
    assert item["params"] == {"user": "DIYgod"}
    assert item["label"] == "我的星标"

    listing = rsshub_client.get("/api/v1/rsshub/routes/favorites").json()
    assert len(listing) == 1

    # 同 route_key 再 PUT → upsert（改标签，不新增行）
    again = rsshub_client.put(
        "/api/v1/rsshub/routes/favorites",
        json={"routeId": "github-starred-repos", "params": {"user": "DIYgod"}, "label": "改名"},
    )
    assert again.status_code == 200
    listing = rsshub_client.get("/api/v1/rsshub/routes/favorites").json()
    assert len(listing) == 1
    assert listing[0]["label"] == "改名"

    # DELETE 命中 → 204 + 列表为空；再删 → 404 rsshub_favorite_not_found
    deleted = rsshub_client.delete(
        f"/api/v1/rsshub/routes/favorites/{item['routeKey']}"
    )
    assert deleted.status_code == 204
    assert rsshub_client.get("/api/v1/rsshub/routes/favorites").json() == []
    missing = rsshub_client.delete(
        "/api/v1/rsshub/routes/favorites/github-starred-repos%7Cuser%3DDIYgod"
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "rsshub_favorite_not_found"


def test_favorite_unknown_route_404(rsshub_client):
    put = rsshub_client.put(
        "/api/v1/rsshub/routes/favorites",
        json={"routeId": "nope", "params": {}},
    )
    assert put.status_code == 404
    assert put.json()["error"]["type"] == "rsshub_route_not_found"


def test_sensitive_param_value_never_stored(rsshub_client):
    """敏感键（*key*）值入库前必须变成 '***' 哨兵——DB 行与响应都查不到原值。"""
    put = rsshub_client.put(
        "/api/v1/rsshub/routes/favorites",
        json={
            "routeId": "github-starred-repos",
            "params": {"user": "DIYgod", "accessKey": "sekret-value-123"},
        },
    )
    assert put.status_code == 200
    assert put.json()["params"] == {"user": "DIYgod", "accessKey": "***"}

    row = asyncio.run(
        app.state.db.fetch_one(
            "SELECT params_json FROM rsshub_route_favorites WHERE template_id = 'github-starred-repos'"
        )
    )
    assert row is not None
    stored = json.loads(str(row["params_json"]))
    assert stored["accessKey"] == "***"
    assert "sekret-value-123" not in str(stored)

    # route_key 里同样只有哨兵
    listing = rsshub_client.get("/api/v1/rsshub/routes/favorites").json()
    assert listing[0]["routeKey"] == (
        "github-starred-repos|accessKey=***&user=DIYgod"
    )


def test_recent_recorded_on_successful_preview_only(rsshub_client):
    app.state.rsshub_service = _ok_service()
    ok = rsshub_client.post(
        "/api/v1/rsshub/preview",
        json={"routeId": "github-starred-repos", "params": {"user": "DIYgod"}},
    )
    assert ok.status_code == 200
    recent = rsshub_client.get("/api/v1/rsshub/routes/recent").json()
    assert [item["templateId"] for item in recent] == ["github-starred-repos"]
    assert recent[0]["params"] == {"user": "DIYgod"}
    assert recent[0]["lastSuccessAt"] is not None

    # 失败的 preview（另一条路由）绝不上最近使用
    app.state.rsshub_service = _failing_service()
    failed = rsshub_client.post(
        "/api/v1/rsshub/preview",
        json={"routeId": "hackernews", "params": {}},
    )
    assert failed.status_code == 502
    recent = rsshub_client.get("/api/v1/rsshub/routes/recent").json()
    assert [item["templateId"] for item in recent] == ["github-starred-repos"]
    app.state.rsshub_service = None


def test_recent_upsert_refreshes_last_used_at(rsshub_client):
    app.state.rsshub_service = _ok_service()
    for _ in range(2):
        response = rsshub_client.post(
            "/api/v1/rsshub/preview",
            json={"routeId": "hackernews", "params": {}},
        )
        assert response.status_code == 200
    recent = rsshub_client.get("/api/v1/rsshub/routes/recent").json()
    assert len(recent) == 1
    assert recent[0]["routeKey"] == "hackernews"
    app.state.rsshub_service = None


def test_subscribe_success_records_recent(rsshub_client):
    """服务端从 feedUrl 路径反推路由 → 成功订阅记最近使用（含路径参数）。"""

    async def _list():
        return []

    created = SimpleNamespace(
        stream_id="feed/9",
        subscription_ref=encode_subscription_ref("feed/9"),
        title="Starred repos",
        feed_url="http://rsshub:1200/github/starred_repos/DIYgod",
        category_id=None,
        category_label=None,
    )

    async def _subscribe(url, category_id=None, title=None):
        assert url == "http://rsshub:1200/github/starred_repos/DIYgod"
        return created

    app.state.freshrss_control_adapter = SimpleNamespace(
        list_subscriptions=_list, subscribe=_subscribe
    )
    response = rsshub_client.post(
        "/api/v1/subscriptions",
        json={"feedUrl": "http://rsshub:1200/github/starred_repos/DIYgod"},
    )
    assert response.status_code == 201
    recent = rsshub_client.get("/api/v1/rsshub/routes/recent").json()
    assert [item["templateId"] for item in recent] == ["github-starred-repos"]
    assert recent[0]["params"] == {"user": "DIYgod"}
    app.state.freshrss_control_adapter = None


def test_subscribe_non_catalog_url_records_nothing(rsshub_client):
    async def _list():
        return []

    created = SimpleNamespace(
        stream_id="feed/9",
        subscription_ref=encode_subscription_ref("feed/9"),
        title="Plain feed",
        feed_url="https://example.com/feed.xml",
        category_id=None,
        category_label=None,
    )

    async def _subscribe(url, category_id=None, title=None):
        return created

    app.state.freshrss_control_adapter = SimpleNamespace(
        list_subscriptions=_list, subscribe=_subscribe
    )
    response = rsshub_client.post(
        "/api/v1/subscriptions",
        json={"feedUrl": "https://example.com/feed.xml"},
    )
    assert response.status_code == 201
    assert rsshub_client.get("/api/v1/rsshub/routes/recent").json() == []
    app.state.freshrss_control_adapter = None
