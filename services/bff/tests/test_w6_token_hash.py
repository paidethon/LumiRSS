"""§13.4 安全整改——bearer token 哈希化存储（W6 收口）。

五处凭据落点统一为「只存 SHA-256 hex（单向验证）」：
- 校验 = sha256(呈递值) == 存储值（常量时间）；回填前旧明文行走兼容
  分支——旧链接/旧 bearer 永不失效；
- 创建/轮换响应是明文的唯一出口（一次性展示）；再次查看 → 空或隐藏；
- 负向：DB / secrets 文件 grep 不到明文（哈希形状断言）。

每处 ≥2 场景：正确 token 过 / 错 token 404；旧明文在回填后仍有效；
DB 负向断言；轮换后旧值失效。
"""

import asyncio
import json

from lumirss.token_backfill import backfill_token_hashes, upgrade_digest_feed_token
from lumirss.token_hash import hash_token, is_token_hash, verify_token


def run(coroutine):
    return asyncio.run(coroutine)


# ---- 纯逻辑：verify_token / is_token_hash -----------------------------------


def test_verify_token_hashed_and_legacy_plaintext_compat():
    stored_hash = hash_token("bearer-xyz")
    assert is_token_hash(stored_hash)
    assert verify_token("bearer-xyz", stored_hash)  # 哈希路径
    assert verify_token("bearer-xyz", "bearer-xyz")  # 旧明文兼容分支
    assert not verify_token("wrong", stored_hash)
    assert not verify_token("", stored_hash) and not verify_token("bearer-xyz", "")


def test_is_token_hash_shape_rejects_raw_secrets():
    assert not is_token_hash("a" * 40)  # new_list_secret 形状（40 hex）
    assert not is_token_hash("a" * 32)  # new_source_secret 形状（32 hex）
    assert is_token_hash("a" * 64)


# ---- 启动回填（token_backfill.backfill_token_hashes） ------------------------


def _seed_legacy_rows(app):
    """四表各插一行旧明文凭据（迁移后标记列默认 0 = 旧明文）。"""
    db = app.state.db

    async def _seed():
        await db.migrate()
        await db.execute(
            "INSERT INTO mail_bridge_lists (uuid, name, secret, created_at) VALUES (?, ?, ?, ?)",
            ("ml-legacy", "旧邮件入口", "legacy-mail-secret", "2026-01-01T00:00:00Z"),
        )
        await db.execute(
            "INSERT INTO inbox_sources (uuid, name, enabled, secret, last_success_at, last_error, created_at) VALUES (?, ?, 1, ?, NULL, NULL, ?)",
            ("in-legacy", "旧连接器", "legacy-inbox-secret", "2026-01-01T00:00:00Z"),
        )
        await db.execute(
            "INSERT INTO saved_searches (id, name, query, params, pinned, pin_order, filters_json, feed_secret, created_at, updated_at) VALUES (?, ?, ?, ?, 0, NULL, '{}', ?, ?, ?)",
            ("sv-legacy", "旧视图", "q", "{}", "legacy-view-secret", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        await db.execute(
            "INSERT INTO api_sources (uuid, name, endpoint, items_expr, field_map, enabled, secret, etag, last_status, last_success_at, last_error, created_at, pagination) VALUES (?, ?, ?, ?, ?, 1, ?, NULL, NULL, NULL, NULL, ?, ?)",
            ("api-legacy", "旧API源", "https://x.example", "$.items", "{}", "legacy-api-secret", "2026-01-01T00:00:00Z", '{"mode":"none"}'),
        )

    run(_seed())


def test_backfill_hashes_all_four_tables_and_keeps_links_working(client):
    app = client.app
    _seed_legacy_rows(app)
    db = app.state.db

    # 回填前：旧明文链接已可用（兼容分支）
    assert client.get("/feeds/mail/ml-legacy.legacy-mail-secret.atom").status_code == 200

    counts = run(backfill_token_hashes(db))
    assert counts == {
        "mail_bridge_lists": 1,
        "inbox_sources": 1,
        "saved_searches": 1,
        "api_sources": 1,
    }

    # 哈希形状 + 无明文残留（负向 grep）
    async def _dump():
        await db.migrate()
        out = {}
        out["mail"] = (await db.fetch_one("SELECT secret, secret_is_hash FROM mail_bridge_lists WHERE uuid = 'ml-legacy'"))
        out["inbox"] = (await db.fetch_one("SELECT secret, secret_is_hash FROM inbox_sources WHERE uuid = 'in-legacy'"))
        out["view"] = (await db.fetch_one("SELECT feed_secret, feed_secret_is_hash FROM saved_searches WHERE id = 'sv-legacy'"))
        out["api"] = (await db.fetch_one("SELECT secret, secret_is_hash FROM api_sources WHERE uuid = 'api-legacy'"))
        return out

    dumped = run(_dump())
    for label, row, column in [
        ("mail", dumped["mail"], "secret"),
        ("inbox", dumped["inbox"], "secret"),
        ("view", dumped["view"], "feed_secret"),
        ("api", dumped["api"], "secret"),
    ]:
        assert row is not None
        assert is_token_hash(str(row[column])), f"{label} 未哈希"
        assert int(row[column.replace("secret", "secret_is_hash") if column == "secret" else "feed_secret_is_hash"]) == 1
        assert "legacy" not in str(row[column])  # 负向：明文不残留

    # 回填后：同一批旧链接 / 旧凭据全部继续有效（单向验证语义）
    assert client.get("/feeds/mail/ml-legacy.legacy-mail-secret.atom").status_code == 200

    # 幂等：再跑一次零改写
    counts2 = run(backfill_token_hashes(db))
    assert counts2 == {"mail_bridge_lists": 0, "inbox_sources": 0, "saved_searches": 0, "api_sources": 0}


# ---- mail bridge（ingest bearer + /feeds/mail atom）--------------------------


def test_mail_bridge_secret_hashed_and_both_endpoints_verify(client):
    resp = client.post("/api/v1/mail/bridge-lists", json={"name": "哈希邮件入口"})
    assert resp.status_code == 201, resp.text
    created = resp.json()
    secret = created["secret"]
    assert secret  # 一次性展示仍在创建响应里

    app = client.app

    app = client.app

    async def _row():
        await app.state.db.migrate()
        return await app.state.db.fetch_one(
            "SELECT secret, secret_is_hash FROM mail_bridge_lists WHERE uuid = ?",
            (created["uuid"],),
        )

    row = run(_row())
    assert is_token_hash(str(row["secret"])) and int(row["secret_is_hash"]) == 1
    assert secret not in str(row["secret"])  # 负向：DB 无明文

    # ingest bearer：正确过 / 错 404
    ok = client.post(
        f"/api/mail/ingest/{created['uuid']}",
        headers={"Authorization": f"Bearer {secret}"},
        content=b"Subject: t\r\n\r\nbody",
    )
    assert ok.status_code == 200, ok.text
    bad = client.post(
        f"/api/mail/ingest/{created['uuid']}",
        headers={"Authorization": "Bearer wrong-secret"},
        content=b"Subject: t\r\n\r\nbody",
    )
    assert bad.status_code == 404

    # atom：正确 token 200（含主题）/ 错 404；self href 不回显存储值
    atom = client.get(f"/feeds/mail/{created['uuid']}.{secret}.atom")
    assert atom.status_code == 200
    assert secret not in atom.text  # self href 不回显（存储值已是哈希）
    assert client.get(f"/feeds/mail/{created['uuid']}.wrong.atom").status_code == 404


# ---- inbox（ingest bearer + rotate）------------------------------------------


def test_inbox_secret_hashed_rotate_invalidates_old(client):
    created = client.post("/api/v1/inbox/sources", json={"name": "哈希连接器"}).json()
    secret = created["secret"]
    ingest = f"/api/v1/inbox/ingest/{created['uuid']}"

    app = client.app

    app = client.app

    async def _row():
        await app.state.db.migrate()
        return await app.state.db.fetch_one(
            "SELECT secret, secret_is_hash FROM inbox_sources WHERE uuid = ?",
            (created["uuid"],),
        )

    row = run(_row())
    assert is_token_hash(str(row["secret"])) and secret not in str(row["secret"])

    payload = {"guid": "g1", "title": "推送一条"}
    ok = client.post(ingest, json=payload, headers={"Authorization": f"Bearer {secret}"})
    assert ok.status_code == 200
    bad = client.post(ingest, json=payload, headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 404

    # 轮换：新 secret 可用、旧立即失效
    rotated = client.post(f"/api/v1/inbox/sources/{created['uuid']}/rotate").json()
    assert rotated["secret"] != secret
    again = client.post(ingest, json={"guid": "g2", "title": "再推"}, headers={"Authorization": f"Bearer {rotated['secret']}"})
    assert again.status_code == 200
    old = client.post(ingest, json={"guid": "g3", "title": "旧令牌"}, headers={"Authorization": f"Bearer {secret}"})
    assert old.status_code == 404
    row2 = run(_row())
    assert rotated["secret"] not in str(row2["secret"])  # 负向：明文不残留


# ---- saved search view（F061 feed token）--------------------------------------


def test_saved_view_token_hashed_and_rotation(client):
    body = {"name": "哈希视图", "query": "alpha"}
    view = client.post("/api/v1/search/views", json=body).json()
    enabled = client.post(f"/api/v1/search/views/{view['id']}/token/enable").json()
    secret = enabled["atomPath"].split(".", 1)[1][: -len(".atom")]

    app = client.app

    app = client.app

    async def _row():
        await app.state.db.migrate()
        return await app.state.db.fetch_one(
            "SELECT feed_secret, feed_secret_is_hash FROM saved_searches WHERE id = ?",
            (view["id"],),
        )

    row = run(_row())
    assert is_token_hash(str(row["feed_secret"])) and secret not in str(row["feed_secret"])

    atom_path = f"/feeds/views/{view['id']}.{secret}.atom"
    assert client.get(atom_path).status_code == 200
    assert client.get(f"/feeds/views/{view['id']}.wrong.atom").status_code == 404

    rotated = client.post(f"/api/v1/search/views/{view['id']}/token/rotate").json()
    new_secret = rotated["atomPath"].split(".", 1)[1][: -len(".atom")]
    assert client.get(f"/feeds/views/{view['id']}.{new_secret}.atom").status_code == 200
    assert client.get(atom_path).status_code == 404  # 旧 token 失效
    assert secret not in run(_row())["feed_secret"]  # type: ignore[operator]


# ---- api source（/feeds/{uuid}.{secret}.atom）--------------------------------


def test_api_source_secret_hashed_and_atom_verifies(client, monkeypatch):
    """上埃及：fetch 桩掉（无真网）；断言仅针对哈希校验层。"""
    import lumirss.routers.api_sources as routes

    async def _fake_fetch(http_client, endpoint):
        return []

    monkeypatch.setattr(routes, "fetch_json", _fake_fetch)
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "哈希API源",
            "endpoint": "https://x.example",
            "itemsExpr": "[*].releases",
            "fieldMap": {"id": "id", "title": "name", "url": "url", "published": "published_at", "body": "body"},
            "subscribe": False,
        },
    ).json()
    secret = created["secret"]

    app = client.app

    app = client.app

    async def _row():
        await app.state.db.migrate()
        return await app.state.db.fetch_one(
            "SELECT secret, secret_is_hash FROM api_sources WHERE uuid = ?",
            (created["uuid"],),
        )

    row = run(_row())
    assert is_token_hash(str(row["secret"])) and int(row["secret_is_hash"]) == 1
    assert secret not in str(row["secret"])

    atom = client.get(f"/feeds/{created['uuid']}.{secret}.atom")
    assert atom.status_code == 200
    assert client.get(f"/feeds/{created['uuid']}.wrong.atom").status_code == 404
    # 列表不回显 secret/atomPath（with_secret 仅创建响应一次）
    listing = client.get("/api/v1/api-sources").text
    assert secret not in listing


# ---- gpt digest feed token（secrets.json 单键）--------------------------------


def test_digest_feed_token_upgraded_to_hash_and_rotation(client):
    app = client.app
    secrets = app.state.secrets_store

    # 遗留明文 token：ensure 原地升级为哈希且不再出明文（再次查看隐藏）
    secrets.set("gpt_digest_feed_token", "legacy-plain-token")
    first = client.get("/api/v1/gpt-digest/feed").json()
    assert first["atomPath"] == ""  # 升级后无法重建明文 → 诚实隐藏
    stored = secrets.get("gpt_digest_feed_token")
    assert stored and is_token_hash(stored)
    assert "legacy-plain-token" not in stored  # 负向：文件无明文
    # 旧链接继续有效：sha256(明文) == 存储哈希
    assert client.get("/feeds/gpt-digest/legacy-plain-token.atom").status_code == 200
    assert client.get("/feeds/gpt-digest/wrong.atom").status_code == 404

    # 轮换：一次性新地址；旧（含遗留）token 立即失效；文件仍无明文
    rotated = client.post("/api/v1/gpt-digest/feed/rotate")
    assert rotated.status_code == 200
    new_path = rotated.json()["atomPath"]
    assert new_path.startswith("/feeds/gpt-digest/")
    assert client.get(new_path).status_code == 200
    assert client.get("/feeds/gpt-digest/legacy-plain-token.atom").status_code == 404
    final_stored = secrets.get("gpt_digest_feed_token")
    assert final_stored and is_token_hash(final_stored)
    assert json.dumps({"token": new_path})  # new_path 里的 token 不在文件里
    assert new_path.split("/feeds/gpt-digest/")[1].removesuffix(".atom") not in final_stored


def test_digest_feed_token_upgrade_helper_is_idempotent(client):
    app = client.app
    secrets = app.state.secrets_store
    secrets.set("gpt_digest_feed_token", "another-plain")
    assert upgrade_digest_feed_token(secrets) is True
    hashed = secrets.get("gpt_digest_feed_token")
    assert hashed == hash_token("another-plain")
    assert upgrade_digest_feed_token(secrets) is False  # 幂等：已是哈希
    assert secrets.get("gpt_digest_feed_token") == hashed
