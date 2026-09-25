"""N029 路由与来源关系图 — my-sources（本人）+ admin usage（计数聚合）。

覆盖：
- 反向映射正确：由 routeKey（模板 + 脱敏参数签名）匹配本人订阅里
  由该模板生成的 feed URL；不同参数 / 不同路由 / 非 RSSHub 订阅不混入；
- 敏感参数：URL 里的真实 token 与 routeKey 里的 '***' 哨兵匹配
  （两侧都按 F047 规则掩码后比较，服务端从不触碰真实凭据）；
- 投影口径：unreadCount / recentEntries（≤5，新→旧）来自 search_entries
  派生投影；畸形 routeKey 400；
- admin usage：跨用户只有计数（userCount/sourceCount/totalEntries），
  绝无其他用户的标题 / URL / 用户名（断言响应键与 JSON 序列化整体）；
- member 403。
"""

import asyncio
import secrets as _secrets
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.rsshub import RssHubPreviewCache
from lumirss.storage import Database
from lumirss.subscriptionref import encode_subscription_ref


class _FakeControl:
    def __init__(self, urls):
        self.urls = list(urls)

    async def list_subscriptions(self):
        return [
            SimpleNamespace(
                stream_id=f"feed/{index + 1}",
                subscription_ref=encode_subscription_ref(f"feed/{index + 1}"),
                title=f"订阅 {index + 1}",
                feed_url=url,
            )
            for index, url in enumerate(self.urls)
        ]


@pytest.fixture()
def sources_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    with TestClient(app) as test_client:
        db = Database(tmp_path / "lumi.sqlite")
        app.state.db = db
        app.state.rsshub_preview_cache = RssHubPreviewCache(ttl_s=0.0)
        app.state.freshrss_control_adapter = _FakeControl(
            [
                "http://rsshub.test:1200/hackernews",
                "http://rsshub.test:1200/github/starred_repos/DIYgod?token=abc123",
                "http://rsshub.test:1200/github/starred_repos/otheruser",
                "http://rsshub.test:1200/ithome/ranking/24h",
                "https://direct.example/feed.xml",
            ]
        )
        yield test_client, db
    app.state.freshrss_control_adapter = None


def _insert_projection(db: Database, feed_url: str, entries: list[dict]):
    """向派生投影写入该来源的条目（read: 0=未读 1=已读）。"""

    async def run():
        await db.migrate()
        await db.execute(
            "INSERT OR REPLACE INTO search_feeds (feed_url, feed_title, category_id, refreshed_at) VALUES (?, ?, NULL, strftime('%s','now'))",
            (feed_url, "投影标题"),
        )
        for index, entry in enumerate(entries):
            await db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, '', '', '', ?, ?, 0, ?)",
                (
                    f"i-{feed_url}-{index}",
                    f"ref-{feed_url}-{index}",
                    feed_url,
                    "投影标题",
                    entry["title"],
                    entry["published"],
                    entry.get("read", 0),
                    1700000000 + index,
                ),
            )

    asyncio.run(run())


def test_my_sources_reverse_maps_route_key(sources_client):
    client, db = sources_client
    _insert_projection(
        db,
        "http://rsshub.test:1200/hackernews",
        [
            {"title": "第一条", "published": "2026-09-01T10:00:00Z"},
            {"title": "第二条", "published": "2026-09-02T10:00:00Z", "read": 1},
            {"title": "第三条", "published": "2026-09-03T10:00:00Z"},
        ],
    )
    response = client.get("/api/v1/rsshub/routes/hackernews/my-sources")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["routeKey"] == "hackernews"
    assert data["templateId"] == "hackernews"
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["feedUrl"] == "http://rsshub.test:1200/hackernews"
    assert item["unreadCount"] == 2
    assert [entry["title"] for entry in item["recentEntries"]] == [
        "第三条",
        "第二条",
        "第一条",
    ]
    assert set(item["recentEntries"][0]) == {"ref", "title", "published"}


def test_my_sources_param_signature_must_match(sources_client):
    client, _ = sources_client
    # URL 里真实 token=abc123 与 routeKey 哨兵 token=*** 匹配（掩码后同形）
    matched = client.get(
        "/api/v1/rsshub/routes/"
        "github-starred-repos%7Ctoken%3D%2A%2A%2A%26user%3DDIYgod/my-sources"
    )
    assert matched.status_code == 200
    assert len(matched.json()["items"]) == 1
    assert matched.json()["items"][0]["feedUrl"].endswith(
        "/github/starred_repos/DIYgod?token=abc123"
    )
    # 不同参数签名 → 不属于该路由
    other = client.get(
        "/api/v1/rsshub/routes/"
        "github-starred-repos%7Ctoken%3D%2A%2A%2A%26user%3Dnobody/my-sources"
    )
    assert other.status_code == 200
    assert other.json()["items"] == []
    # 完全不同的路由 → 空（其它订阅不混入）
    unrelated = client.get("/api/v1/rsshub/routes/v2ex-topics/my-sources")
    assert unrelated.status_code == 200
    assert unrelated.json()["items"] == []


def test_my_sources_empty_projection_is_zero_not_error(sources_client):
    client, _ = sources_client
    response = client.get("/api/v1/rsshub/routes/ithome-ranking-24h/my-sources")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["unreadCount"] == 0
    assert data["items"][0]["recentEntries"] == []


def test_my_sources_malformed_route_key_400(sources_client):
    client, _ = sources_client
    response = client.get("/api/v1/rsshub/routes/hackernews%7C%26bad/my-sources")
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "rsshub_invalid_parameters"


# ---- admin usage（session 模式：真实多用户库） --------------------------------

PASSWORD = "us-" + _secrets.token_urlsafe(9)


@pytest.fixture()
def usage_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(tmp_path)
        owner_login = client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
        )
        assert owner_login.status_code == 200, owner_login.text
        owner_headers = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = client.post(
            "/api/v1/admin/invites", json={"label": "alice"}, headers=owner_headers
        )
        activation = client.post(
            "/api/v1/auth/activate",
            json={"token": invite.json()["token"], "username": "alice", "password": PASSWORD},
        )
        assert activation.status_code == 200, activation.text
        yield {
            "client": client,
            "owner": owner_headers,
            "alice": {"cookie": activation.headers["set-cookie"].split(";")[0]},
            "tmp_path": tmp_path,
        }


def _set_owner_password(db_path) -> None:
    from lumirss.accounts_store import AccountsStore, hash_password

    async def run():
        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        for row in await AccountsStore(database).list_users(limit=50):
            if row["role"] == "owner":
                await AccountsStore(database).set_password_hash(
                    str(row["id"]), hash_password(PASSWORD)
                )
                return
        raise AssertionError("owner migration did not run")

    asyncio.run(run())


def _seed_user_projection(db_path: Path, uid: str, feed_urls: list[str], entries_per_feed: int = 2) -> None:
    """直接在该用户的 SQLite 文件里写入派生投影行（先建库建表）。"""
    user_db = db_path / "users" / uid / "lumi.sqlite"

    async def _migrate():
        await Database(user_db).migrate()

    asyncio.run(_migrate())
    connection = sqlite3.connect(str(user_db))
    try:
        for feed_url in feed_urls:
            connection.execute(
                "INSERT OR REPLACE INTO search_feeds (feed_url, feed_title, category_id, refreshed_at) VALUES (?, ?, NULL, 1700000000)",
                (feed_url, "t"),
            )
            for index in range(entries_per_feed):
                connection.execute(
                    "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, '', '', '', ?, 0, 0, 1700000000)",
                    (
                        f"{feed_url}-{index}",
                        f"ref-{feed_url}-{index}",
                        feed_url,
                        "t",
                        f"条目 {index}",
                        "2026-09-01T00:00:00Z",
                    ),
                )
        connection.commit()
    finally:
        connection.close()


def _list_user_ids(control_db_path: Path) -> list[str]:
    connection = sqlite3.connect(str(control_db_path))
    try:
        return [str(row[0]) for row in connection.execute("SELECT id FROM users")]
    finally:
        connection.close()


def test_admin_usage_counts_without_leaking_other_users(usage_env):
    env = usage_env
    uids = _list_user_ids(env["tmp_path"] / "lumi.sqlite")
    assert len(uids) >= 2
    for index, uid in enumerate(uids):
        # owner 有 1 条 hackernews + 1 条无关；alice 有 1 条 hackernews
        urls = ["http://rsshub.test:1200/hackernews"]
        if index == 0:
            urls.append("https://direct.example/feed.xml")
        _seed_user_projection(env["tmp_path"], uid, urls, entries_per_feed=3)

    response = env["client"].get(
        "/api/v1/admin/rsshub/routes/hackernews/usage", headers=env["owner"]
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["routeKey"] == "hackernews"
    assert data["userCount"] == len(uids)
    assert data["sourceCount"] == len(uids)
    assert data["totalEntries"] == len(uids) * 3
    # 隐私边界：响应整体只有计数键——没有任何标题/URL/用户名可泄漏
    assert set(data) == {
        "routeKey",
        "templateId",
        "userCount",
        "sourceCount",
        "totalEntries",
        "basis",
    }
    serialized = response.text
    assert "hackernews" not in serialized.replace(data["routeKey"], "")
    for title_probe in ("订阅 1", "投影标题", "条目"):
        assert title_probe not in serialized


def test_admin_usage_route_without_users_is_zero(usage_env):
    env = usage_env
    response = env["client"].get(
        "/api/v1/admin/rsshub/routes/sspai-matrix/usage", headers=env["owner"]
    )
    assert response.status_code == 200
    data = response.json()
    assert data["userCount"] == 0
    assert data["sourceCount"] == 0
    assert data["totalEntries"] == 0


def test_member_403_on_usage(usage_env):
    env = usage_env
    response = env["client"].get(
        "/api/v1/admin/rsshub/routes/hackernews/usage", headers=env["alice"]
    )
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "forbidden"
