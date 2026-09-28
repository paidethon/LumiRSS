"""NEW-206 来源阅读日历 —— 月界聚合、空月/资料缺失区分、只读负向契约。

验收问题对照：
- 谁看：用户按真实发表日期浏览某个来源（投影口径）；
- 入口：GET /api/v1/new206/calendar?feedUrl=&month=YYYY-MM；
- 之前/之后：种子跨月条目 → 只落当月桶、按日分桶、当日样本 ≤5、
  可打开当日文章（entryRef 原样返回）；
- 核心口径：投影中该来源**一行都没有** → coverage=no_projection_data
  （资料缺失 ≠ 当月没发文）；有行但当月无条目 → 正常空日历
  （coverage=projection, days=[]）；
- 消费 NEW-210：停机计划中的来源 fetchPaused=true；
- 只读负向契约：请求前后投影行数逐字节不变；
- A/B 隔离：per-user 投影天然隔离（B 的种子不出现在 A 的日历）。
"""

import pytest
from fastapi.testclient import TestClient

from lumirss.new206_calendar import build_calendar, validate_month
from lumirss.routers import new206_calendar as calendar_router
from new201_210_harness import feature_app

FEED = "https://example.com/feed.xml"


@pytest.fixture()
def make_client(tmp_path):
    clients = []

    def _make(*routers):
        app = feature_app(tmp_path, *routers)
        client = TestClient(app)
        clients.append(client)
        return client, app

    yield _make
    for client in clients:
        client.close()


def _seed(app, feed_url, rows):
    import asyncio

    from lumirss.user_scope import user_context

    async def _run():
        with user_context("owner"):
            db = app.state.db
            await db.migrate()
            for index, published_at in enumerate(rows):
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url,"
                    " feed_title, title, author, url, content_text, published_at,"
                    " read, starred, fetched_at)"
                    " VALUES (?, ?, ?, '', ?, '', '', '', ?, 0, 0, 0)",
                    (
                        f"{feed_url}#item-{index}",
                        f"e1.{feed_url}.{index}",
                        feed_url,
                        f"文章 {index}",
                        published_at,
                    ),
                )

    asyncio.run(_run())


def test_new206_validate_month_and_pure_bucketing():
    assert validate_month("2026-09") == "2026-09"
    for bad in ("2026-13", "202609", "2026-9", "ab-cd", "2026-00", ""):
        with pytest.raises(ValueError):
            validate_month(bad)
    calendar = build_calendar(
        [
            ("e1.a", "甲", "2026-09-01T05:00:00Z"),
            ("e1.b", "乙", "2026-09-01T09:00:00Z"),
            ("e1.c", "丙", "2026-09-30T23:00:00Z"),
            ("e1.d", "丁", "2026-10-01T00:00:00Z"),  # 越界行：诚实计数不落桶
        ],
        "2026-09",
    )
    assert calendar["totalEntries"] == 3
    assert calendar["outOfWindowRows"] == 1
    day_counts = {day["date"]: day["count"] for day in calendar["days"]}
    assert day_counts == {"2026-09-01": 2, "2026-09-30": 1}


def test_new206_calendar_endpoint_and_no_data_semantics(make_client):
    client, app = make_client(calendar_router.router)
    _seed(app, FEED, [
        "2026-09-03T08:00:00Z",
        "2026-09-03T12:00:00Z",
        "2026-08-20T00:00:00Z",
        "2026-07-01T00:00:00Z",
    ])
    view = client.get(
        "/api/v1/new206/calendar", params={"feedUrl": FEED, "month": "2026-09"}
    )
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["coverage"] == "projection"
    assert body["totalEntries"] == 2
    day = body["days"][0]
    assert day["date"] == "2026-09-03" and day["count"] == 2
    assert [s["entryRef"] for s in day["sample"]] == [f"e1.{FEED}.0", f"e1.{FEED}.1"]

    # 有行但当月无条目 → 正常空日历（不是资料缺失）
    empty_month = client.get(
        "/api/v1/new206/calendar", params={"feedUrl": FEED, "month": "2026-05"}
    ).json()
    assert empty_month["coverage"] == "projection"
    assert empty_month["days"] == [] and empty_month["totalEntries"] == 0

    # 投影中零行 → no_projection_data（资料缺失，诚实区分）
    unknown = client.get(
        "/api/v1/new206/calendar",
        params={"feedUrl": "https://never.example/rss", "month": "2026-09"},
    ).json()
    assert unknown["coverage"] == "no_projection_data"
    assert "资料缺失" in unknown["note"]

    # 校验：坏月份 422 稳定信封
    bad = client.get(
        "/api/v1/new206/calendar", params={"feedUrl": FEED, "month": "2026-99"}
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "invalid_month"

    # 只读负向契约：请求不改变投影行数
    import asyncio

    from lumirss.user_scope import user_context

    async def _count():
        with user_context("owner"):
            row = await app.state.db.fetch_one(
                "SELECT COUNT(*) AS n FROM search_entries", ()
            )
            return int(row["n"])

    assert asyncio.run(_count()) == 4


def test_new206_pause_marker_and_isolation(make_client):
    client, app = make_client(calendar_router.router)
    _seed(app, FEED, ["2026-09-10T00:00:00Z"])
    bob = {"x-test-user": "bob"}

    # A（owner）无暂停 → fetchPaused=false；B 的库里没种子 → no data
    body = client.get(
        "/api/v1/new206/calendar", params={"feedUrl": FEED, "month": "2026-09"}
    ).json()
    assert body["fetchPaused"] is False
    assert body["totalEntries"] == 1
    assert (
        client.get(
            "/api/v1/new206/calendar",
            params={"feedUrl": FEED, "month": "2026-09"},
            headers=bob,
        ).json()["coverage"]
        == "no_projection_data"
    )

    # 消费 NEW-210：A 给来源设停机计划 → fetchPaused=true
    import asyncio

    from lumirss.new210_pause import PausePlanStore
    from lumirss.user_scope import user_context

    async def _pause():
        with user_context("owner"):
            await PausePlanStore(app.state.db).create(
                {
                    "feed_url": FEED,
                    "reason": None,
                    "start_at": "2020-01-01T00:00:00Z",
                    "end_at": "2099-01-01T00:00:00Z",
                }
            )

    asyncio.run(_pause())
    body = client.get(
        "/api/v1/new206/calendar", params={"feedUrl": FEED, "month": "2026-09"}
    ).json()
    assert body["fetchPaused"] is True
    assert "暂停" in body["note"]
