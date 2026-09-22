"""F061 保存视图私有 Atom 订阅 — 公开路由 / 管理端 / 渲染契约。

- 过滤正确（视图 filters + q 反映到 feed 内容）；
- GUID 稳定（entry_ref 的 sha256 前缀，跨请求不变）；
- 条目上限 ≤100；旧 token 404、新 token 可读；
- 公开路由免登录、管理端需登录；CJK 标题转义正确。
"""

import asyncio
import hashlib
import xml.etree.ElementTree as ET

from lumirss.main import app

ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _run(coroutine):
    return asyncio.run(coroutine)


def _seed_entries(db, rows):
    async def _seed():
        await db.migrate()
        for row in rows:
            await db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )

    _run(_seed())


def _entry(item_id, ref, title, *, feed_url="https://f.example/rss", content="alpha 正文", published="2026-08-01T00:00:00Z", read=0, starred=0):
    return (
        item_id, ref, feed_url, "示例源", title, "作者", f"https://f.example/{item_id}",
        content, published, read, starred, 0,
    )


def _create_view(client, **payload):
    body = {"name": "我的视图", "query": "alpha", **payload}
    resp = client.post("/api/v1/search/views", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _enable(client, view_id):
    return client.post(f"/api/v1/search/views/{view_id}/token/enable")


def _entries(client_client_response):
    root = ET.fromstring(client_client_response.text)
    return root.findall(f"{ATOM_NS}entry")


def test_f061_enable_rotate_and_public_route(client):
    # 与 client 同一临时库（lifespan 绑定的 app.state.db）
    db = app.state.db
    _seed_entries(db, [
        _entry("i1", "ref.1", "alpha 第一篇"),
        _entry("i2", "ref.2", "beta 第二篇", content="beta 正文"),
    ])
    view = _create_view(client)

    # 列表：hasFeedToken 布尔，secret 绝不出站
    listing = client.get("/api/v1/search/views").json()["items"][0]
    assert listing["hasFeedToken"] is False
    assert "feedSecret" not in listing and "feed_secret" not in listing

    enabled = _enable(client, view["id"])
    assert enabled.status_code == 200, enabled.text
    atom_path = enabled.json()["atomPath"]
    assert atom_path.startswith(f"/feeds/views/{view['id']}.") and atom_path.endswith(".atom")
    secret = atom_path.split(".")[-2]
    # secret 是 secrets 风格 hex，且不再出现在任何管理端响应里
    assert len(secret) == 32 and all(c in "0123456789abcdef" for c in secret)
    assert secret not in client.get("/api/v1/search/views").text

    # 已启用 → 再启用 409（地址无法二次查看）
    assert _enable(client, view["id"]).status_code == 409

    # 公开路由免登录可读；标题诚实标注视图名 + 生成时间
    feed = client.get(atom_path)
    assert feed.status_code == 200
    assert "atom+xml" in feed.headers["content-type"]
    root = ET.fromstring(feed.text)
    assert "我的视图" in root.find(f"{ATOM_NS}title").text
    assert "生成于" in root.find(f"{ATOM_NS}title").text

    # 管理端轮换 → 旧地址 404、新地址可读
    rotated = client.post(f"/api/v1/search/views/{view['id']}/token/rotate")
    assert rotated.status_code == 200
    new_path = rotated.json()["atomPath"]
    assert new_path != atom_path
    assert client.get(atom_path).status_code == 404
    assert client.get(new_path).status_code == 200

    # token 错 / 视图缺失 → 同一 404（不泄露存在性）
    new_secret = rotated.json()["atomPath"].split(".")[-2]
    bad_path = new_path.replace(new_secret, new_secret + "ff")
    assert client.get(bad_path).status_code == 404
    assert client.get("/feeds/views/does-not-exist.0123456789abcdef0123456789abcdef.atom").status_code == 404


def test_f061_filters_reflected_and_guid_stable(client):
    db = app.state.db
    _seed_entries(db, [
        _entry("u1", "ref.a", "alpha 未读一篇", read=0),
        _entry("u2", "ref.b", "alpha 已读一篇", read=1),
    ])
    # filters：unreadOnly → 只有未读进入 feed（创建时存意图）
    view = _create_view(client, query="alpha", filters={"unreadOnly": True})
    assert view["filters"] == {"unreadOnly": True}
    path = _enable(client, view["id"]).json()["atomPath"]
    feed = client.get(path)
    entries = _entries(feed)
    titles = [e.find(f"{ATOM_NS}title").text for e in entries]
    assert titles == ["alpha 未读一篇"]

    # GUID 稳定 = entry_ref sha256 前缀；两次请求一致
    expected_id = "urn:lumi:entry:" + hashlib.sha256(b"ref.a").hexdigest()[:32]
    assert entries[0].find(f"{ATOM_NS}id").text == expected_id
    assert client.get(path).text.count(expected_id) == 1
    second = ET.fromstring(client.get(path).text).find(f"{ATOM_NS}entry")
    assert second.find(f"{ATOM_NS}id").text == expected_id


def test_f061_cap_100_and_cjk_escaping(client):
    db = app.state.db
    _seed_entries(db, [
        _entry(f"i{n}", f"ref.n{n}", f"alpha 第{n}篇", content="alpha 正文")
        for n in range(150)
    ])
    view = _create_view(client)
    path = _enable(client, view["id"]).json()["atomPath"]
    feed = client.get(path)
    entries = _entries(feed)
    assert len(entries) == 100  # 分页上限：诚实截断到 ≤100
    # CJK 标题经 stdlib XML 转义后仍可无损解析回原文
    titles = [e.find(f"{ATOM_NS}title").text for e in entries]
    assert "alpha 第99篇" in titles
    assert any(t.startswith("alpha 第") and t.endswith("篇") for t in titles)

    # 不存在的视图 token/rotate → 404
    assert client.post("/api/v1/search/views/nope/token/rotate").status_code == 404
    assert client.post("/api/v1/search/views/nope/token/enable").status_code == 404


def test_f061_admin_needs_session_public_atom_stays_open(client, monkeypatch):
    """管理端需登录（session 模式 401）；公开 Atom 路由无需登录可读。"""
    from fastapi.testclient import TestClient

    from lumirss.accounts_store import AccountsStore, hash_password

    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")

    async def _install_password():
        # 0067：owner 在启动迁移时已存在（随机不可知密码）——把已知
        # 测试密码直接写进控制库 users.password_hash。
        accounts = AccountsStore(app.state.control_db)
        owner = await accounts.get_user_by_username("owner")
        assert owner is not None
        await accounts.set_password_hash(
            str(owner["id"]), hash_password("pw-f061-session")
        )

    with TestClient(app, base_url="http://lumirss.test") as anon:
        # 未登录：管理端列表 401
        assert anon.get("/api/v1/search/views").status_code == 401
        assert (
            anon.post("/api/v1/search/views/x/token/rotate").status_code == 401
        )
        _run(_install_password())
        # 登录后启用订阅
        assert anon.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": "pw-f061-session"},
        ).status_code == 200
        view = _create_view(anon)
        atom_path = _enable(anon, view["id"]).json()["atomPath"]

    with TestClient(app, base_url="http://lumirss.test") as fresh_anon:
        # 全新无 cookie 客户端：公开 Atom 可读、管理端仍 401
        assert fresh_anon.get(atom_path).status_code == 200
        assert fresh_anon.get("/api/v1/search/views").status_code == 401
