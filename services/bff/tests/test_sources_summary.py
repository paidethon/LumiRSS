"""GET /api/v1/sources/summary — 来源中心按类型汇总（R02）。

覆盖：
- 八类（+ rsshub 共九类）齐全，顺序与前端 nav-registry 的
  sourceTypeSourceOrder 一致；
- 计数口径：rss=search_feeds 订阅投影、api_source=配置表、
  bookmark/clip/snapshot=per-user 库真实行数、inbox=条目数；
- 「服务未配置」与「集合为空」严格区分（not_configured ≠ empty）；
- newsletter/obsidian 给连接状态而非伪计数（count=None）；
- per-user 隔离：两个账户互不可见对方的书签 / API 来源 / 收件连接器；
- 零上游调用：所有种子都不触 FreshRSS/RSSHub 网络。
"""

import asyncio

import pytest

from lumirss.library_clips import ClipStore


@pytest.fixture()
def db(client):
    return client.app.state.db


def run(coroutine):
    return asyncio.run(coroutine)


def _seed_rss_feeds(db, feeds: list[str], published_at: str = "2026-09-20T08:00:00Z"):
    """落订阅投影 search_feeds + 一条 search_entries（最近活动口径）。"""

    async def _seed():
        await db.migrate()
        for i, feed_url in enumerate(feeds):
            await db.execute(
                "INSERT OR IGNORE INTO search_feeds (feed_url, feed_title, category_id, refreshed_at) VALUES (?, ?, NULL, 0)",
                (feed_url, f"源{i}"),
            )
            await db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, '条目', '', 'https://u.example/x', '', ?, 0, 0, 0)",
                (f"seed-{i}", f"seed-ref-{i}", feed_url, f"源{i}", published_at),
            )

    run(_seed())


def _seed_clip(db):
    """ClipStore 直建（不走 /library/clips 路由——那条路会真取网页）。"""

    async def _seed():
        await ClipStore(db).create_clip(
            url="https://example.com/clip",
            title="剪藏页",
            content_html="<p>hi</p>",
            content_text="hi",
        )

    run(_seed())


def _seed_snapshot(db):
    """library_assets 直插一行（save_snapshot 的落库形态，跳过文件 IO）。"""

    async def _seed():
        await db.migrate()
        await db.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'snapshot', '2026-09-22T00:00:00Z')",
            ("snap-uuid-1",),
        )
        await db.execute(
            "INSERT INTO library_assets (uuid, item_uuid, path, bytes, sha256, mime, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("snap-uuid-1", "snap-uuid-1", "snap-uuid-1.html", 16, "deadbeef", "text/html", "https://example.com/a", "2026-09-22T00:00:00Z"),
        )

    run(_seed())


def _create_api_source(client) -> None:
    resp = client.post(
        "/api/v1/api-sources",
        json={
            "name": "GitHub releases",
            "endpoint": "https://api.example.com/repos/x/y/releases",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name", "url": "html_url"},
            # subscribe=false：hermetic 环境无 FreshRSS，自动订阅会落
            # last_error（subscribe_failed），与「配置健康」的断言无关。
            "subscribe": False,
        },
    )
    assert resp.status_code in (200, 201), resp.text


def _summary_types(client, **kwargs):
    resp = client.get("/api/v1/sources/summary", **kwargs)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {item["type"]: item for item in body["items"]}


# ---------------------------------------------------------------------------
# 九类齐全 + 计数口径
# ---------------------------------------------------------------------------


def test_summary_covers_all_nine_types_in_registry_order(client):
    types = list(_summary_types(client))
    # 与前端 nav-registry.sourceTypeSourceOrder() 完全同序
    assert types == [
        "rss",
        "rsshub",
        "api_source",
        "newsletter",
        "inbox",
        "obsidian",
        "bookmark",
        "clip",
        "snapshot",
    ]


def test_summary_counts_and_status_per_type(client, db, monkeypatch):
    monkeypatch.setenv("RSSHUB_BASE_URL", "https://rsshub.example")
    _seed_rss_feeds(
        db,
        [
            "https://blog.example/rss",
            "https://rsshub.example/bilibili/user/x",
        ],
        published_at="2026-09-20T08:00:00Z",
    )
    _create_api_source(client)
    client.post("/api/v1/mail/bridge-lists", json={"name": "周报桥"})
    client.post("/api/v1/inbox/sources", json={"name": "推送脚本"})
    resp = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://seed.example/b1", "title": "书签一"},
    )
    assert resp.status_code == 201, resp.text
    _seed_clip(db)
    _seed_snapshot(db)

    by_type = _summary_types(client)

    # rss：订阅投影计数 = 2；最近活动来自 search_entries 投影
    rss = by_type["rss"]
    assert rss["count"] == 2
    assert rss["status"] == "ok"
    assert rss["lastActivityAt"] == "2026-09-20T08:00:00Z"

    # rsshub：base 已配置，指向该 base 的订阅 = 1
    rsshub = by_type["rsshub"]
    assert rsshub["count"] == 1
    assert rsshub["status"] == "ok"

    # api_source：配置表计数 = 1
    api = by_type["api_source"]
    assert api["count"] == 1
    assert api["status"] == "ok"

    # newsletter：连接状态（有桥列表 = ok），count=None 不伪计数
    newsletter = by_type["newsletter"]
    assert newsletter["count"] is None
    assert newsletter["status"] == "ok"

    # inbox：连接器已建（ok），条目集合为 0 是诚实 0
    inbox = by_type["inbox"]
    assert inbox["count"] == 0
    assert inbox["status"] == "ok"

    # obsidian：未配置 vault → not_configured，count=None
    obsidian = by_type["obsidian"]
    assert obsidian["status"] == "not_configured"
    assert obsidian["count"] is None

    # bookmark / clip / snapshot：真实计数 + 集合非空 = ok
    assert by_type["bookmark"]["count"] == 1
    assert by_type["bookmark"]["status"] == "ok"
    assert by_type["clip"]["count"] == 1
    assert by_type["clip"]["status"] == "ok"
    assert by_type["snapshot"]["count"] == 1
    assert by_type["snapshot"]["status"] == "ok"


def test_summary_distinguishes_not_configured_vs_empty(client, monkeypatch):
    monkeypatch.setenv("RSSHUB_BASE_URL", "https://rsshub.example")
    by_type = _summary_types(client)

    # 全新账户：rss 零订阅 = 服务未配置（不是「集合为空」）
    assert by_type["rss"]["status"] == "not_configured"
    # rsshub base 已配置但没有任何路由订阅 = 集合为空
    assert by_type["rsshub"]["status"] == "empty"
    assert by_type["rsshub"]["count"] == 0
    # api_source 无任何配置 = 服务未配置
    assert by_type["api_source"]["status"] == "not_configured"
    # newsletter 无桥列表 = 未配置
    assert by_type["newsletter"]["status"] == "not_configured"
    # inbox 无连接器 = 未配置（推送来源没有入口 ≠ 空集合）
    assert by_type["inbox"]["status"] == "not_configured"
    # bookmark / clip / snapshot 集合可用但没内容 = empty
    assert by_type["bookmark"]["status"] == "empty"
    assert by_type["bookmark"]["count"] == 0
    assert by_type["clip"]["status"] == "empty"
    assert by_type["snapshot"]["status"] == "empty"


def test_summary_rsshub_not_configured_without_base(client, monkeypatch):
    monkeypatch.setenv("RSSHUB_BASE_URL", "")
    rsshub = _summary_types(client)["rsshub"]
    assert rsshub["status"] == "not_configured"
    assert rsshub["count"] is None  # 未配置绝不冒充 0


def test_summary_obsidian_configured_reports_note_count(client, db, monkeypatch, tmp_path):
    # conftest 把 app.state.db 换成 plain Database，但 lifespan 在换库前
    # 构建的 obsidian_service 仍绑 RoutingDatabase（owner 用户库）——与其
    # 隔离打架。用同库测试替身替换 router 内解析函数，保证种子可见。
    import lumirss.routers.sources as sources_routes
    from lumirss.obsidian import ObsidianService

    monkeypatch.setattr(
        sources_routes,
        "_get_obsidian_service",
        lambda request: ObsidianService(db, env_root=""),
    )
    run(_seed_obsidian_vault(db, str(tmp_path / "vault")))
    obsidian = _summary_types(client)["obsidian"]
    assert obsidian["status"] == "ok"
    assert obsidian["count"] == 2
    assert obsidian["lastActivityAt"] == "2026-09-23T00:00:00Z"


async def _seed_obsidian_vault(db, vault_root: str):
    await db.migrate()
    await db.execute(
        f"UPDATE obsidian_settings SET vault_path = '{vault_root}', last_scan_at = '2026-09-23T00:00:00Z', last_error = NULL WHERE id = 1"
    )
    for i in range(2):
        await db.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'snapshot', '2026-09-23T00:00:00Z')",
            (f"obs-note-{i}",),
        )
        await db.execute(
            "INSERT INTO obsidian_notes (item_uuid, rel_path, fingerprint, content_hash, title, indexed_at) VALUES (?, ?, ?, ?, ?, '2026-09-23T00:00:00Z')",
            (f"obs-note-{i}", f"note-{i}.md", f"fp-{i}", f"hash-{i}", f"笔记{i}"),
        )


def test_summary_api_source_error_bubbles_to_status_and_detail(client, db):
    run(_seed_api_source_with_error(db))
    api = _summary_types(client)["api_source"]
    assert api["status"] == "error"
    assert api["detail"] == "上游超时"
    assert api["count"] == 1


async def _seed_api_source_with_error(db):
    await db.migrate()
    await db.execute(
        "INSERT INTO api_sources (uuid, name, endpoint, items_expr, field_map, enabled, secret, last_error, created_at) VALUES (?, ?, ?, ?, ?, 1, ?, '上游超时', '2026-09-01T00:00:00Z')",
        ("api-uuid-1", "坏源", "https://api.example.com/x", "[*]", "{}", "s3cret"),
    )


# ---------------------------------------------------------------------------
# per-user 隔离：两个账户互不可见
# ---------------------------------------------------------------------------


def test_summary_per_user_isolation(monkeypatch, tmp_path):
    """成员的书签 / API 来源 / 收件连接器不出现在 owner 的汇总里，反之亦然。"""
    from new21x_isolation import build_two_user_client, isolated_auth_env

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        # member：1 书签 + 1 API 来源 + 1 收件连接器（全走自己的会话）
        resp = client.post(
            "/api/v1/library/bookmarks",
            json={"url": "https://seed.example/m1", "title": "成员书签"},
            headers=member,
        )
        assert resp.status_code == 201, resp.text
        assert (
            client.post(
                "/api/v1/api-sources",
                json={
                    "name": "成员源",
                    "endpoint": "https://api.example.com/m",
                    "itemsExpr": "[*]",
                    "fieldMap": {"id": "id", "title": "name"},
                    "subscribe": False,
                },
                headers=member,
            ).status_code
            in (200, 201)
        )
        assert (
            client.post(
                "/api/v1/inbox/sources",
                json={"name": "成员连接器"},
                headers=member,
            ).status_code
            == 200
        )

        member_view = _summary_types(client, headers=member)
        owner_view = _summary_types(client, headers=owner)

        assert member_view["bookmark"]["count"] == 1
        assert member_view["api_source"]["count"] == 1
        assert member_view["inbox"]["status"] == "ok"

        # owner：零书签（empty ≠ member 的 ok）、零 API 来源（not_configured）、
        # 无收件连接器（not_configured ≠ member 的 ok）
        assert owner_view["bookmark"]["count"] == 0
        assert owner_view["bookmark"]["status"] == "empty"
        assert owner_view["api_source"]["count"] == 0
        assert owner_view["api_source"]["status"] == "not_configured"
        assert owner_view["inbox"]["status"] == "not_configured"
