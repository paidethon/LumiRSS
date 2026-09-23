"""N012 退订影响预览 + keep_artifacts 显式语义。

- 预览只读：200 + 计数/样本正确 + 预览前后数据库逐维度不变；
- keep_artifacts=true：退订后工作区引用/看板状态/批注保留；保留的
  引用经既有 stale-ref 机制解析为 stale 卡片（内容缺失不 500）；
- keep_artifacts=false：批注 + 工作区引用/看板状态显式清理；
- 缺省（无参数）：既有 legacy 行为原样保留（仅备注级联）；
- library 书签在任何分支都不删。
"""

import asyncio
from types import SimpleNamespace

from lumirss.adapters.freshrss import EntryNotFound
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.subscriptionref import encode_subscription_ref

FEED_URL = "https://feed.example.com/rss"
STREAM_ID = "feed/42"
REF = encode_subscription_ref(STREAM_ID)
ENTRY_REF = encode_entry_ref("e1.n012")


def run(coroutine):
    return asyncio.run(coroutine)


async def _seed_artifacts():
    """一条投影条目 + 全套牵连工件（批注/工作区/看板状态/书签/备注）。"""
    db = app.state.db
    await db.migrate()
    await db.execute(
        "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1.n012", ENTRY_REF, FEED_URL, "源", "标题", "", "", "正文", "2026-09-20T00:00:00Z", 0, 0, 1789660000),
    )
    await db.execute(
        "INSERT INTO annotations (id, entry_ref, anchor_json, anchor_hash, excerpt, note, color, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("ann-1", ENTRY_REF, "{}", "hash-n012", "摘录", "批注", "yellow", "2026-09-20T00:00:00Z", "2026-09-20T00:00:00Z"),
    )
    await db.execute(
        "INSERT INTO workspaces (id, name, position, created_at) VALUES (?, ?, 0, ?)",
        ("ws-n012", "工作区", "2026-09-20T00:00:00Z"),
    )
    await db.execute(
        "INSERT INTO workspace_items (workspace_id, item_ref, position, added_at) VALUES (?, ?, 0, ?)",
        ("ws-n012", f"rss:{ENTRY_REF}", "2026-09-20T00:00:00Z"),
    )
    await db.execute(
        "INSERT INTO workspace_item_status (workspace_id, item_ref, status, updated_at) VALUES (?, ?, 'reading', ?)",
        ("ws-n012", f"rss:{ENTRY_REF}", "2026-09-20T00:00:00Z"),
    )
    await db.execute(
        "INSERT INTO library_items (uuid, kind, created_at) VALUES ('bm-n012-uuid', 'bookmark', '2026-09-20T00:00:00Z')",
        (),
    )
    await db.execute(
        "INSERT INTO library_bookmarks (item_uuid, item_type, url, rss_item_ref, title, note, created_at) VALUES ('bm-n012-uuid', 'rss', NULL, ?, '书签', '', '2026-09-20T00:00:00Z')",
        (f"rss:{ENTRY_REF}",),
    )
    from lumirss.source_notes import SourceNotesStore

    await SourceNotesStore(db).update_notes(REF, note="备注")


def _counts():
    async def _one(sql: str) -> int:
        row = await app.state.db.fetch_one(sql)
        return int(row["n"])

    async def _all():
        await app.state.db.migrate()
        return {
            "entries": await _one("SELECT COUNT(*) AS n FROM search_entries"),
            "annotations": await _one("SELECT COUNT(*) AS n FROM annotations"),
            "workspace_items": await _one("SELECT COUNT(*) AS n FROM workspace_items"),
            "board_status": await _one("SELECT COUNT(*) AS n FROM workspace_item_status"),
            "bookmarks": await _one("SELECT COUNT(*) AS n FROM library_bookmarks"),
            "source_notes": await _one("SELECT COUNT(*) AS n FROM source_notes"),
        }

    return run(_all())


def _install_control(unsubscribe_calls: list | None = None):
    async def _list_subs():
        return [
            SimpleNamespace(
                stream_id=STREAM_ID,
                feed_url=FEED_URL,
                title="示例源",
                subscription_ref=REF,
                category_id=None,
                category_label=None,
            )
        ]

    async def _unsubscribe(stream_id):
        if unsubscribe_calls is not None:
            unsubscribe_calls.append(stream_id)

    app.state.freshrss_control_adapter = SimpleNamespace(
        list_subscriptions=_list_subs, unsubscribe=_unsubscribe
    )


def test_n012_preview_readonly_counts(client):
    run(_seed_artifacts())
    _install_control()
    before = _counts()

    response = client.get(f"/api/v1/subscriptions/{REF}/unsubscribe-preview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["feedUrl"] == FEED_URL
    assert body["unreadCount"] == 1
    assert body["annotations"]["count"] == 1
    assert body["annotations"]["items"][0]["entryRef"] == ENTRY_REF
    assert body["workspaceItems"]["count"] == 1
    assert body["workspaceItems"]["items"][0]["workspaceId"] == "ws-n012"
    assert body["boardItems"]["count"] == 1
    assert body["libraryItems"]["count"] == 1
    assert body["inboxRules"]["count"] == 0

    after = _counts()
    assert before == after, "预览必须零写入（数据库逐维度不变）"


def test_n012_preview_invalid_ref_and_unknown_subscription(client):
    run(_seed_artifacts())
    _install_control()
    bad = client.get("/api/v1/subscriptions/not-a-ref/unsubscribe-preview")
    assert bad.status_code == 400
    assert bad.json()["error"]["type"] == "invalid_subscription_ref"

    async def _empty():
        return []

    app.state.freshrss_control_adapter = SimpleNamespace(list_subscriptions=_empty)
    missing = client.get(f"/api/v1/subscriptions/{REF}/unsubscribe-preview")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "subscription_not_found"


def test_n012_delete_keep_artifacts_true_retains(client):
    run(_seed_artifacts())
    calls: list = []
    _install_control(calls)
    before = _counts()

    response = client.delete(f"/api/v1/subscriptions/{REF}?keep_artifacts=true")
    assert response.status_code == 204, response.text
    assert calls == [STREAM_ID]

    after = _counts()
    assert after["annotations"] == before["annotations"] == 1
    assert after["workspace_items"] == before["workspace_items"] == 1
    assert after["board_status"] == before["board_status"] == 1
    assert after["bookmarks"] == before["bookmarks"] == 1
    assert after["source_notes"] == 0, "备注沿用既有级联（所有分支一致）"

    # 保留的引用经既有 stale-ref 机制优雅降级：退订后投影同步移除条目
    # 且上游 404 → stale=True / not_found，绝不 500。
    async def _get_entry(item_id):
        raise EntryNotFound("gone")

    app.state.freshrss_adapter = SimpleNamespace(get_entry=_get_entry)

    async def _drop_projection():
        await app.state.db.migrate()
        await app.state.db.execute(
            "DELETE FROM search_entries WHERE feed_url = ?",
            (FEED_URL,),
        )

    run(_drop_projection())
    resolved = client.post("/api/v1/resolve", json={"refs": [f"rss:{ENTRY_REF}"]})
    assert resolved.status_code == 200, resolved.text
    item = resolved.json()["items"][0]
    assert item["stale"] is True
    assert item["staleReason"] == "not_found"


def test_n012_delete_explicit_false_cleans(client):
    run(_seed_artifacts())
    _install_control()

    response = client.delete(f"/api/v1/subscriptions/{REF}?keep_artifacts=false")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["purged"]["annotations"] == 1
    assert body["purged"]["workspaceItems"] == 1
    assert body["purged"]["boardItems"] == 1
    counts = _counts()
    assert counts["annotations"] == 0
    assert counts["workspace_items"] == 0
    assert counts["board_status"] == 0
    assert counts["bookmarks"] == 1, "library 书签不在清理路径"


def test_n012_delete_default_preserves_legacy(client):
    run(_seed_artifacts())
    calls: list = []
    _install_control(calls)
    before = _counts()

    response = client.delete(f"/api/v1/subscriptions/{REF}")
    assert response.status_code == 204
    assert calls == [STREAM_ID]

    after = _counts()
    # legacy：只级联备注；批注/工作区引用/看板状态/书签维持原状。
    assert after["source_notes"] == 0
    assert after["annotations"] == before["annotations"] == 1
    assert after["workspace_items"] == before["workspace_items"] == 1
    assert after["board_status"] == before["board_status"] == 1
    assert after["bookmarks"] == before["bookmarks"] == 1
