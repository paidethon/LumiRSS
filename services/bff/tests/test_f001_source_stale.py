"""F001 来源新鲜度预警 —— per-source 阈值、stale 端点口径与路由校验。

- 阈值前后判定：latest_entry 年龄 > 阈值才列入；
- unknown basis 不误报：投影无条目的来源绝不判超期；
- 配置持久：新 store 实例（模拟重启）后阈值仍在；
- 路由：threshold/staleAlertHours 参数校验（422）与 sentinel 语义。
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from lumirss.main import app
from lumirss.source_overrides import SourceOverrideStore


def run(coroutine):
    return asyncio.run(coroutine)


def _iso(hours_ago: float) -> str:
    moment = datetime.now(UTC) - timedelta(hours=hours_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _install_adapter(feeds: list[str]) -> None:
    subs = [
        SimpleNamespace(
            stream_id=f"feed/{i}",
            feed_url=url,
            title=f"源 {i}",
            subscription_ref=f"s1.ref{i}",
        )
        for i, url in enumerate(feeds)
    ]

    async def _list_subs():
        return subs

    app.state.freshrss_adapter = SimpleNamespace(list_subscriptions=_list_subs)


def _seed_projection(feed_url: str, published_iso: str) -> None:
    async def _seed():
        await app.state.db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                feed_url,
                feed_url,
                feed_url,
                "源",
                "条目",
                "",
                "",
                "",
                published_iso,
                0,
                0,
                1789660000,
            ),
        )

    run(_seed())


def test_f001_threshold_boundary_and_basis(client):
    stale_url = "https://slow.example.com/rss"
    fresh_url = "https://fast.example.com/rss"
    _install_adapter([stale_url, fresh_url])
    store = SourceOverrideStore(app.state.db)
    run(store.set_fields(stale_url, stale_alert_hours=24))
    run(store.set_fields(fresh_url, stale_alert_hours=24))
    _seed_projection(stale_url, _iso(hours_ago=25.0))
    _seed_projection(fresh_url, _iso(hours_ago=2.0))

    body = client.get("/api/v1/sources/stale").json()
    feed_urls = [item["feedUrl"] for item in body["items"]]
    assert stale_url in feed_urls, "25h 未更新 > 24h 阈值 → 列入"
    assert fresh_url not in feed_urls, "2h 未更新 < 24h 阈值 → 不列入"
    stale_item = next(i for i in body["items"] if i["feedUrl"] == stale_url)
    assert stale_item["basis"] == "latest_entry"
    assert stale_item["staleAlertHours"] == 24
    assert stale_item["ageHours"] is not None and stale_item["ageHours"] > 24
    assert body["checked"] == 2

    # 全局兜底阈值：只作用于未单独配置的来源
    run(store.set_fields(stale_url, stale_alert_hours=None))
    body2 = client.get("/api/v1/sources/stale?threshold=48").json()
    assert [i["feedUrl"] for i in body2["items"]] == []  # 25h < 48h
    body3 = client.get("/api/v1/sources/stale?threshold=6").json()
    assert stale_url in [i["feedUrl"] for i in body3["items"]]


def test_f001_unknown_basis_not_reported(client):
    quiet_url = "https://quiet.example.com/rss"
    _install_adapter([quiet_url])
    store = SourceOverrideStore(app.state.db)
    run(store.set_fields(quiet_url, stale_alert_hours=1))
    # 无任何投影条目 → basis=unknown，绝不判超期
    body = client.get("/api/v1/sources/stale").json()
    assert [i["feedUrl"] for i in body["items"]] == []
    assert body["checked"] == 1


def test_f001_config_persists_across_restart(client):
    url = "https://persist.example.com/rss"
    run(SourceOverrideStore(app.state.db).set_fields(url, stale_alert_hours=72))
    # 模拟重启：全新 store 实例读同一数据库
    fresh_store = SourceOverrideStore(app.state.db)
    assert run(fresh_store.stale_alert_configs()) == {url: 72}
    listing = client.get("/api/v1/sources/overrides").json()
    item = next(i for i in listing["items"] if i["feedUrl"] == url)
    assert item["staleAlertHours"] == 72


def test_f001_route_validation_and_sentinel(client):
    url = "https://api.example.com/rss"
    _install_adapter([url])
    ok = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": url, "staleAlertHours": 12},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["staleAlertHours"] == 12

    # 0 小时 / 超上限 → 422（pydantic 约束）
    assert (
        client.put(
            "/api/v1/sources/overrides",
            json={"feedUrl": url, "staleAlertHours": 0},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/sources/overrides",
            json={"feedUrl": url, "staleAlertHours": 100000},
        ).status_code
        == 422
    )
    # GET threshold 参数校验
    assert client.get("/api/v1/sources/stale?threshold=0").status_code == 422
    assert client.get("/api/v1/sources/stale?threshold=-5").status_code == 422

    # sentinel：null 清除该维度（其余维度不动）
    cleared = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": url, "staleAlertHours": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["staleAlertHours"] is None
