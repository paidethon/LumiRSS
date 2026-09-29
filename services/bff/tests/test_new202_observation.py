"""NEW-202 订阅停更观察 —— 观察 CRUD、到期标注、抓取失败/停更区分。

验收问题对照：
- 谁：用户为可疑停更的来源设观察期（7..180 天）；
- 入口：POST /api/v1/new202/observations；同一来源同时至多一条
  active（409 observation_exists）；
- 之前/之后：观察期内 verdict=still_posting（投影有新文）；到期后
  expired=true，复核 continue/unsubscribed 落 closed 台账（系统绝不
  自动停订）；
- 核心口径（负向契约）：source_refresh_log 里 error（抓取失败）→
  verdict=fetch_failure，即使投影零新文也**不**判停更；投影无行 →
  no_data（资料缺失 ≠ 没有发文）；
- 消费 NEW-210：停机计划内的来源 fetchPaused=true；
- A/B 隔离：B 的观察 A 不可见、extend/close 404。

种子数据直接写 per-user 库的 source_refresh_log / search_entries
（既有派生表，迁移 0128 / 0006）。
"""

import pytest
from fastapi.testclient import TestClient

from lumirss.new202_observation import verdict_for
from lumirss.routers import new202_observation as observation_router
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


def _seed_projection(app, feed_url, rows):
    """直接写投影行（published_at 为 Z 串，与同步管线同形）。"""
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
                        f"条目 {index}",
                        published_at,
                    ),
                )

    asyncio.run(_run())


def _seed_refresh(app, feed_url, result):
    import asyncio

    from lumirss.user_scope import user_context

    async def _run():
        with user_context("owner"):
            db = app.state.db
            await db.migrate()
            await db.execute(
                "INSERT INTO source_refresh_log (feed_url, checked_at, result, entry_count)"
                " VALUES (?, '2026-09-01T00:00:00Z', ?, 0)",
                (feed_url, result),
            )

    asyncio.run(_run())


def _create(client, **overrides):
    body = {"feedUrl": FEED, "days": 14, "note": "最近很安静"}
    body.update(overrides)
    return client.post("/api/v1/new202/observations", json=body)


def test_new202_create_and_still_posting(make_client):
    client, app = make_client(observation_router.router)
    # 观察从「现在」开始：投影种子放在开始之后（+1h/+2h）
    from datetime import UTC, datetime, timedelta

    base = datetime.now(UTC).replace(microsecond=0)
    first = (base + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    second = (base + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_projection(app, FEED, [first, second])
    _seed_refresh(app, FEED, "ok")

    created = _create(client)
    assert created.status_code == 201, created.text
    observation = created.json()
    assert observation["status"] == "active"
    assert observation["postsSinceStart"] == 2
    assert observation["lastPostAt"] == second
    assert observation["verdict"] == "still_posting"
    assert observation["fetchHealth"] == "ok"

    # 同一来源第二条 active → 409
    duplicate = _create(client)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["type"] == "observation_exists"
    # 天数越界 → 422
    assert _create(client, feedUrl="https://x.example/f", days=5).status_code == 422


def test_new202_fetch_failure_is_not_staleness(make_client):
    """核心负向契约：抓取失败 ≠ 停更。"""
    client, app = make_client(observation_router.router)
    _seed_projection(app, FEED, ["2026-05-01T00:00:00Z"])  # 观察期内无新文
    _seed_refresh(app, FEED, "error")
    observation = _create(client).json()
    assert observation["postsSinceStart"] == 0
    assert observation["fetchHealth"] == "error"
    assert observation["verdict"] == "fetch_failure", "抓取失败不得误判为 no_new_posts"

    # 无投影、无检查记录 → no_data（诚实缺席）
    quiet_feed = "https://quiet.example/rss"
    _seed_refresh(app, quiet_feed, "ok")
    no_data = _create(client, feedUrl=quiet_feed).json()
    assert no_data["projectionRows"] == 0
    assert no_data["verdict"] == "no_data"
    assert verdict_for(fetch_health=None, projection_rows=0, posts_since_start=0) == "no_data"


def test_new202_extend_close_and_pause_marker(make_client):
    client, app = make_client(observation_router.router)
    observation = _create(client).json()

    extended = client.post(
        f"/api/v1/new202/observations/{observation['id']}/extend", json={"days": 30}
    )
    assert extended.status_code == 200
    assert extended.json()["endsAt"] > observation["endsAt"], "extend 只会推后到期日"

    # 消费 NEW-210：来源处于停机计划 → fetchPaused=true
    import asyncio

    from lumirss.new210_pause import PausePlanStore
    from lumirss.user_scope import user_context

    async def _pause():
        with user_context("owner"):
            store = PausePlanStore(app.state.db)
            await store.create(
                {
                    "feed_url": FEED,
                    "reason": None,
                    "start_at": "2020-01-01T00:00:00Z",
                    "end_at": "2099-01-01T00:00:00Z",
                }
            )

    asyncio.run(_pause())
    listing = client.get("/api/v1/new202/observations").json()
    assert listing["items"][0]["fetchPaused"] is True

    closed = client.post(
        f"/api/v1/new202/observations/{observation['id']}/close",
        json={"resolution": "continue"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert closed.json()["resolution"] == "continue"
    assert closed.json()["expired"] is False, "closed 行不再有到期语义"

    # 重复 close → 409；坏 resolution → 422
    again = client.post(
        f"/api/v1/new202/observations/{observation['id']}/close",
        json={"resolution": "unsubscribed"},
    )
    assert again.status_code == 409
    bad = client.post(
        f"/api/v1/new202/observations/{observation['id']}/extend", json={"days": 999}
    )
    assert bad.status_code == 422
    missing = client.post(
        "/api/v1/new202/observations/nope/close", json={"resolution": "continue"}
    )
    assert missing.status_code == 404


def test_new202_per_user_isolation(make_client):
    client, _app = make_client(observation_router.router)
    alice = {"x-test-user": "alice"}
    bob = {"x-test-user": "bob"}
    created = client.post(
        "/api/v1/new202/observations",
        json={"feedUrl": FEED, "days": 14},
        headers=bob,
    )
    assert created.status_code == 201
    observation_id = created.json()["id"]

    assert client.get("/api/v1/new202/observations", headers=alice).json()["items"] == []
    assert (
        client.post(
            f"/api/v1/new202/observations/{observation_id}/extend",
            json={"days": 14},
            headers=alice,
        ).status_code
        == 404
    )
    mine = client.get("/api/v1/new202/observations", headers=bob).json()["items"]
    assert [item["id"] for item in mine] == [observation_id]
