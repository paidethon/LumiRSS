"""N143 搜索排除原因（why-missed）— 单条目复跑过滤链归因回归。

- 每类排除条件（词条/仅标题/短语/排除/来源/分类/未读/收藏/日期/摘要）
  都能被如实归因；
- 全部条件通过 → matched=true + 诚实 rank（keyset 全量迭代复用生产查
  询路径）；
- 他人条目的 ref → 与不存在同一 404（不泄露存在性）。
"""

import asyncio
import secrets as _secrets

import pytest

from lumirss.entryref import encode_entry_ref

PASSWORD = "wm-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice"
B_USER = "bob"

FEED_A = "https://a.example/rss"
FEED_B = "https://b.example/rss"

# (item_id, title, content, published_at, feed_url, read, starred)
ROWS = [
    ("1", "Rust 1.80 发布", "Rust 性能提升明显。", "2026-09-23T08:00:00Z", FEED_A, 0, 0),
    ("2", "Rust 旧闻回顾", "去年的 Rust 内容存档。", "2025-03-01T08:00:00Z", FEED_B, 1, 0),
    ("3", "Rust 广告合集", "推广内容。", "2026-09-22T08:00:00Z", FEED_A, 0, 1),
]


def _seed_owner_or_member_db(app, uid: str | None = None) -> None:
    """直接向（指定用户的）搜索投影写入固定行 + 分类投影。

    uid=None → owner（app.state.owner_id，lifespan 已设置）；请求上下文
    之外的后台写入必须显式绑定用户（user_context 同步上下文管理器）。"""

    async def run():
        from lumirss.search_store import SearchStore
        from lumirss.user_scope import user_context

        target = uid if uid is not None else app.state.owner_id
        db = app.state.db
        with user_context(target):
            await db.migrate()
            store = SearchStore(db)
            for (
                item_id,
                title,
                content,
                published_at,
                feed_url,
                read,
                starred,
            ) in ROWS:
                row = await store.entry_row_by_ref(encode_entry_ref(item_id))
                if row is not None:
                    continue
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item_id,
                        encode_entry_ref(item_id),
                        feed_url,
                        "源A" if feed_url == FEED_A else "源B",
                        title,
                        "作者甲",
                        "https://example.com/x",
                        content,
                        published_at,
                        read,
                        starred,
                        0,
                    ),
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


def _why_missed(client, ref, **overrides):
    body = {"query": "rust", "entryRef": ref}
    body.update(overrides)
    return client.post("/api/v1/search/why-missed", json=body)


@pytest.fixture()
def search_client(monkeypatch, tmp_path):
    """client fixture + 预置 owner 投影行（与 test_search_advanced 同
    一 TestClient 模式，保证 hermetic）。"""
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    from fastapi.testclient import TestClient

    from lumirss.main import app

    with TestClient(app) as test_client:
        _seed_owner_or_member_db(app)
        yield test_client


# ---- 各类排除归因 -----------------------------------------------------------


def test_term_miss_reported(search_client):
    ref = encode_entry_ref("1")
    body = _why_missed(search_client, ref, query="quantum").json()
    assert body["matched"] is False
    kinds = [r["kind"] for r in body["reasons"]]
    assert "term" in kinds
    assert any("quantum" in r["detail"] for r in body["reasons"])


def test_intitle_miss_reported(search_client):
    body = _why_missed(
        search_client, encode_entry_ref("1"), intitle="旧闻"
    ).json()
    assert [r["kind"] for r in body["reasons"]] == ["intitle"]


def test_phrase_miss_reported(search_client):
    body = _why_missed(
        search_client, encode_entry_ref("2"), phrase="性能提升明显"
    ).json()
    assert [r["kind"] for r in body["reasons"]] == ["phrase"]


def test_exclude_hit_reported(search_client):
    body = _why_missed(
        search_client, encode_entry_ref("1"), exclude="性能"
    ).json()
    assert [r["kind"] for r in body["reasons"]] == ["exclude"]


def test_source_mismatch_reported(search_client):
    body = _why_missed(
        search_client, encode_entry_ref("1"), feedUrl=FEED_B
    ).json()
    assert [r["kind"] for r in body["reasons"]] == ["source"]
    assert "源A" in body["reasons"][0]["detail"]


def test_category_mismatch_reported(search_client):
    body = _why_missed(
        search_client, encode_entry_ref("1"), categoryId="cat-b"
    ).json()
    assert [r["kind"] for r in body["reasons"]] == ["category"]


def test_unread_filter_reported(search_client):
    body = _why_missed(
        search_client, encode_entry_ref("2"), state="unread"
    ).json()
    assert [r["kind"] for r in body["reasons"]] == ["unread"]


def test_starred_filter_reported(search_client):
    body = _why_missed(
        search_client, encode_entry_ref("1"), favorite=True
    ).json()
    assert [r["kind"] for r in body["reasons"]] == ["starred"]


def test_date_range_reported(search_client):
    body = _why_missed(
        search_client,
        encode_entry_ref("2"),
        **{"from": "2026-01-01", "to": "2027-01-01"},
    ).json()
    assert [r["kind"] for r in body["reasons"]] == ["date"]
    assert "2025-03-01" in body["reasons"][0]["detail"]


def test_has_summary_reported(search_client):
    body = _why_missed(
        search_client, encode_entry_ref("3"), hasSummary=False
    ).json()
    assert [r["kind"] for r in body["reasons"]] == ["hasSummary"]


def test_multiple_reasons_all_listed(search_client):
    body = _why_missed(
        search_client,
        encode_entry_ref("2"),
        favorite=True,
        state="unread",
        feedUrl=FEED_A,
    ).json()
    kinds = {r["kind"] for r in body["reasons"]}
    assert kinds == {"starred", "unread", "source"}


# ---- matched + 诚实排序位置 --------------------------------------------------


def test_matched_reports_honest_rank(search_client):
    body = _why_missed(search_client, encode_entry_ref("1")).json()
    assert body["matched"] is True
    assert body["reasons"] == []
    assert body["rank"] == 1  # 最新优先
    assert body["rankCapped"] is False
    assert body["entry"]["title"] == "Rust 1.80 发布"


def test_matched_oldest_entry_rank(search_client):
    body = _why_missed(search_client, encode_entry_ref("2")).json()
    assert body["matched"] is True
    assert body["rank"] == 3


# ---- own-scope：他人条目 404，不泄露存在性 -----------------------------------


@pytest.fixture()
def iso_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    return tmp_path


def _login(client, username):
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )


def test_foreign_entry_ref_is_404_without_leak(iso_env):
    """B 的条目 ref 对 A → 404 search_entry_not_found（与不存在同型）。"""
    from fastapi.testclient import TestClient

    from lumirss.accounts_store import AccountsStore, hash_password
    from lumirss.main import app

    with TestClient(app, base_url="http://lumirss.test") as client:

        async def _set_owner_password():
            store = AccountsStore(app.state.control_db)
            for row in await store.list_users(limit=50):
                if row["role"] == "owner":
                    await store.set_password_hash(
                        str(row["id"]), hash_password(PASSWORD)
                    )
                    return

        asyncio.run(_set_owner_password())
        owner_cookie = _login(client, OWNER_USER).headers["set-cookie"].split(";")[0]
        owner_headers = {"cookie": owner_cookie}
        invite = client.post(
            "/api/v1/admin/invites", json={"label": A_USER}, headers=owner_headers
        ).json()
        cookie_a = client.post(
            "/api/v1/auth/activate",
            json={
                "token": invite["token"],
                "username": A_USER,
                "password": PASSWORD,
                "displayName": A_USER,
            },
        ).headers["set-cookie"].split(";")[0]
        headers_a = {"cookie": cookie_a}
        invite_b = client.post(
            "/api/v1/admin/invites", json={"label": B_USER}, headers=owner_headers
        ).json()
        client.post(
            "/api/v1/auth/activate",
            json={
                "token": invite_b["token"],
                "username": B_USER,
                "password": PASSWORD,
                "displayName": B_USER,
            },
        )

        # A 的库：1 条自己的投影行。
        session_a = client.get(
            "/api/v1/auth/session", headers=headers_a
        ).json()
        _seed_owner_or_member_db(app, uid=session_a["userId"])

        # B 的库：另 1 条（ref 形状相同、item_id 不同）；找 B 的 uid。
        login_b = _login(client, B_USER)
        cookie_b = login_b.headers["set-cookie"].split(";")[0]
        uid_b = client.get(
            "/api/v1/auth/session", headers={"cookie": cookie_b}
        ).json()["userId"]

        from lumirss.user_scope import user_context

        async def _seed_b():
            db = app.state.db
            with user_context(uid_b):
                await db.migrate()
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "b-secret",
                        encode_entry_ref("b-secret"),
                        FEED_B,
                        "B的源",
                        "B 的私密条目",
                        "",
                        "https://b.example/x",
                        "私密内容",
                        "2026-09-01T00:00:00Z",
                        0,
                        0,
                        0,
                    ),
                )

        asyncio.run(_seed_b())

        # A 查询 B 的条目 → 404（稳定类型），不泄露存在性。
        response = client.post(
            "/api/v1/search/why-missed",
            json={"query": "rust", "entryRef": encode_entry_ref("b-secret")},
            headers=headers_a,
        )
        assert response.status_code == 404
        assert (
            response.json()["error"]["type"] == "search_entry_not_found"
        )

        # 完全不存在的 ref → 同一 404（不可区分）。
        missing = client.post(
            "/api/v1/search/why-missed",
            json={"query": "rust", "entryRef": encode_entry_ref("nope")},
            headers=headers_a,
        )
        assert missing.status_code == 404
        assert (
            missing.json()["error"]["type"] == "search_entry_not_found"
        )

        # A 查询自己的条目 → 正常诊断（matched）。
        own = client.post(
            "/api/v1/search/why-missed",
            json={"query": "rust", "entryRef": encode_entry_ref("1")},
            headers=headers_a,
        )
        assert own.status_code == 200
        assert own.json()["matched"] is True


# ---- 参数校验 ----------------------------------------------------------------


def test_why_missed_validates_payload(search_client):
    empty = search_client.post(
        "/api/v1/search/why-missed",
        json={"query": "rust", "entryRef": encode_entry_ref("1"), "state": "bogus"},
    )
    assert empty.status_code == 400
    mutex = search_client.post(
        "/api/v1/search/why-missed",
        json={
            "query": "rust",
            "entryRef": encode_entry_ref("1"),
            "feedUrl": FEED_A,
            "categoryId": "cat-a",
        },
    )
    assert mutex.status_code == 400
