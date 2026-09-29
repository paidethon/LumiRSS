"""NEW-211..220 组共享的 A/B 双用户隔离夹具（session 模式 + 真实路由）。

用法与 test_e3_n199_quick_actions.py 的隔离测试同构：独立临时控制库、
owner 邀请成员 B、各自 cookie 会话；返回的 client 上 owner/member
headers 分离。每个测试独占一个 TestClient（进程级中间件计数器先清）。
"""

import asyncio
import secrets


def build_two_user_client():
    """返回 (TestClient, owner_headers, member_headers)——均已登录。"""
    from fastapi.testclient import TestClient

    from lumirss.main import app

    password = secrets.token_urlsafe(16)

    def _run(coroutine):
        return asyncio.run(coroutine)

    with TestClient(app, base_url="http://lumirss.test") as session_client:
        async def _set_owner_password():
            import os

            from lumirss.accounts_store import AccountsStore, hash_password
            from lumirss.storage import Database

            database = Database(os.environ["LUMIRSS_DB_PATH"])
            await database.migrate()
            store = AccountsStore(database)
            for row in await store.list_users(limit=50):
                if row["role"] == "owner":
                    await store.set_password_hash(str(row["id"]), hash_password(password))
                    return

        _run(_set_owner_password())
        owner_login = session_client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": password}
        )
        owner = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = session_client.post(
            "/api/v1/admin/invites", json={"label": "ab-test"}, headers=owner
        )
        member = session_client.post(
            "/api/v1/auth/activate",
            json={
                "token": invite.json()["token"],
                "username": secrets.token_hex(4),
                "password": password,
            },
        )
        member_headers = {"cookie": member.headers["set-cookie"].split(";")[0]}
        yield session_client, owner, member_headers


def isolated_auth_env(monkeypatch, tmp_path) -> None:
    """session 模式 + 干净限流计数（与 n199 隔离测试同构）。"""
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")

    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    middleware._implicit_owner_cache.clear()


def seed_library_item(client, item_uuid: str, title: str = "种子条目") -> str:
    """落一行可解析的 library bookmark（bookmarks 域投影 + 视图都好使）。"""
    import asyncio

    from lumirss.db_tx import transaction

    ref = f"library:{item_uuid}"

    def _seed(conn):
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'bookmark', '2026-09-01T00:00:00+00:00')",
            (item_uuid,),
        )
        conn.execute(
            "INSERT INTO library_bookmarks (item_uuid, item_type, url, title, note, created_at) VALUES (?, 'url', ?, ?, '', '2026-09-01T00:00:00+00:00')",
            (item_uuid, f"https://seed.example/{item_uuid}", title),
        )

    asyncio.run(transaction(client.app.state.db, _seed))
    return ref


def make_bookmark(client, headers: dict, title: str) -> str:
    """经真实路由创建 per-user 可解析的 library 书签，返回其 ItemRef。

    隔离测试的内容种子必须走用户自己的会话（直连 app.state.db 没有
    user context；经路由创建则天然落在对应账户的库）。"""
    created = client.post(
        "/api/v1/library/bookmarks",
        json={"url": f"https://seed.example/{abs(hash(title))}", "title": title},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return str(created.json()["ref"])


def seed_entry(client, item_id: str, *, title: str = "种子文章", feed: str = "https://f.example/rss",
               published_at: str = "2026-09-01T00:00:00+00:00", read: int = 0, starred: int = 0) -> str:
    """落一行 search_entries 投影（rss 引用解析/预览的好使路径）。"""
    import asyncio

    from lumirss.entryref import encode_entry_ref

    entry_ref = encode_entry_ref(item_id)

    async def _seed():
        await client.app.state.db.migrate()
        await client.app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, '', 'https://u.example/x', '', ?, ?, ?, 0)",
            (item_id, entry_ref, feed, "种子源", title, published_at, read, starred),
        )

    asyncio.run(_seed())
    return f"rss:{entry_ref}"

