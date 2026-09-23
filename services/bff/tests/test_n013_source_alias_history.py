"""N013 来源改名（别名）+ 历史 —— 存储、路由与账户隔离。

- upsert + 历史：变化写史（old + 上游快照）、同名不重复写史、封顶 20；
- 上游标题变更绝不覆盖 custom_name（适配器 mock 改名后别名原样）；
- DELETE 删别名留历史；恢复 = 用历史旧名重新 PUT；
- 隔离：A 设的别名对 B 不可见（per-user DB，B 侧 404 / 空列表）。
"""

import asyncio
from types import SimpleNamespace

from lumirss.main import app
from lumirss.source_aliases import SourceAliasInvalid, SourceAliasStore

FEED_URL = "https://feed.example.com/rss"


def run(coroutine):
    return asyncio.run(coroutine)


def _store():
    return SourceAliasStore(app.state.db)


def _install_read_adapter(title: str):
    async def _list_subs():
        return [SimpleNamespace(stream_id="feed/1", feed_url=FEED_URL, title=title)]

    app.state.freshrss_adapter = SimpleNamespace(list_subscriptions=_list_subs)


def test_n013_put_upsert_history_and_snapshot(client):
    _install_read_adapter("上游标题 v1")
    first = client.put(
        "/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": "我的源"}
    )
    assert first.status_code == 200, first.text
    assert first.json()["customName"] == "我的源"

    history = client.get(f"/api/v1/sources/alias/history?feedUrl={FEED_URL}").json()
    assert len(history["items"]) == 1
    assert history["items"][0]["oldCustomName"] is None  # 首设别名
    assert history["items"][0]["upstreamNameAtSave"] == "上游标题 v1"

    # 同名重复 PUT：别名 upsert，历史不重复写
    client.put("/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": "我的源"})
    history = client.get(f"/api/v1/sources/alias/history?feedUrl={FEED_URL}").json()
    assert len(history["items"]) == 1

    # 更名：历史记录旧名 + 当时上游快照
    _install_read_adapter("上游标题 v2（上游已改名）")
    second = client.put(
        "/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": "更好认的名字"}
    )
    assert second.status_code == 200
    history = client.get(f"/api/v1/sources/alias/history?feedUrl={FEED_URL}").json()
    assert len(history["items"]) == 2
    assert history["items"][0]["oldCustomName"] == "我的源"
    assert history["items"][0]["upstreamNameAtSave"] == "上游标题 v2（上游已改名）"

    listing = client.get("/api/v1/sources/aliases").json()
    assert [item["customName"] for item in listing["items"]] == ["更好认的名字"]


def test_n013_upstream_rename_never_overwrites_alias(client):
    _install_read_adapter("旧上游标题")
    client.put("/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": "我的源"})
    # 模拟上游改名：适配器返回的标题变了；别名存储没有任何「随上游
    # 改名」路径——别名只被显式 PUT/DELETE 改变。
    _install_read_adapter("上游全新标题")
    stored = run(_store().get_alias(FEED_URL))
    assert stored is not None and stored["customName"] == "我的源"
    # 之后一次快照型 PUT 记录新上游名，但别名仍是用户显式设置的值。
    client.put("/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": "我的源"})
    stored = run(_store().get_alias(FEED_URL))
    assert stored["customName"] == "我的源"


def test_n013_history_capped_at_20(client):
    for i in range(25):
        response = client.put(
            "/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": f"名字 {i}"}
        )
        assert response.status_code == 200
    history = client.get(f"/api/v1/sources/alias/history?feedUrl={FEED_URL}").json()
    assert len(history["items"]) == 20  # 封顶：只保留最近 20 条
    assert history["items"][0]["oldCustomName"] == "名字 23"
    stored = run(_store().get_alias(FEED_URL))
    assert stored["customName"] == "名字 24"


def test_n013_delete_keeps_history_and_restore(client):
    client.put("/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": "第一版"})
    client.put("/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": "第二版"})
    deleted = client.delete(f"/api/v1/sources/alias?feedUrl={FEED_URL}")
    assert deleted.status_code == 204
    assert run(_store().get_alias(FEED_URL)) is None
    listing = client.get("/api/v1/sources/aliases").json()
    assert listing["items"] == []
    # 历史保留
    history = client.get(f"/api/v1/sources/alias/history?feedUrl={FEED_URL}").json()
    assert len(history["items"]) == 2
    # 删除不存在的别名 → 404（稳定错误码）
    again = client.delete(f"/api/v1/sources/alias?feedUrl={FEED_URL}")
    assert again.status_code == 404
    assert again.json()["error"]["type"] == "source_alias_not_found"
    # 恢复 = 用历史旧名重新 PUT
    restored = client.put(
        "/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": "第一版"}
    )
    assert restored.status_code == 200
    assert run(_store().get_alias(FEED_URL))["customName"] == "第一版"


def test_n013_invalid_name_rejected(client):
    empty = client.put("/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": "   "})
    assert empty.status_code == 422
    assert empty.json()["error"]["type"] == "invalid_source_alias"
    too_long = client.put(
        "/api/v1/sources/alias", json={"feedUrl": FEED_URL, "customName": "x" * 201}
    )
    assert too_long.status_code == 422
    # 存储层同样拒绝（双保险），且不落任何行
    try:
        run(_store().put_alias(FEED_URL, ""))
    except SourceAliasInvalid:
        pass
    else:
        raise AssertionError("空别名必须被拒绝")
    assert run(_store().get_alias(FEED_URL)) is None


def test_n013_member_isolation(monkeypatch, tmp_path):
    """A 设的别名对 B 不可见：per-user DB 路由，B 侧空列表 + 404。"""
    import secrets as _secrets

    from fastapi.testclient import TestClient

    from lumirss.accounts_store import AccountsStore, hash_password

    password = "iso-" + _secrets.token_urlsafe(9)
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    middleware._implicit_owner_cache.clear()
    with TestClient(app, base_url="http://lumirss.test") as isolated:
        async def _fix_owner():
            from lumirss.storage import Database

            database = Database(tmp_path / "lumi.sqlite")
            await database.migrate()
            store = AccountsStore(database)
            for row in await store.list_users(limit=50):
                if row["role"] == "owner":
                    await store.set_password_hash(str(row["id"]), hash_password(password))
                    break

        asyncio.run(_fix_owner())
        owner = isolated.post(
            "/api/v1/auth/login", json={"username": "owner", "password": password}
        )
        assert owner.status_code == 200
        owner_headers = {"cookie": owner.headers["set-cookie"].split(";")[0]}
        invite = isolated.post(
            "/api/v1/admin/invites", json={"label": "a"}, headers=owner_headers
        )
        token = invite.json()["token"]
        a = isolated.post(
            "/api/v1/auth/activate",
            json={
                "token": token,
                "username": "alice",
                "password": password,
                "displayName": "A",
            },
        )
        invite_b = isolated.post(
            "/api/v1/admin/invites", json={"label": "b"}, headers=owner_headers
        )
        b = isolated.post(
            "/api/v1/auth/activate",
            json={
                "token": invite_b.json()["token"],
                "username": "bob",
                "password": password,
                "displayName": "B",
            },
        )
        a_headers = {"cookie": a.headers["set-cookie"].split(";")[0]}
        b_headers = {"cookie": b.headers["set-cookie"].split(";")[0]}

        put = isolated.put(
            "/api/v1/sources/alias",
            json={"feedUrl": FEED_URL, "customName": "甲的别名"},
            headers=a_headers,
        )
        assert put.status_code == 200, put.text
        # A 自己可见
        seen_by_a = isolated.get("/api/v1/sources/aliases", headers=a_headers).json()
        assert [item["customName"] for item in seen_by_a["items"]] == ["甲的别名"]
        # B 侧（独立用户库）：空列表；DELETE → 404
        seen_by_b = isolated.get("/api/v1/sources/aliases", headers=b_headers).json()
        assert seen_by_b["items"] == []
        gone = isolated.delete(
            f"/api/v1/sources/alias?feedUrl={FEED_URL}", headers=b_headers
        )
        assert gone.status_code == 404
        # A 的别名原样（B 的删除没有越权）
        still = isolated.get("/api/v1/sources/aliases", headers=a_headers).json()
        assert [item["customName"] for item in still["items"]] == ["甲的别名"]
