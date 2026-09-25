"""N149 主题演变时间线 — 24 个月逐月计数 + 本人批注匹配。

- 计数与投影 fixtures 对账（当月/历史月/窗口外），零值月补齐出全窗口；
- 批注腿只含本人（per-user DB 路由：他人批注物理不可见）；
- LIKE 匹配 excerpt/note；cap 10 超界诚实标注；
- 与 GET /search 同参同权限（同过滤链）。
"""

import asyncio
import secrets as _secrets
from datetime import date

import pytest

from lumirss.entryref import encode_entry_ref

PASSWORD = _secrets.token_urlsafe(16)
OWNER_USER = "owner"
A_USER = "alice"
B_USER = "bob"

FEED_A = "https://a.example/rss"
TODAY = date.today()


def _month_shift(base: date, delta: int) -> str:
    total = base.year * 12 + (base.month - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _row(item_id, title, published_at):
    return (
        item_id,
        encode_entry_ref(item_id),
        FEED_A,
        "源A",
        title,
        "作者甲",
        "https://example.com/x",
        f"{title} 的正文。",
        published_at,
        0,
        0,
        0,
    )


def _seed_owner(app):
    async def run():
        from lumirss.user_scope import user_context

        db = app.state.db
        with user_context(app.state.owner_id):
            await db.migrate()
            existing = {
                str(r["entry_ref"])
                for r in await db.fetch_all(
                    "SELECT entry_ref FROM search_entries", ()
                )
            }
            rows = [
                _row("t1", "Rust 发布", f"{TODAY.isoformat()}T08:00:00Z"),
                _row("t2", "Rust 教程", f"{TODAY.isoformat()}T09:00:00Z"),
                _row("t3", "Rust 上月", f"{_month_shift(TODAY, -1)}-15T08:00:00Z"),
                _row("t4", "Rust 去年", f"{_month_shift(TODAY, -13)}-10T08:00:00Z"),
                # 窗口外（24 个月之前）→ 不计入任何月份。
                _row("t5", "Rust 远古", f"{_month_shift(TODAY, -24)}-05T08:00:00Z"),
            ]
            for row in rows:
                if row[1] in existing:
                    continue
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )

    asyncio.run(run())


def _create_annotation(app, uid, *, excerpt, note, entry_ref="t1", marker=0):
    """显式绑定用户的批注写入（请求上下文之外必须 user_context）。

    marker 让锚点彼此不同——同锚点批注是幂等的（同 anchor_hash 复用
    同一行），而这里的用例需要多条独立批注。"""

    async def run():
        from lumirss.annotation_store import AnnotationStore
        from lumirss.user_scope import user_context

        db = app.state.db
        with user_context(uid):
            await db.migrate()
            store = AnnotationStore(db)
            return await store.create(
                entry_ref=entry_ref,
                anchor={"type": "text", "start": marker, "end": marker + 4},
                excerpt=excerpt,
                note=note,
            )

    return asyncio.run(run())


@pytest.fixture()
def timeline_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    from fastapi.testclient import TestClient

    from lumirss.main import app

    with TestClient(app) as test_client:
        _seed_owner(app)
        yield test_client


def _timeline(client, **params):
    body = {"q": "rust"}
    body.update(params)
    response = client.get("/api/v1/search/timeline", params=body)
    assert response.status_code == 200
    return response.json()


def test_month_counts_match_fixture_and_zero_fill(timeline_client):
    body = _timeline(timeline_client)
    assert len(body["months"]) == 24
    assert body["monthFrom"] == _month_shift(TODAY, -23)
    counts = {m["month"]: m["count"] for m in body["months"]}
    assert counts[TODAY.strftime("%Y-%m")] == 2
    assert counts[_month_shift(TODAY, -1)] == 1
    assert counts[_month_shift(TODAY, -13)] == 1
    # 窗口仅覆盖 [-23, 0] 月：-24 月的行不计入任何月份，空月补零。
    assert _month_shift(TODAY, -24) not in counts
    assert counts[_month_shift(TODAY, -10)] == 0
    assert body["total"] == 4


def test_filters_narrow_counts(timeline_client):
    assert _timeline(timeline_client, intitle="教程")["total"] == 1
    assert _timeline(timeline_client, exclude="教程")["total"] == 3


def test_annotations_match_query(timeline_client):
    from lumirss.main import app

    _create_annotation(
        app, app.state.owner_id, excerpt="Rust 所有权笔记", note="重点章节", marker=1
    )
    _create_annotation(
        app, app.state.owner_id, excerpt="无关摘录", note="买菜清单", marker=2
    )

    body = _timeline(timeline_client)
    texts = [a["excerpt"] + a["note"] for a in body["annotations"]]
    assert any("Rust 所有权笔记" in t for t in texts)
    assert all("买菜清单" not in t for t in texts)  # LIKE 未命中不出现
    assert body["annotationsComplete"] is True


def test_annotations_capped_at_ten_honestly(timeline_client):
    from lumirss.main import app

    for i in range(12):
        _create_annotation(
            app, app.state.owner_id, excerpt=f"Rust 批注 {i}", note="", marker=i + 1
        )
    body = _timeline(timeline_client)
    assert len(body["annotations"]) == 10
    assert body["annotationsComplete"] is False


def test_timeline_requires_query(timeline_client):
    response = timeline_client.get("/api/v1/search/timeline", params={"q": "  "})
    assert response.status_code == 400


def test_annotations_own_only_across_accounts(monkeypatch, tmp_path):
    """B 的批注对 A 的时间线不可见（per-user DB 路由，端到端）。"""
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
        headers_owner = {"cookie": owner_cookie}
        cookies: dict[str, str] = {}
        for username in (A_USER, B_USER):
            invite = client.post(
                "/api/v1/admin/invites",
                json={"label": username},
                headers=headers_owner,
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

        # A：搜索投影 + 1 条自己的批注；B：1 条同词批注。
        for username in (A_USER, B_USER):
            uid = _uid_of(lumi_app, username)
            _seed_projection(lumi_app, uid)
            _create_annotation(
                lumi_app,
                uid,
                excerpt=f"Rust {username} 的批注",
                note="",
                marker=7,
            )

        body_a = client.get(
            "/api/v1/search/timeline", params={"q": "rust"}, headers=headers_a
        ).json()
        excerpts = [a["excerpt"] for a in body_a["annotations"]]
        assert excerpts == [f"Rust {A_USER} 的批注"]
        assert all(B_USER not in e for e in excerpts)

        body_b = client.get(
            "/api/v1/search/timeline", params={"q": "rust"}, headers=headers_b
        ).json()
        assert [a["excerpt"] for a in body_b["annotations"]] == [
            f"Rust {B_USER} 的批注"
        ]


def _uid_of(app, username: str) -> str:
    async def run():
        from lumirss.accounts_store import AccountsStore
        from lumirss.user_scope import user_context

        with user_context(app.state.owner_id):
            store = AccountsStore(app.state.control_db)
            for row in await store.list_users(limit=50):
                if row["username"] == username:
                    return str(row["id"])
        raise AssertionError(f"user {username} not found")

    return asyncio.run(run())


def _seed_projection(app, uid: str) -> None:
    async def run():
        from lumirss.user_scope import user_context

        db = app.state.db
        with user_context(uid):
            await db.migrate()
            existing = {
                str(r["entry_ref"])
                for r in await db.fetch_all(
                    "SELECT entry_ref FROM search_entries", ()
                )
            }
            row = _row("t1", "Rust 发布", f"{TODAY.isoformat()}T08:00:00Z")
            if row[1] not in existing:
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )

    asyncio.run(run())
