"""NEW-201 订阅接管向导 —— 预演映射/不重复订阅/继承目录/台账 + 隔离。

验收问题对照：
- 谁/输入：用户把同一用户旧实例导出的 OPML 交给向导；
- 入口：订阅管理「接管导入」（POST /api/v1/new201/takeover/preview，
  只读）→ 预览冲突 → 确认 → apply；
- 之前/之后：预演把导出映射为 新建 / 已订（绝不重复订阅——同批与
  跨批均不重复，负向契约断言 subscribe 未被以已订 URL 调用）/ 无效
  三类；apply 后新 feed 已订阅并按导出分类归位（move_to_new_category
  建类），已有 feed 可按确认「继承目录」（move）；
- 持久化：apply 台账逐批留痕（含逐项结果）；预演零写入；
- 失败/恢复：坏 OPML → 422 takeover_invalid_opml；单项失败不阻断
  其他项（逐项 outcome=failed 如实回报）；
- A/B 隔离：B 的接管台账 A 不可见（per-user 库）。

上游交互走 SimpleNamespace 假件（F004 同模式），零网络。
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lumirss.new201_takeover import TakeoverStore, build_plan
from lumirss.opml import OpmlEntry, ParsedOpml
from lumirss.routers import new201_takeover as takeover_router
from lumirss.subscriptionref import encode_subscription_ref
from new201_210_harness import feature_app

OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0"><head><title>旧实例导出</title></head>
<body>
  <outline text="技术">
    <outline text="新源甲" xmlUrl="https://new-a.example/feed"/>
    <outline text="已订源" xmlUrl="https://existing.example/feed"/>
  </outline>
  <outline text="随笔">
    <outline text="新源乙" xmlUrl="https://new-b.example/rss"/>
  </outline>
  <outline text="坏项" xmlUrl="ftp://not-a-feed"/>
</body></opml>"""


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
    async def _list():
        return list(subs)

    async def _subscribe(feed_url, category_id=None, title=None):
        calls.append(("subscribe", feed_url, category_id, title))
        index = 50 + len(calls)
        created = SimpleNamespace(
            stream_id=f"feed/{index}",
            subscription_ref=encode_subscription_ref(f"feed/{index}"),
            title=title or "",
            feed_url=feed_url,
            category_id=None,
            category_label=None,
        )
        subs.append(created)
        return created

    async def _move_to_new_category(stream_id, label):
        calls.append(("move_to_new_category", stream_id, label))

    return SimpleNamespace(
        list_subscriptions=_list,
        subscribe=_subscribe,
        move_to_new_category=_move_to_new_category,
    )


def _sub(index, feed_url, title, category_label=None):
    stream_id = f"feed/{index}"
    return SimpleNamespace(
        stream_id=stream_id,
        subscription_ref=encode_subscription_ref(stream_id),
        title=title,
        feed_url=feed_url,
        category_id="cat-x",
        category_label=category_label,
    )


def test_new201_preview_maps_export_to_current(make_client):
    calls: list = []
    subs = [_sub(1, "https://existing.example/feed", "已订源", category_label="旧分类")]
    client, _app = make_client(takeover_router.router, adapter=_adapter(subs, calls))

    preview = client.post("/api/v1/new201/takeover/preview", json={"opml": OPML})
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["exportedTotal"] == 3 + 1  # 3 可用 + 1 无效
    assert [item["feedUrl"] for item in plan["toSubscribe"]] == [
        "https://new-a.example/feed",
        "https://new-b.example/rss",
    ]
    assert plan["toSubscribe"][0]["categoryLabel"] == "技术"
    assert len(plan["alreadySubscribed"]) == 1
    existing = plan["alreadySubscribed"][0]
    assert existing["categoryDiffers"] is True, "导出分类 vs 当前分类差异如实标注"
    assert existing["currentCategory"] == "旧分类"
    assert plan["invalidCount"] == 1
    assert "绝不重复订阅" in plan["note"]
    assert calls == [], "预演零写入（上游零 mutation）"

    # 坏 OPML → 422 稳定信封
    bad = client.post(
        "/api/v1/new201/takeover/preview", json={"opml": "<html>not-opml</html>"}
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "takeover_invalid_opml"


def test_new201_apply_subscribes_only_new_and_inherits_category(make_client):
    calls: list = []
    subs = [_sub(1, "https://existing.example/feed", "已订源", category_label="旧分类")]
    client, _app = make_client(takeover_router.router, adapter=_adapter(subs, calls))

    result = client.post(
        "/api/v1/new201/takeover/apply",
        json={
            "label": "从旧实例接管",
            "items": [
                {
                    "action": "subscribe",
                    "feedUrl": "https://new-a.example/feed",
                    "title": "新源甲",
                    "categoryLabel": "技术",
                },
                {
                    "action": "subscribe",
                    "feedUrl": "https://existing.example/feed",
                },
                {
                    "action": "move",
                    "feedUrl": "https://existing.example/feed",
                    "categoryLabel": "技术",
                },
            ],
        },
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["created"] == 1
    assert body["skippedExisting"] == 1, "已订 URL 绝不重复订阅"
    assert body["moved"] == 1
    assert body["failed"] == 0
    subscribe_calls = [c for c in calls if c[0] == "subscribe"]
    assert [c[1] for c in subscribe_calls] == ["https://new-a.example/feed"], (
        "已订 URL 未进 subscribe"
    )
    assert ("move_to_new_category", "feed/51", "技术") in calls, "新订阅按导出分类归位"
    assert ("move_to_new_category", "feed/1", "技术") in calls, "已有订阅继承目录"

    # 台账可回看
    batches = client.get("/api/v1/new201/takeover/batches").json()
    assert len(batches["items"]) == 1
    assert batches["items"][0]["label"] == "从旧实例接管"
    assert batches["items"][0]["summary"]["created"] == 1

    # 纯函数负向契约：同一 URL 再 apply → skipped_existing（跨批不重复）
    again = client.post(
        "/api/v1/new201/takeover/apply",
        json={"items": [{"action": "subscribe", "feedUrl": "https://new-a.example/feed"}]},
    )
    assert again.json()["skippedExisting"] == 1
    assert again.json()["created"] == 0

    # 校验错误：未知动作 422；空 items 422；坏 move 目标 → failed 项
    bad_action = client.post(
        "/api/v1/new201/takeover/apply",
        json={"items": [{"action": "delete", "feedUrl": "https://x.example/f"}]},
    )
    assert bad_action.status_code == 422
    move_missing = client.post(
        "/api/v1/new201/takeover/apply",
        json={"items": [{"action": "move", "feedUrl": "https://gone.example/f"}]},
    ).json()
    assert move_missing["failed"] == 1
    assert move_missing["results"][0]["outcome"] == "failed"


def test_new201_plan_pure_dedupe():
    parsed = ParsedOpml(
        entries=[
            OpmlEntry(title="A", feed_url="https://x.example/feed/"),
            OpmlEntry(title="B", feed_url="https://X.EXAMPLE/feed"),
        ]
    )
    plan = build_plan(parsed, [])
    assert len(plan["toSubscribe"]) == 1, "导出内同源归并（FIX-235 口径）"


def test_new201_per_user_isolation(make_client):
    calls: list = []
    subs: list = []
    client, _app = make_client(takeover_router.router, adapter=_adapter(subs, calls))
    bob = {"x-test-user": "bob"}
    created = client.post(
        "/api/v1/new201/takeover/apply",
        json={
            "label": "B 的接管",
            "items": [{"action": "subscribe", "feedUrl": "https://b.example/feed"}],
        },
        headers=bob,
    )
    assert created.status_code == 200
    batch_id = created.json()["batch"]["id"]

    assert client.get("/api/v1/new201/takeover/batches").json()["items"] == []
    mine = client.get("/api/v1/new201/takeover/batches", headers=bob).json()["items"]
    assert [b["id"] for b in mine] == [batch_id]


def test_new201_store_records_batches(tmp_path):
    import asyncio

    from lumirss.storage import Database
    from lumirss.user_scope import user_context

    async def _run():
        with user_context("eve"):
            store = TakeoverStore(Database(tmp_path / "control.sqlite"))
            batch = await store.record_batch(
                label="demo", summary={"created": 1, "skippedExisting": 0}
            )
            batches = await store.list_batches()
            assert [b["id"] for b in batches] == [batch["id"]]

    asyncio.run(_run())
