"""N025 — RSSHub 路由健康时间线。

覆盖：preview 尝试写入运行行（成功含 entry_count；fetch 阶段失败写
failed 行，参数校验失败不写）、每 route_key 20 条裁剪、history 端点
有界返回、订阅成功/失败写时间线、行内无敏感值。fetch 全部 mock，
service 走 app.state 注入（F050 health_probe 同一注入模式）。
"""

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.rsshub import RssHubPreviewCache, RssHubService
from lumirss.rsshub_route_store import compute_route_key
from lumirss.storage import Database
from lumirss.subscriptionref import encode_subscription_ref

RSS_DOC_ENTRIES = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>RSSHub Feed</title><link>https://example.com/</link>
  <description>desc</description>
  <item><title>one</title></item>
  <item><title>two</title></item>
  <item><title>three</title></item>
</channel></rss>"""

RSS_DOC_EMPTY = b"""<?xml version="1.0"?>
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


def _service(doc: bytes = RSS_DOC_ENTRIES) -> RssHubService:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=doc)
        )
    )

    async def _list():
        return []

    service = RssHubService(client, SimpleNamespace(list_subscriptions=_list))
    service.load_settings = lambda: FakeSettings()  # type: ignore[method-assign]
    return service


def _failing_service() -> RssHubService:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, content=b"boom")
        )
    )

    async def _list():
        return []

    service = RssHubService(client, SimpleNamespace(list_subscriptions=_list))
    service.load_settings = lambda: FakeSettings()  # type: ignore[method-assign]
    return service


@pytest.fixture()
def runs_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    with TestClient(app) as test_client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        # N027：时间线语义 = 真实上游尝试——禁用预览缓存（TTL=0 即未命中）
        app.state.rsshub_preview_cache = RssHubPreviewCache(ttl_s=0.0)
        yield test_client
    app.state.rsshub_service = None


def _history(client, route_key: str, **params):
    return client.get(
        "/api/v1/rsshub/routes/history",
        params={"routeKey": route_key, **params},
    )


def test_preview_records_ok_run_with_entry_count(runs_client):
    app.state.rsshub_service = _service(RSS_DOC_ENTRIES)
    response = runs_client.post(
        "/api/v1/rsshub/preview",
        json={"routeId": "hackernews", "params": {}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["routeKey"] == "hackernews"

    history = _history(runs_client, "hackernews")
    assert history.status_code == 200
    items = history.json()["items"]
    assert len(items) == 1
    run = items[0]
    assert run["status"] == "ok"
    assert run["entryCount"] == 3
    assert run["failureClass"] is None
    assert run["durationMs"] >= 0
    assert run["ranAt"]

    # 0 条目也是 ok（新路由属正常状态；N026 再分辨 no_new_content）
    app.state.rsshub_service = _service(RSS_DOC_EMPTY)
    empty = runs_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    assert empty.status_code == 200
    items = _history(runs_client, "hackernews").json()["items"]
    assert items[0]["status"] == "ok"
    assert items[0]["entryCount"] == 0
    app.state.rsshub_service = None


def test_failed_fetch_records_run_but_validation_errors_do_not(runs_client):
    # fetch 阶段失败（503）→ failed 行
    app.state.rsshub_service = _failing_service()
    failed = runs_client.post(
        "/api/v1/rsshub/preview",
        json={"routeId": "hackernews", "params": {}},
    )
    assert failed.status_code == 502
    items = _history(runs_client, "hackernews").json()["items"]
    assert [run["status"] for run in items] == ["failed"]
    # 失败不进最近使用
    assert runs_client.get("/api/v1/rsshub/routes/recent").json() == []

    # 参数校验失败（没到 fetch 阶段）→ 不写时间线
    app.state.rsshub_service = _service()
    invalid = runs_client.post(
        "/api/v1/rsshub/preview",
        json={"routeId": "nope", "params": {}},
    )
    assert invalid.status_code == 404
    bad_params = runs_client.post(
        "/api/v1/rsshub/preview",
        json={"routeId": "hackernews", "params": {"bogus": "x"}},
    )
    assert bad_params.status_code == 400
    assert _history(runs_client, "hackernews").json()["items"][0]["status"] == "failed"
    assert _history(runs_client, "nope").json()["items"] == []
    app.state.rsshub_service = None


def test_runs_pruned_to_last_20_per_route(runs_client):
    app.state.rsshub_service = _service()
    for _ in range(25):
        response = runs_client.post(
            "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
        )
        assert response.status_code == 200
    items = _history(runs_client, "hackernews").json()["items"]
    assert len(items) == 20
    # 最新的在前
    assert items[0]["id"] > items[-1]["id"]
    # 另一路由不受影响
    other = runs_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "cnbeta", "params": {}}
    )
    assert other.status_code == 200
    assert len(_history(runs_client, "cnbeta").json()["items"]) == 1
    app.state.rsshub_service = None


def test_history_route_key_bounded_limit(runs_client):
    missing = runs_client.get("/api/v1/rsshub/routes/history")
    assert missing.status_code == 422
    too_high = _history(runs_client, "hackernews", limit=21)
    assert too_high.status_code == 422
    bounded = _history(runs_client, "hackernews", limit=1)
    assert bounded.status_code == 200


def test_run_rows_never_carry_secrets(runs_client):
    """route_key 由服务端脱敏生成；带未知敏感参数的请求在参数校验阶段
    被拒（无时间线行），库内行不含任何敏感值。"""
    app.state.rsshub_service = _service()
    masked_key = compute_route_key("hackernews", {"accessToken": "s3cret"})
    assert "s3cret" not in masked_key
    assert masked_key == "hackernews|accessToken=***"

    response = runs_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    assert response.status_code == 200
    raw = str(_history(runs_client, "hackernews").json())
    assert "s3cret" not in raw
    app.state.rsshub_service = None


def test_subscribe_attempts_record_runs(runs_client):
    ok_created = SimpleNamespace(
        stream_id="feed/9",
        subscription_ref=encode_subscription_ref("feed/9"),
        title="x",
        feed_url="http://rsshub:1200/github/starred_repos/DIYgod",
        category_id=None,
        category_label=None,
    )
    calls = {"n": 0}

    async def _list():
        return []

    async def _subscribe(url, category_id=None, title=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return ok_created
        from lumirss.adapters.freshrss import UpstreamConnectionError

        raise UpstreamConnectionError("freshrss down")

    app.state.freshrss_control_adapter = SimpleNamespace(
        list_subscriptions=_list, subscribe=_subscribe
    )
    key = "github-starred-repos|user=DIYgod"

    ok = runs_client.post(
        "/api/v1/subscriptions",
        json={"feedUrl": "http://rsshub:1200/github/starred_repos/DIYgod"},
    )
    assert ok.status_code == 201
    failed = runs_client.post(
        "/api/v1/subscriptions",
        json={"feedUrl": "http://rsshub:1200/github/starred_repos/DIYgod"},
    )
    assert failed.status_code == 502

    items = _history(runs_client, key).json()["items"]
    assert [run["status"] for run in items] == ["failed", "ok"]
    assert items[0]["failureClass"] == "network_error"
    assert items[1]["failureClass"] is None
    app.state.freshrss_control_adapter = None
