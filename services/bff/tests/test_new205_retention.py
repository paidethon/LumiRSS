"""NEW-205 来源保留策略预演与确认启用 —— 事实面/确认语义/负向契约。

验收问题对照：
- 谁：用户为某来源设置保留期限前先看预演；
- 入口：来源设置「保留策略」（POST /api/v1/new205/retention/dry-run）；
- 之前/之后：预演（只读）展示将保留的收藏/批注/书签与将回收的普通
  缓存；确认启用后策略落库（source_overrides.retentionDays）、立即
  裁剪本地投影（starred 恒排除）、台账留痕（含预演快照）；
- 确认语义在服务端强制：confirmed 缺席/false → 422
  confirmation_required（不信任客户端流程）；
- 负向契约：全路径零上游调用（零调用间谍）；收藏/批注/书签不进任何
  删除路径（裁剪后仍在）；
- A/B 隔离：B 的预演/启用对 A 不可见（per-user 库）。
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lumirss.routers import new205_retention as retention_router
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


def _spy_adapter():
    def _boom(*args, **kwargs):
        raise AssertionError("保留策略全路径零上游调用")

    return SimpleNamespace(
        list_subscriptions=_boom,
        subscribe=_boom,
        unsubscribe=_boom,
        move_category=_boom,
        move_to_new_category=_boom,
    )


def _seed(app):
    import asyncio

    from lumirss.user_scope import user_context

    async def _run():
        with user_context("owner"):
            db = app.state.db
            await db.migrate()
            rows = [
                # (item_id, ref, published_at, starred) —— 旧普通缓存 x2、
                # 旧收藏 x1、新普通缓存 x1
                ("i1", "e1.old-a", "2025-01-01T00:00:00Z", 0),
                ("i2", "e1.old-b", "2025-02-01T00:00:00Z", 0),
                ("i3", "e1.old-starred", "2025-03-01T00:00:00Z", 1),
                ("i4", "e1.new", "2026-09-28T00:00:00Z", 0),
            ]
            for item_id, ref, published_at, starred in rows:
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url,"
                    " feed_title, title, author, url, content_text, published_at,"
                    " read, starred, fetched_at)"
                    " VALUES (?, ?, ?, '', ?, '', '', '', ?, 0, ?, 0)",
                    (item_id, ref, FEED, f"t-{ref}", published_at, starred),
                )
            # 旧普通缓存条目上的批注（保留）+ 书签（保留）
            await db.execute(
                "INSERT INTO annotations (id, entry_ref, anchor_json, anchor_hash,"
                " excerpt, note) VALUES ('a1', 'e1.old-a', '{\"p\":1}', 'h1',"
                " '关键句', '重点')"
            )
            await db.execute(
                "INSERT INTO library_items (uuid, kind, created_at)"
                " VALUES ('lb1', 'bookmark', '2026-01-01T00:00:00Z')"
            )
            await db.execute(
                "INSERT INTO library_bookmarks (item_uuid, item_type,"
                " rss_item_ref, title, created_at)"
                " VALUES ('lb1', 'rss', 'e1.old-b', '旧文乙',"
                " '2026-01-01T00:00:00Z')"
            )

    asyncio.run(_run())


def test_new205_dry_run_counts(make_client):
    client, app = make_client(retention_router.router, adapter=_spy_adapter())
    _seed(app)
    result = client.post(
        "/api/v1/new205/retention/dry-run", json={"feedUrl": FEED, "days": 180}
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["basis"] == "projection"
    assert body["reclaimed"]["prunableEntries"] == 2, "旧普通缓存将回收"
    assert body["preserved"]["starredEntries"] == 1, "收藏恒保留（无论多旧）"
    assert body["preserved"]["annotations"] == 1, "批注不进删除路径"
    assert body["preserved"]["libraryBookmarks"] == 1, "书签不进删除路径"
    assert "原生界面" in body["note"]

    # 越界天数 → 422 稳定信封
    bad = client.post(
        "/api/v1/new205/retention/dry-run", json={"feedUrl": FEED, "days": 3}
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "invalid_retention_days"


def test_new205_enable_requires_confirm_and_audits(make_client):
    client, app = make_client(retention_router.router, adapter=_spy_adapter())
    _seed(app)
    unconfirmed = client.post(
        "/api/v1/new205/retention/enable",
        json={"feedUrl": FEED, "days": 180, "confirmed": False},
    )
    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["error"]["type"] == "confirmation_required"

    enabled = client.post(
        "/api/v1/new205/retention/enable",
        json={"feedUrl": FEED, "days": 180, "confirmed": True},
    )
    assert enabled.status_code == 200, enabled.text
    body = enabled.json()
    assert body["enabled"] is True
    assert body["pruned"] == 2, "立即裁剪：旧普通缓存从投影回收"
    assert body["dryRun"]["preserved"]["starredEntries"] == 1

    # 策略本体已落库（N038 单一真源）+ 台账含预演快照
    import asyncio
    import json as _json

    from lumirss.source_overrides import SourceOverrideStore
    from lumirss.user_scope import user_context

    async def _check():
        with user_context("owner"):
            db = app.state.db
            override = await SourceOverrideStore(db).get_override(FEED)
            row = await db.fetch_one(
                "SELECT feed_url, days, dry_run_json FROM new205_retention_enables"
                " ORDER BY enabled_at DESC LIMIT 1"
            )
            kept = await db.fetch_one(
                "SELECT COUNT(*) AS n FROM search_entries WHERE feed_url = ?",
                (FEED,),
            )
            annotations = await db.fetch_one(
                "SELECT COUNT(*) AS n FROM annotations"
            )
            bookmarks = await db.fetch_one(
                "SELECT COUNT(*) AS n FROM library_bookmarks"
            )
            return override, row, int(kept["n"]), int(annotations["n"]), int(bookmarks["n"])

    override, audit, kept, annotations, bookmarks = asyncio.run(_check())
    assert override is not None and int(override["retentionDays"]) == 180
    assert audit is not None and audit["feed_url"] == FEED
    snapshot = _json.loads(audit["dry_run_json"])
    assert snapshot["reclaimed"]["prunableEntries"] == 2
    assert kept == 2, "收藏 + 新缓存保留"
    assert annotations == 1 and bookmarks == 1, "批注/书签永不删除"


def test_new205_per_user_isolation(make_client):
    client, app = make_client(retention_router.router, adapter=_spy_adapter())
    _seed(app)
    bob = {"x-test-user": "bob"}
    enabled = client.post(
        "/api/v1/new205/retention/enable",
        json={"feedUrl": FEED, "days": 30, "confirmed": True},
        headers=bob,
    )
    assert enabled.status_code == 200
    # B 的预演基于 B 自己的空投影（不看到 A 的种子数据）
    preview = client.post(
        "/api/v1/new205/retention/dry-run",
        json={"feedUrl": FEED, "days": 30},
        headers=bob,
    ).json()
    assert preview["totalEntries"] == 0
    assert preview["preserved"] == {
        "starredEntries": 0,
        "annotations": 0,
        "libraryBookmarks": 0,
    }
    owner_preview = client.post(
        "/api/v1/new205/retention/dry-run", json={"feedUrl": FEED, "days": 30}
    ).json()
    assert owner_preview["totalEntries"] == 4
