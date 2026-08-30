"""Tests E / F — /api/v1/feeds route wiring with an injected fake adapter.

No real FreshRSS is contacted: we replace app.state.freshrss_adapter with a
stub, so these tests exercise the route and error mapping only.
"""

from fastapi.testclient import TestClient

from lumirss.adapters.freshrss import AuthenticationError, Feed, UpstreamConnectionError
from lumirss.main import app


class FakeAdapter:
    def __init__(self, feeds=None, error=None) -> None:
        self.feeds = feeds or []
        self.error = error
        self.calls = 0

    async def list_feeds(self) -> list[Feed]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.feeds


def test_feeds_route_returns_lumirss_json_shape():
    fake = FakeAdapter(
        feeds=[
            Feed(
                title="FreshRSS releases",
                feed_url="https://example.com/releases.xml",
                category_id="user/-/label/技术",
                category_label="技术",
            ),
            Feed(title="阮一峰的网络日志", feed_url="https://example.com/ruanyifeng.xml"),
        ]
    )
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake  # inject after lifespan startup
            response = client.get("/api/v1/feeds")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        # 0011：feed 附带 FreshRSS 真实分类（categoryId 稳定 key + label
        # 展示名）；无分类 → category: null（前端归入未分组）
        assert body == [
            {
                "title": "FreshRSS releases",
                "feedUrl": "https://example.com/releases.xml",
                "category": {"id": "user/-/label/技术", "label": "技术"},
            },
            {
                "title": "阮一峰的网络日志",
                "feedUrl": "https://example.com/ruanyifeng.xml",
                "category": None,
            },
        ]
        assert fake.calls == 1  # cached adapter is reused, not recreated
    finally:
        app.state.freshrss_adapter = None


def test_feeds_route_maps_authentication_error():
    fake = FakeAdapter(error=AuthenticationError("FreshRSS rejected the credentials."))
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake  # inject after lifespan startup
            response = client.get("/api/v1/feeds")

        assert response.status_code == 502
        body = response.json()
        assert body["error"]["type"] == "authentication_error"
        assert "message" in body["error"]
    finally:
        app.state.freshrss_adapter = None


def test_feeds_route_maps_connection_error():
    fake = FakeAdapter(
        error=UpstreamConnectionError("Could not reach FreshRSS.")
    )
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake  # inject after lifespan startup
            response = client.get("/api/v1/feeds")

        assert response.status_code == 502
        assert response.json()["error"]["type"] == "connection_error"
    finally:
        app.state.freshrss_adapter = None
