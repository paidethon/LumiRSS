"""FIX-237 — 订阅删除→重建：新订阅代次不继承已删除对象的私有状态。

两个真实缺陷（同一条 delete 流程）：

1. keep_artifacts=false 的显式清理在**退订成功之后**才向上游解析
   feed_url——生产语义下订阅已从 subscription/list 消失，解析恒空，
   purge 拿到空 URL、一条也删不掉（测试假适配器不摘除订阅，掩盖了
   时序）。契约：解析先于破坏性写。
2. 检查代次私有状态（source_refresh_log 检查历史 + feed_recovery 恢复
   窗口）在退订后原样留存——同 URL 重新订阅即“新代次”，却继承上一代
   的失败史/断更恢复窗（状态页显示从未发生过的 pending）。契约：
   退订成功即 generation-clean 该 feed 的检查侧状态（备注级联已有
   先例；用户手工配置的覆盖/屏蔽规则按 URL 有意保留，不在代次内）。
"""

import asyncio
from types import SimpleNamespace

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.refresh_log import SourceRefreshLogStore
from lumirss.subscriptionref import encode_subscription_ref

FEED_URL = "https://feed.example.com/rss"
STREAM_ID = "feed/42"
REF = encode_subscription_ref(STREAM_ID)
ENTRY_REF = encode_entry_ref("e1.fix237")


def run(coroutine):
    return asyncio.run(coroutine)


def _install_control(*, drop_on_unsubscribe: bool):
    """生产时序忠实的假适配器：退订后 subscription/list 不再含该订阅。"""
    subs = [
        SimpleNamespace(
            stream_id=STREAM_ID,
            feed_url=FEED_URL,
            title="示例源",
            subscription_ref=REF,
            category_id=None,
            category_label=None,
        )
    ]

    async def _list_subs():
        return list(subs)

    async def _unsubscribe(stream_id):
        assert stream_id == STREAM_ID
        if drop_on_unsubscribe:
            subs.clear()

    app.state.freshrss_control_adapter = SimpleNamespace(
        list_subscriptions=_list_subs, unsubscribe=_unsubscribe
    )


async def _seed_projection_row():
    db = app.state.db
    await db.migrate()
    await db.execute(
        "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1.fix237", ENTRY_REF, FEED_URL, "源", "标题", "", "", "正文", "2026-09-20T00:00:00Z", 0, 0, 1789660000),
    )
    # 一条工作区引用 + 一条批注：keep_artifacts=false 的 purge 计数来源。
    await db.execute(
        "INSERT INTO workspaces (id, name, position, created_at) VALUES (?, ?, 0, ?)",
        ("ws-fix237", "工作区", "2026-09-20T00:00:00Z"),
    )
    await db.execute(
        "INSERT INTO workspace_items (workspace_id, item_ref, position, added_at) VALUES (?, ?, 0, ?)",
        ("ws-fix237", f"rss:{ENTRY_REF}", "2026-09-20T00:00:00Z"),
    )
    await db.execute(
        "INSERT INTO annotations (id, entry_ref, anchor_json, anchor_hash, excerpt, note, color, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("ann-fix237", ENTRY_REF, "{}", "hash-fix237", "摘录", "批注", "yellow", "2026-09-20T00:00:00Z", "2026-09-20T00:00:00Z"),
    )


async def _seed_stale_check_generation():
    """上一代检查状态：一条 error 历史 + error→ok 跳变产生的恢复窗口。"""
    store = SourceRefreshLogStore(app.state.db)
    await store.record(FEED_URL, "error", entry_count=0)
    recovery = await store.record(FEED_URL, "ok", entry_count=3)
    assert recovery is not None, "前置：error→ok 跳变应产生恢复窗口"


def test_delete_resolves_feed_url_before_upstream_write(client):
    """keep_artifacts=false：解析先于退订——生产时序（退订后订阅从
    list 消失）下显式清理仍按真实 feed_url 生效。"""
    run(_seed_projection_row())
    _install_control(drop_on_unsubscribe=True)

    response = client.delete(f"/api/v1/subscriptions/{REF}?keep_artifacts=false")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["purged"]["workspaceItems"] == 1, (
        f"生产时序下 purge 不得拿到空 feed_url：{body['purged']}"
    )
    assert body["purged"]["annotations"] == 1


def test_delete_generation_cleans_refresh_check_state(client):
    """退订成功 → 该 feed 的检查历史与恢复窗口整体清除；重建的同 URL
    订阅是干净的新代次（状态页如实呈现“从未检查过”）。"""
    run(_seed_projection_row())
    run(_seed_stale_check_generation())
    _install_control(drop_on_unsubscribe=True)

    response = client.delete(f"/api/v1/subscriptions/{REF}")
    assert response.status_code == 204

    store = SourceRefreshLogStore(app.state.db)
    snapshot = run(store.status_snapshot())
    assert all(feed["feedUrl"] != FEED_URL for feed in snapshot["feeds"]), (
        "新代次不得继承上一代的检查历史"
    )
    recoveries = run(store.recoveries())
    assert all(recovery["feedUrl"] != FEED_URL for recovery in recoveries), (
        "恢复窗口（含已消费）属于上一代，一并清除"
    )


def test_delete_without_upstream_listing_still_unsubscribes(client):
    """上游 list 失败（网络退化）不阻断退订本身；代次清理在拿不到
    feed 身份时诚实跳过（best-effort 边界）。"""

    class _ListBroken:
        async def list_subscriptions(self):
            raise RuntimeError("upstream degraded")

        async def unsubscribe(self, stream_id):
            assert stream_id == STREAM_ID

    app.state.freshrss_control_adapter = _ListBroken()
    response = client.delete(f"/api/v1/subscriptions/{REF}")
    assert response.status_code == 204
