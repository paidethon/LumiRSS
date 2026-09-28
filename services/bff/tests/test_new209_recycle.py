"""NEW-209 订阅变动回收箱 —— 退订捕获配置 / 限期 / 恢复 / 放弃 + 隔离。

验收问题对照：
- 谁：用户退订自己的订阅时选择保留天数（1..365）；
- 入口：订阅行「退订进回收箱」（POST /api/v1/new209/unsubscribe）；
- 之前/之后：退订前上游清单有该订阅、回收箱为空；退订后上游清单
  没有了、箱内多一行**完整配置**（URL/标题/分类/保留期）；
- 恢复：按原配置重新订阅（新代次 stream id），行转 restored；
  恢复调用真实走了捕获的 categoryId/title（适配器假件记录参数）；
- 承诺边界：恢复的是**配置**；源站已删正文不承诺恢复（响应 note）；
- 失败/恢复：重复恢复/放弃 → 409 稳定信封；未知行 404；
- A/B 隔离：B 的回收箱行 A 不可见、不可恢复。

上游交互全部走注入的 SimpleNamespace 假件（与 F004 套件同模式），
测试零网络。
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lumirss.new209_recycle import UnsubscribeBinStore, is_expired
from lumirss.routers import new209_recycle as recycle_router
from lumirss.subscriptionref import encode_subscription_ref
from new201_210_harness import feature_app

FEED = "https://example.com/feed.xml"


@pytest.fixture()
def make_client(tmp_path):
    clients = []

    def _make(*routers, adapter=None):
        app = feature_app(tmp_path, *routers)
        if adapter is not None:
            app.state.freshrss_control_adapter = adapter
        client = TestClient(app)
        clients.append(client)
        return client, app

    yield _make
    for client in clients:
        client.close()


def _adapter(subs, calls):
    """假控制适配器：记录 subscribe/unsubscribe 调用。"""

    async def _list():
        return list(subs)

    async def _unsubscribe(stream_id):
        calls.append(("unsubscribe", stream_id))
        subs[:] = [s for s in subs if s.stream_id != stream_id]

    async def _subscribe(feed_url, category_id=None, title=None):
        calls.append(("subscribe", feed_url, category_id, title))
        index = 100 + len(calls)
        created = SimpleNamespace(
            stream_id=f"feed/{index}",
            subscription_ref=encode_subscription_ref(f"feed/{index}"),
            title=title or "新标题",
            feed_url=feed_url,
            category_id=category_id,
            category_label=None,
        )
        subs.append(created)
        return created

    async def _move_to_new_category(stream_id, label):
        calls.append(("move_to_new_category", stream_id, label))

    return SimpleNamespace(
        list_subscriptions=_list,
        unsubscribe=_unsubscribe,
        subscribe=_subscribe,
        move_to_new_category=_move_to_new_category,
    )


def _sub(index, title, feed_url=FEED, category_id=None, category_label=None):
    stream_id = f"feed/{index}"
    return SimpleNamespace(
        stream_id=stream_id,
        subscription_ref=encode_subscription_ref(stream_id),
        title=title,
        feed_url=feed_url,
        category_id=category_id,
        category_label=category_label,
    )


def test_new209_unsubscribe_capture_restore_roundtrip(make_client):
    calls: list = []
    subs = [_sub(1, "示例源", category_id="cat-7", category_label="技术")]
    client, _app = make_client(recycle_router.router, adapter=_adapter(subs, calls))
    ref = encode_subscription_ref("feed/1")

    created = client.post(
        "/api/v1/new209/unsubscribe", json={"subscriptionRef": ref, "keepDays": 30}
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert ("unsubscribe", "feed/1") in calls
    assert row["feedUrl"] == FEED
    assert row["categoryId"] == "cat-7" and row["categoryLabel"] == "技术"
    assert row["status"] == "kept" and row["expired"] is False
    assert row["purgeAfter"] > row["unsubscribedAt"]

    # 退订生效：上游清单已无该订阅
    assert subs == []

    # 恢复：按捕获配置重新订阅（新代次）
    restored = client.post(f"/api/v1/new209/bin/{row['id']}/restore")
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["status"] == "restored"
    assert body["restoredStreamId"] != "feed/1"
    assert ("subscribe", FEED, "cat-7", "示例源") in calls
    assert FEED in [s.feed_url for s in subs]

    # 重复恢复 → 409 稳定信封
    again = client.post(f"/api/v1/new209/bin/{row['id']}/restore")
    assert again.status_code == 409
    assert again.json()["error"]["type"] == "bin_row_not_restorable"
    assert client.post("/api/v1/new209/bin/nope/restore").status_code == 404


def test_new209_discard_and_label_recreate_path(make_client):
    calls: list = []
    subs = [_sub(2, "无分类源")]
    client, _app = make_client(recycle_router.router, adapter=_adapter(subs, calls))
    created = client.post(
        "/api/v1/new209/unsubscribe",
        json={"subscriptionRef": encode_subscription_ref("feed/2"), "keepDays": 7},
    ).json()

    discarded = client.post(f"/api/v1/new209/bin/{created['id']}/discard")
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "discarded"
    # discard 行默认不出现在列表（显式 include 才回）
    assert client.get("/api/v1/new209/bin").json()["items"] == []
    listing = client.get("/api/v1/new209/bin", params={"includeDiscarded": True}).json()
    assert [r["id"] for r in listing["items"]] == [created["id"]]
    assert "正文" in listing["note"]
    again = client.post(f"/api/v1/new209/bin/{created['id']}/discard")
    assert again.status_code == 409

    # 无 categoryId 但有 label 的行：恢复走 move_to_new_category 重建归位
    subs2 = [_sub(5, "随笔源", category_id=None, category_label="随笔")]
    calls2: list = []
    client2, _app2 = make_client(recycle_router.router, adapter=_adapter(subs2, calls2))
    row2 = client2.post(
        "/api/v1/new209/unsubscribe",
        json={"subscriptionRef": encode_subscription_ref("feed/5"), "keepDays": 7},
    ).json()
    restored = client2.post(f"/api/v1/new209/bin/{row2['id']}/restore")
    assert restored.status_code == 200
    assert ("move_to_new_category", restored.json()["restoredStreamId"], "随笔") in calls2


def test_new209_validation_errors(make_client):
    calls: list = []
    subs = [_sub(3, "示例源")]
    client, _app = make_client(recycle_router.router, adapter=_adapter(subs, calls))
    bad_ref = client.post(
        "/api/v1/new209/unsubscribe", json={"subscriptionRef": "garbage", "keepDays": 30}
    )
    assert bad_ref.status_code == 400
    assert bad_ref.json()["error"]["type"] == "invalid_subscription_ref"
    out_of_range = client.post(
        "/api/v1/new209/unsubscribe",
        json={"subscriptionRef": encode_subscription_ref("feed/3"), "keepDays": 400},
    )
    assert out_of_range.status_code == 422
    missing_sub = client.post(
        "/api/v1/new209/unsubscribe",
        json={"subscriptionRef": encode_subscription_ref("feed/999"), "keepDays": 30},
    )
    assert missing_sub.status_code == 404
    assert missing_sub.json()["error"]["type"] == "subscription_not_found"


def test_new209_per_user_isolation(make_client):
    calls: list = []
    subs = [_sub(4, "B 的源")]
    client, _app = make_client(recycle_router.router, adapter=_adapter(subs, calls))
    bob = {"x-test-user": "bob"}
    alice = {"x-test-user": "alice"}
    created = client.post(
        "/api/v1/new209/unsubscribe",
        json={"subscriptionRef": encode_subscription_ref("feed/4"), "keepDays": 7},
        headers=bob,
    )
    assert created.status_code == 201
    row_id = created.json()["id"]

    assert client.get("/api/v1/new209/bin", headers=alice).json()["items"] == []
    assert (
        client.post(f"/api/v1/new209/bin/{row_id}/restore", headers=alice).status_code
        == 404
    )
    mine = client.get("/api/v1/new209/bin", headers=bob).json()["items"]
    assert [r["id"] for r in mine] == [row_id]


def test_new209_expiry_is_annotation_not_deletion(tmp_path):
    """过期 = 标注（expired=true），行保留等待显式放弃（无调度器）。"""
    import asyncio

    from lumirss.storage import Database
    from lumirss.user_scope import user_context

    async def _run():
        database = Database(tmp_path / "control.sqlite")
        with user_context("dave"):
            store = UnsubscribeBinStore(database)
            row = await store.capture(
                feed_url=FEED,
                stream_id="feed/9",
                title="过期演示",
                category_id=None,
                category_label=None,
                keep_days=1,
                unsubscribed_at="2026-01-01T00:00:00Z",
            )
            assert is_expired(row, now="2026-01-03T00:00:00Z") is True
            assert is_expired(row, now="2026-01-01T12:00:00Z") is False
            rows = await store.list_rows()
            assert rows[0]["status"] == "kept", "过期不自动删除，等显式 discard"

    asyncio.run(_run())
