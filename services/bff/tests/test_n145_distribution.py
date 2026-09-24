"""N145 来源内搜索分布 — 同参聚合回归。

- 来源计数 / 总数与手工执行同一过滤链的搜索一致（fixtures 对账）；
- 近 30 天逐日计数（补零出全窗口）；
- 来源 top-20 截断诚实标注；
- 权限作用域与 /search 完全一致（他人条目绝不计入）。
"""

import asyncio
import secrets as _secrets
from datetime import date, timedelta

import pytest

from lumirss.entryref import encode_entry_ref

PASSWORD = "ds-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"
B_USER = "bob"

FEED_A = "https://a.example/rss"
FEED_B = "https://b.example/rss"
TODAY = date.today()


def _iso(day: date) -> str:
    return day.isoformat()


def _row(item_id, title, content, published_at, feed_url, feed_title):
    return (
        item_id,
        encode_entry_ref(item_id),
        feed_url,
        feed_title,
        title,
        "作者甲",
        "https://example.com/x",
        content,
        published_at,
        0,
        0,
        0,
    )


def _seed_db(app, uid: str | None = None) -> None:
    """投影行：源A 3 条（2 条今天、1 条昨天），源B 1 条（昨天）。"""

    async def run():
        from lumirss.user_scope import user_context

        target = uid if uid is not None else app.state.owner_id
        db = app.state.db
        with user_context(target):
            await db.migrate()
            existing = {str(r["entry_ref"]) for r in await db.fetch_all(
                "SELECT entry_ref FROM search_entries", ()
            )}
            rows = [
                _row("a1", "Rust 发布", "Rust 新版本内容。", f"{_iso(TODAY)}T08:00:00Z", FEED_A, "源A"),
                _row("a2", "Rust 教程", "Rust 入门实践。", f"{_iso(TODAY)}T09:00:00Z", FEED_A, "源A"),
                _row("a3", "Rust 深谈", "Rust 进阶话题。", f"{_iso(TODAY - timedelta(days=1))}T08:00:00Z", FEED_A, "源A"),
                _row("b1", "Python 周报", "Python 动态。", f"{_iso(TODAY - timedelta(days=1))}T08:00:00Z", FEED_B, "源B"),
            ]
            for row in rows:
                if row[1] in existing:
                    continue
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
            await db.execute("DELETE FROM search_feeds")
            await db.execute(
                "INSERT INTO search_feeds (feed_url, feed_title, category_id, refreshed_at) VALUES (?, ?, ?, ?)",
                (FEED_A, "源A", "cat-a", 0),
            )
            await db.execute(
                "INSERT INTO search_feeds (feed_url, feed_title, category_id, refreshed_at) VALUES (?, ?, ?, ?)",
                (FEED_B, "源B", "cat-b", 0),
            )

    asyncio.run(run())


@pytest.fixture()
def dist_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    from fastapi.testclient import TestClient

    from lumirss.main import app

    with TestClient(app) as test_client:
        _seed_db(app)
        yield test_client


def _distribution(client, **params):
    response = client.get("/api/v1/search/distribution", params=params)
    assert response.status_code == 200
    return response.json()


def test_source_counts_match_manual_query(dist_client):
    body = _distribution(dist_client, q="rust")
    assert body["total"] == 3
    sources = {s["feedUrl"]: s["count"] for s in body["sources"]}
    assert sources == {FEED_A: 3}
    assert body["sourcesComplete"] is True

    # 手工对账：与 GET /search 全量迭代（同过滤链）计数一致。
    seen = []
    cursor = None
    for _ in range(10):
        params = {"q": "rust", "limit": 50}
        if cursor:
            params["cursor"] = cursor
        page = dist_client.get("/api/v1/search", params=params).json()
        seen.extend(row["entryRef"] for row in page["items"])
        if not page["hasMore"]:
            break
        cursor = page["nextCursor"]
    assert len(seen) == body["total"]
    assert {FEED_A: seen.count(encode_entry_ref("a1"))} == {FEED_A: 1}


def test_per_day_histogram_zero_filled(dist_client):
    body = _distribution(dist_client, q="rust")
    assert len(body["days"]) == 30
    assert body["dayFrom"] == _iso(TODAY - timedelta(days=29))
    counts = {d["day"]: d["count"] for d in body["days"]}
    assert counts[_iso(TODAY)] == 2
    assert counts[_iso(TODAY - timedelta(days=1))] == 1
    assert counts[_iso(TODAY - timedelta(days=5))] == 0


def test_filters_narrow_the_aggregate(dist_client):
    body = _distribution(dist_client, q="rust", feedUrl=FEED_A)
    assert body["total"] == 3
    body = _distribution(dist_client, q="python")
    assert body["total"] == 1
    assert body["sources"] == [
        {"feedUrl": FEED_B, "feedTitle": "源B", "count": 1}
    ]
    # 日期过滤（仅今天）。
    body = _distribution(dist_client, q="rust", **{"from": _iso(TODAY), "to": _iso(TODAY + timedelta(days=1))})
    assert body["total"] == 2
    # 未读过滤（全未读 → 不变）；排除词。
    body = _distribution(dist_client, q="rust", exclude="教程")
    assert body["total"] == 2
    body = _distribution(dist_client, q="rust", intitle="教程")
    assert body["total"] == 1
    body = _distribution(dist_client, q="rust", phrase="入门实践")
    assert body["total"] == 1


def test_top20_sources_capped_honestly(dist_client, monkeypatch):
    """>20 个来源时截断 20 并诚实标注 sourcesComplete=false。"""
    from lumirss.main import app as lumi_app
    from lumirss.user_scope import user_context

    async def run():
        db = lumi_app.state.db
        with user_context(lumi_app.state.owner_id):
            await db.migrate()
            for i in range(25):
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _row(
                        f"m{i}",
                        f"聚合词 {i}",
                        "聚合词内容。",
                        f"{_iso(TODAY)}T07:{i:02d}:00Z",
                        f"https://src{i}.example/rss",
                        f"源{i}",
                    ),
                )

    asyncio.run(run())
    body = _distribution(dist_client, q="聚合词")
    assert len(body["sources"]) == 20
    assert body["sourcesComplete"] is False
    # 计数降序：第一个来源计数最高。
    assert body["sources"][0]["count"] == 1
    assert body["total"] == 25


def test_permission_scoping_excludes_other_users(monkeypatch, tmp_path):
    """B 的条目对 A 的分布不可见（per-user DB 路由 + 同一作用域）。"""
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()

    from fastapi.testclient import TestClient

    from lumirss.accounts_store import AccountsStore, hash_password
    from lumirss.main import app as lumi_app

    with TestClient(lumi_app, base_url="http://lumirss.test") as client:

        async def _set_owner_password():
            store = AccountsStore(lumi_app.state.control_db)
            for row in await store.list_users(limit=50):
                if row["role"] == "owner":
                    await store.set_password_hash(
                        str(row["id"]), hash_password(PASSWORD)
                    )
                    return

        asyncio.run(_set_owner_password())
        owner_cookie = client.post(
            "/api/v1/auth/login",
            json={"username": OWNER_USER, "password": PASSWORD},
        ).headers["set-cookie"].split(";")[0]
        owner_headers = {"cookie": owner_cookie}
        cookies: dict[str, str] = {}
        for username in (A_USER, B_USER):
            invite = client.post(
                "/api/v1/admin/invites",
                json={"label": username},
                headers=owner_headers,
            ).json()
            cookies[username] = client.post(
                "/api/v1/auth/activate",
                json={
                    "token": invite["token"],
                    "username": username,
                    "password": PASSWORD,
                    "displayName": username,
                },
            ).headers["set-cookie"].split(";")[0]
        headers_a = {"cookie": cookies[A_USER]}
        headers_b = {"cookie": cookies[B_USER]}

        # A：2 条 rust（源A）；B：5 条 rust（同词，源B）——分布必须互不可见。
        from lumirss.user_scope import user_context

        async def _seed(uid: str, rows):
            db = lumi_app.state.db
            with user_context(uid):
                await db.migrate()
                for row in rows:
                    await db.execute(
                        "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        row,
                    )

        def _mk(item_id, feed_url, feed_title):
            return _row(
                item_id,
                f"{item_id}-x",
                "共享词内容。",
                f"{_iso(TODAY)}T06:00:00Z",
                feed_url,
                feed_title,
            )

        uid_a = client.get(
            "/api/v1/auth/session", headers=headers_a
        ).json()["userId"]
        uid_b = client.get(
            "/api/v1/auth/session", headers=headers_b
        ).json()["userId"]
        asyncio.run(
            _seed(
                uid_a,
                [
                    _mk("aa1", FEED_A, "A源"),
                    _mk("aa2", FEED_A, "A源"),
                ],
            )
        )
        asyncio.run(
            _seed(
                uid_b,
                [
                    _mk(f"bb{i}", FEED_B, "B源") for i in range(5)
                ],
            )
        )

        body_a = client.get(
            "/api/v1/search/distribution",
            params={"q": "共享词内容"},
            headers=headers_a,
        )
        assert body_a.status_code == 200
        body_a = body_a.json()
        assert body_a["total"] == 2  # 绝不计入 B 的 5 条
        assert {s["feedUrl"] for s in body_a["sources"]} == {FEED_A}

        body_b = client.get(
            "/api/v1/search/distribution",
            params={"q": "共享词内容"},
            headers=headers_b,
        ).json()
        assert body_b["total"] == 5
        assert {s["feedUrl"] for s in body_b["sources"]} == {FEED_B}


def test_validation_errors(dist_client):
    empty = dist_client.get("/api/v1/search/distribution", params={"q": ""})
    assert empty.status_code == 400
    mutex = dist_client.get(
        "/api/v1/search/distribution",
        params={"q": "rust", "feedUrl": FEED_A, "categoryId": "cat-a"},
    )
    assert mutex.status_code == 400
    bogus = dist_client.get(
        "/api/v1/search/distribution", params={"q": "rust", "state": "read"}
    )
    assert bogus.status_code == 400
