"""NEW-210 来源抓取停机计划 —— 计划 CRUD + 生效判定 + 取消 + per-user 隔离。

验收问题对照：
- 谁给哪个来源设置暂停：owner/alice 各自给自己的订阅设暂停；
- 入口：POST /api/v1/new210/pauses（表单：起始/恢复/开放式/理由）；
- 之前/之后：active 端点的 feedUrls 集合在设置前后真实变化；
- 谁能取消：创建者本人（A 取消不了 B 的计划——不同用户库 404）；
- 持久化：计划跨请求存在（SQLite 行）；恢复时间到点自动失效
  （is_active 谓词，now 可注入验证）；
- 失败/恢复：取消后再取消 → 409（状态陈旧如实报告）；删除是
  housekeeping，默认路径是取消。

诚实负向契约：本组表面（active 端点响应 note）声明 FreshRSS 上游
抓取不可被 Lumi 逐源暂停——绝不伪装调度已被停止。
"""

import pytest
from fastapi.testclient import TestClient

from lumirss.new210_pause import PausePlanStore, is_active, validate_plan_input
from lumirss.routers import new210_pause as pause_router
from new201_210_harness import feature_app

FEED = "https://example.com/feed.xml"
OTHER = "https://other.example/rss"


@pytest.fixture()
def make_client(tmp_path):
    """挂载本特性路由的本地客户端（x-test-user 头切换用户）。"""
    clients = []

    def _make(*routers):
        app = feature_app(tmp_path, *routers)
        client = TestClient(app)
        clients.append(client)
        return client, app

    yield _make
    for client in clients:
        client.close()


def _create(client, **overrides):
    body = {"feedUrl": FEED, "endAt": "2030-01-01T00:00:00Z", "reason": "站点维护"}
    body.update(overrides)
    return client.post("/api/v1/new210/pauses", json=body)


def test_new210_validation_errors(make_client):
    client, _app = make_client(pause_router.router)
    # endAt 与 openEnded 都缺席 → 422 稳定错误
    missing = client.post("/api/v1/new210/pauses", json={"feedUrl": FEED})
    assert missing.status_code == 422
    assert missing.json()["error"]["type"] == "invalid_pause_plan"
    # endAt <= startAt → 422
    inverted = _create(
        client, startAt="2030-01-02T00:00:00Z", endAt="2030-01-01T00:00:00Z"
    )
    assert inverted.status_code == 422
    # 非法时刻 → 422；未知字段（extra=forbid）→ FastAPI 422
    bad_time = _create(client, endAt="not-a-time")
    assert bad_time.status_code == 422
    unknown = client.post(
        "/api/v1/new210/pauses", json={"feedUrl": FEED, "openEnded": True, "wat": 1}
    )
    assert unknown.status_code == 422


def test_new210_create_list_active_cancel_lifecycle(make_client):
    client, _app = make_client(pause_router.router)
    created = _create(client)
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["status"] == "active" and plan["activeNow"] is True
    assert plan["endAt"] == "2030-01-01T00:00:00Z"

    listing = client.get("/api/v1/new210/pauses").json()
    assert [p["id"] for p in listing["items"]] == [plan["id"]]

    active = client.get("/api/v1/new210/pauses/active").json()
    assert active["feedUrls"] == [FEED]
    assert "CRON_MIN" in active["note"]

    cancelled = client.post(f"/api/v1/new210/pauses/{plan['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["activeNow"] is False

    # 取消后 active 端点立即不含该来源（其他来源不受影响）
    active = client.get("/api/v1/new210/pauses/active").json()
    assert active["feedUrls"] == []

    # 取消后再取消 → 409 稳定错误（不是幂等 204）
    again = client.post(f"/api/v1/new210/pauses/{plan['id']}/cancel")
    assert again.status_code == 409
    assert again.json()["error"]["type"] == "pause_plan_already_cancelled"
    missing = client.post("/api/v1/new210/pauses/nope/cancel")
    assert missing.status_code == 404


def test_new210_window_predicate_and_open_ended(make_client):
    """恢复时间到点自动失效；开放式持续到取消（谓词级验证）。"""
    client, _app = make_client(pause_router.router)
    plan = _create(client, startAt="2029-06-01T00:00:00Z").json()
    assert plan["activeNow"] is False, "开始时间未到：尚未生效"

    # is_active 的 now 注入：区间内生效、到点失效
    inside = {"status": "active", "start_at": "2029-06-01T00:00:00Z", "end_at": "2029-06-02T00:00:00Z"}
    assert is_active(inside, now="2029-06-01T12:00:00Z") is True
    assert is_active(inside, now="2029-06-02T00:00:00Z") is False

    opened = _create(client, feedUrl=OTHER, openEnded=True, endAt=None)
    assert opened.status_code == 201
    assert opened.json()["endAt"] is None
    active = client.get("/api/v1/new210/pauses/active").json()
    assert set(active["feedUrls"]) == {OTHER}


def test_new210_per_user_isolation(make_client):
    """A/B 隔离：B 的计划对 A 不可见、不可取消（不同 per-user 库）。"""
    client, _app = make_client(pause_router.router)
    alice = {"x-test-user": "alice"}
    bob = {"x-test-user": "bob"}
    created = client.post(
        "/api/v1/new210/pauses",
        json={"feedUrl": FEED, "openEnded": True},
        headers=bob,
    )
    assert created.status_code == 201
    plan_id = created.json()["id"]

    assert client.get("/api/v1/new210/pauses", headers=alice).json()["items"] == []
    assert client.get("/api/v1/new210/pauses/active", headers=alice).json()["feedUrls"] == []
    assert (
        client.post(f"/api/v1/new210/pauses/{plan_id}/cancel", headers=alice).status_code
        == 404
    )
    assert client.get("/api/v1/new210/pauses/active", headers=bob).json()["feedUrls"] == [FEED]


def test_new210_store_roundtrip(tmp_path):
    """store 直连：校验输入归一（RFC3339 → Z 串）+ 谓词消费点。"""
    import asyncio

    from lumirss.storage import Database
    from lumirss.user_scope import user_context

    async def _run():
        database = Database(tmp_path / "control.sqlite")
        plan_input = validate_plan_input(
            feed_url=FEED,
            reason=None,
            start_at="2029-06-01T02:00:00+02:00",
            end_at=None,
            open_ended=True,
        )
        # +02:00 偏移归一为 UTC Z 串
        assert plan_input["start_at"] == "2029-06-01T00:00:00Z"
        with user_context("carol"):
            store = PausePlanStore(database)
            plan = await store.create(plan_input)
            urls = await store.paused_feed_urls(now="2029-06-01T00:00:01Z")
            assert urls == [FEED]
            await store.cancel(plan["id"])
            assert await store.paused_feed_urls(now="2029-06-01T00:00:01Z") == []

    asyncio.run(_run())
