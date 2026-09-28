"""NEW-203 来源分流视图 —— CRUD / 读取侧过滤 / LIKE 转义 / 负向契约。

验收问题对照：
- 谁：用户给同一个已订阅 feed 建多个命名视图（列/关键词包含）；
- 入口：订阅详情「分流视图」（POST /api/v1/new203/views）；
- 之前/之后：创建前该 feed 只有一个时间线；创建后可按视图过滤出
  子集（title/author 口径），feed 本身与抓取任务不变；
- 核心负向契约：分流是读取侧投影过滤——零 FreshRSS/上游调用（测试
  断言 control adapter 全程未被触碰），不复制条目、不改条目身份；
- 失败/恢复：同 feed 同名 409；未知字段/超长 422（含 % _ 字面匹配）；
  删除视图后视图行消失（投影/条目不受影响）；
- A/B 隔离：B 的视图 A 不可见。

种子直接写投影表（迁移 0006 的 search_entries）。
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lumirss.new203_views import escape_like
from lumirss.routers import new203_views as views_router
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
    """零调用间谍：任何属性被调用即测试失败（负向契约）。"""

    def _boom(*args, **kwargs):
        raise AssertionError("分流视图绝不触碰 FreshRSS/上游适配器")

    return SimpleNamespace(
        list_subscriptions=_boom,
        subscribe=_boom,
        unsubscribe=_boom,
        move_category=_boom,
        move_to_new_category=_boom,
    )


def _seed(app, feed_url, rows):
    """rows: (title, author, published_at, content_text)。"""
    import asyncio

    from lumirss.user_scope import user_context

    async def _run():
        with user_context("owner"):
            db = app.state.db
            await db.migrate()
            for index, (title, author, published_at, content) in enumerate(rows):
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url,"
                    " feed_title, title, author, url, content_text, published_at,"
                    " read, starred, fetched_at)"
                    " VALUES (?, ?, ?, '', ?, ?, '', ?, ?, 0, 0, 0)",
                    (
                        f"{feed_url}#item-{index}",
                        f"e1.{feed_url}.{index}",
                        feed_url,
                        title,
                        author,
                        content,
                        published_at,
                    ),
                )

    asyncio.run(_run())


def test_new203_view_crud_and_entries(make_client):
    client, app = make_client(views_router.router, adapter=_spy_adapter())
    _seed(app, FEED, [
        ("Rust 1.75 发布", "dev-team", "2026-09-01T00:00:00Z", "语言更新内容"),
        ("Python 3.13 发布", "dev-team", "2026-09-02T00:00:00Z", "解释器更新"),
        ("周报：社区动态", "editor", "2026-09-03T00:00:00Z", "本周 Rust 生态"),
    ])

    created = client.post(
        "/api/v1/new203/views",
        json={"feedUrl": FEED, "name": "Rust 视图", "field": "title", "value": "rust"},
    )
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["field"] == "title"

    # 同 feed 第二个视图（按作者）——同一来源多个视图并存
    author_view = client.post(
        "/api/v1/new203/views",
        json={"feedUrl": FEED, "name": "编辑署名", "field": "author", "value": "editor"},
    ).json()

    entries = client.get(f"/api/v1/new203/views/{view['id']}/entries").json()
    assert entries["basis"] == "projection"
    assert [e["entryRef"] for e in entries["entries"]] == [f"e1.{FEED}.0"]

    author_entries = client.get(
        f"/api/v1/new203/views/{author_view['id']}/entries"
    ).json()
    assert [e["entryRef"] for e in author_entries["entries"]] == [f"e1.{FEED}.2"]

    # 同名冲突 409；坏字段 422；未知视图 404
    duplicate = client.post(
        "/api/v1/new203/views",
        json={"feedUrl": FEED, "name": "Rust 视图", "field": "title", "value": "x"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["type"] == "source_view_exists"
    bad_field = client.post(
        "/api/v1/new203/views",
        json={"feedUrl": FEED, "name": "正则视图", "field": "regex", "value": "x"},
    )
    assert bad_field.status_code == 422
    missing = client.get("/api/v1/new203/views/nope/entries")
    assert missing.status_code == 404

    # PATCH 重命名 + DELETE
    patched = client.patch(
        f"/api/v1/new203/views/{view['id']}", json={"name": "Rust 月报"}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Rust 月报"
    deleted = client.delete(f"/api/v1/new203/views/{author_view['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/new203/views").json()["items"] != []
    assert (
        client.get(f"/api/v1/new203/views/{author_view['id']}/entries").status_code
        == 404
    )


def test_new203_like_escaping_and_content_field(make_client):
    client, app = make_client(views_router.router, adapter=_spy_adapter())
    _seed(app, FEED, [
        ("打折 100% 正品", "shop", "2026-09-01T00:00:00Z", "全场 5 折起"),
        ("普通文章", "shop", "2026-09-02T00:00:00Z", "提到 100_倍效率"),
    ])
    view = client.post(
        "/api/v1/new203/views",
        json={"feedUrl": FEED, "name": "标题含百分号", "field": "title", "value": "100%"},
    ).json()
    entries = client.get(f"/api/v1/new203/views/{view['id']}/entries").json()
    # % 按字面匹配：只命中标题字面含 "100%" 的那行（不是所有行）
    assert [e["entryRef"] for e in entries["entries"]] == [f"e1.{FEED}.0"]

    content_view = client.post(
        "/api/v1/new203/views",
        json={"feedUrl": FEED, "name": "正文含下划线", "field": "content", "value": "100_倍"},
    ).json()
    content_entries = client.get(
        f"/api/v1/new203/views/{content_view['id']}/entries"
    ).json()
    assert [e["entryRef"] for e in content_entries["entries"]] == [f"e1.{FEED}.1"]
    assert escape_like("a%b_c\\d") == "a\\%b\\_c\\\\d"


def test_new203_per_user_isolation(make_client):
    client, app = make_client(views_router.router, adapter=_spy_adapter())
    _seed(app, FEED, [("Rust 发布", "a", "2026-09-01T00:00:00Z", "正文")])
    bob = {"x-test-user": "bob"}
    created = client.post(
        "/api/v1/new203/views",
        json={"feedUrl": FEED, "name": "B 的视图", "field": "title", "value": "rust"},
        headers=bob,
    )
    assert created.status_code == 201
    view_id = created.json()["id"]

    assert client.get("/api/v1/new203/views").json()["items"] == []
    assert client.get(f"/api/v1/new203/views/{view_id}/entries").status_code == 404
    assert client.delete(f"/api/v1/new203/views/{view_id}").status_code == 404
    mine = client.get("/api/v1/new203/views", headers=bob).json()["items"]
    assert [v["id"] for v in mine] == [view_id]
