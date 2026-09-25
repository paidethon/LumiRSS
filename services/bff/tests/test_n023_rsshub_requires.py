"""N023 RSSHub 路由依赖说明 —— catalog 元数据、preview 呈现与 0 条目提示。

- 目录条目携带 requires 元数据（curated 静态数据；字段三态
  true/false/null，null = 未知，诚实呈现）；
- preview 响应透出 requires（缓存命中路径同样透出）；
- 0 条目预览结果携带 zeroEntryHint（依赖可能未满足——不是健康状态）；
- wire 键集合固定：login / cookies / render / extraService。
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lumirss.feed_preview import FeedPreview
from lumirss.main import app
from lumirss.rsshub import CATALOG, RssHubPreviewCache
from lumirss.storage import Database

BASE_URL = "http://rsshub.test:1200"


class FakeSettings:
    def __init__(self, base: str = BASE_URL) -> None:
        self.RSSHUB_BASE_URL = base
        self.RSSHUB_FRESHRSS_BASE_URL = ""

    @property
    def freshrss_base_url(self) -> str:
        return self.RSSHUB_FRESHRSS_BASE_URL or self.RSSHUB_BASE_URL


def _preview(entry_count: int) -> FeedPreview:
    return FeedPreview(
        title="Route Feed",
        feed_url=f"{BASE_URL}/hackernews",
        site_url="https://news.ycombinator.com",
        description="desc",
        format="rss",
        already_subscribed=False,
        entry_count=entry_count,
    )


@pytest.fixture()
def n023_client(tmp_path):
    with TestClient(app) as test_client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        # 目录端点只读 list_routes/load_settings——注入 stub 避免构建真实
        # FreshRSS 适配器（测试环境无凭据）。时间线语义无关本套件：
        # 预览缓存 TTL=0 即未命中。
        from lumirss.rsshub import RssHubNotConfigured

        async def _noop():
            return []

        app.state.rsshub_service = SimpleNamespace(
            list_routes=lambda: list(CATALOG),
            load_settings=lambda: (_ for _ in ()).throw(RssHubNotConfigured("unset")),
        )
        app.state.rsshub_preview_cache = RssHubPreviewCache(ttl_s=0.0)
        yield test_client
    app.state.rsshub_service = None
    app.state.rsshub_route_probe = None


def test_n023_catalog_entries_carry_dependency_metadata(n023_client):
    response = n023_client.get("/api/v1/rsshub/routes")
    assert response.status_code == 200
    routes = {route["id"]: route for route in response.json()["routes"]}
    # 目录全部条目都带 requires（未标注 → null，同样是显式契约）。
    for route in CATALOG:
        wire = routes[route.id]["requires"]
        if route.requires is None:
            assert wire is None
            continue
        assert set(wire) == {"login", "cookies", "render", "extraService"}
        for value in wire.values():
            assert value in (True, False, None)

    # 已知事实抽检：YouTube 需要额外服务（API key）；知乎/酷安需要
    # Cookie；无需登录的条目如实标注 False。
    assert routes["youtube-channel"]["requires"]["extraService"] is True
    assert routes["zhihu-people-activities"]["requires"]["cookies"] is True
    assert routes["coolapk-hot"]["requires"]["cookies"] is True
    assert routes["hackernews"]["requires"] == {
        "login": False,
        "cookies": False,
        "render": False,
        "extraService": False,
    }
    # 部分未知：豆瓣 cookies 诚实留空（未知 ≠ 不需要）。
    assert routes["douban-book-latest"]["requires"]["cookies"] is None


def test_n023_preview_surfaces_requires_and_zero_entry_hint(n023_client):
    async def _probe(route_id, params, *, base_override=None):
        return _preview(entry_count=0)

    app.state.rsshub_route_probe = _probe
    response = n023_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["requires"]["extraService"] is False
    # 0 条目 → 诚实提示（依赖可能未满足，非健康状态）。
    assert payload["zeroEntryHint"] is not None
    assert "依赖" in payload["zeroEntryHint"]


def test_n023_preview_without_zero_entries_has_no_hint(n023_client):
    async def _probe(route_id, params, *, base_override=None):
        return _preview(entry_count=3)

    app.state.rsshub_route_probe = _probe
    response = n023_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    )
    payload = response.json()
    assert payload["zeroEntryHint"] is None
    assert payload["requires"] is not None


def test_n023_cache_hit_still_carries_metadata(n023_client):
    app.state.rsshub_preview_cache = RssHubPreviewCache(ttl_s=300.0)
    async def _probe(route_id, params, *, base_override=None):
        return _preview(entry_count=0)

    app.state.rsshub_route_probe = _probe
    first = n023_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    ).json()
    second = n023_client.post(
        "/api/v1/rsshub/preview", json={"routeId": "hackernews", "params": {}}
    ).json()
    assert second["cache"]["fresh"] is False
    assert second["requires"] == first["requires"]
    assert second["zeroEntryHint"] is not None
    app.state.rsshub_preview_cache = RssHubPreviewCache(ttl_s=0.0)
