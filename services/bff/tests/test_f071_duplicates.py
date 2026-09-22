"""F071 疑似重复审核 — scan 找到种子对、白名单后不重现、confirm 建关系、
重复扫描幂等、status 重启持久、不自动删除任何条目（负向）。"""

import asyncio

from lumirss.main import app


def run(coroutine):
    return asyncio.run(coroutine)


def _seed(client):
    """种子：a/b/d 为普通书签（不同 URL）；e 与 a 标题相同但 URL 不同
    （title_jaccard 对）；c 为同一 URL 的剪藏（same_content_url 异源对）。"""
    db = app.state.db

    async def _seed_inner():
        await db.migrate()
        rows = [
            ("00000000-0000-4000-8000-00000000000a", "https://shop.example/item/42", None, "LumiRSS 阅读器上手指南"),
            ("00000000-0000-4000-8000-00000000000b", "https://other.example/post", None, " completely different topic "),
            ("00000000-0000-4000-8000-00000000000d", "https://shop.example/item/99", None, "毫不相干的另一篇文章"),
            ("00000000-0000-4000-8000-00000000000e", "https://blog.example/lumirss-guide", None, "LumiRSS 阅读器上手指南"),
        ]
        for uuid_, url, rss_ref, title in rows:
            await db.execute(
                "INSERT OR IGNORE INTO library_items (uuid, kind, created_at) VALUES (?, 'bookmark', '2026-09-01T00:00:00Z')",
                (uuid_,),
            )
            await db.execute(
                "INSERT OR IGNORE INTO library_bookmarks (item_uuid, item_type, url, rss_item_ref, title, note, created_at) VALUES (?, 'url', ?, ?, ?, '', '2026-09-01T00:00:00Z')",
                (uuid_, url, rss_ref, title),
            )
        # 剪藏：与 uuid-a 同 URL（不同表，异来源）
        await db.execute(
            "INSERT OR IGNORE INTO library_items (uuid, kind, created_at) VALUES ('00000000-0000-4000-8000-00000000000c', 'clip', '2026-09-01T00:00:00Z')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO library_clips (item_uuid, url, title, content_html, content_text, fetched_at, created_at) VALUES ('00000000-0000-4000-8000-00000000000c', 'https://shop.example/item/42', 'shop item 42 剪藏', '<p>c</p>', 'c', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')"
        )

    run(_seed_inner())
    return db


def test_f071_scan_find_seed_pairs_and_whitelist_never_returns(client):
    _seed(client)

    scan1 = client.post("/api/v1/library/duplicates/scan")
    assert scan1.status_code == 200, scan1.text
    body = scan1.json()
    assert body["created"] >= 1  # 种子对被找到

    queue = client.get("/api/v1/library/duplicates", params={"status": "pending"}).json()["items"]
    refs = {(p["aRef"], p["bRef"]) for p in queue}
    # 同 normalizeContentUrl 不同源（书签 vs 剪藏）
    assert ("library:00000000-0000-4000-8000-00000000000a", "library:00000000-0000-4000-8000-00000000000c") in refs
    # 标题 Jaccard 对（同标题异 URL）
    assert ("library:00000000-0000-4000-8000-00000000000a", "library:00000000-0000-4000-8000-00000000000e") in refs
    # 完全不同标题/不同 URL 不配对
    assert all("00000000-0000-4000-8000-00000000000b" not in pair and "00000000-0000-4000-8000-00000000000d" not in pair for pair in refs)

    # 白名单一对 → 重新扫描不重现（该对不再 pending）
    pair = next(p for p in queue if p["aRef"] == "library:00000000-0000-4000-8000-00000000000a" and p["bRef"] == "library:00000000-0000-4000-8000-00000000000c")
    assert (
        client.post(f"/api/v1/library/duplicates/{pair['id']}/whitelist").status_code
        == 200
    )
    client.post("/api/v1/library/duplicates/scan")
    pending2 = client.get("/api/v1/library/duplicates", params={"status": "pending"}).json()["items"]
    assert all(not (p["aRef"] == "library:00000000-0000-4000-8000-00000000000a" and p["bRef"] == "library:00000000-0000-4000-8000-00000000000c") for p in pending2)


def test_f071_confirm_creates_duplicate_relation(client):
    _seed(client)
    client.post("/api/v1/library/duplicates/scan")
    queue = client.get("/api/v1/library/duplicates", params={"status": "pending"}).json()["items"]
    pair = queue[0]
    confirmed = client.post(f"/api/v1/library/duplicates/{pair['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    # item_relations kind='duplicate' 已建立（双向可查）
    relations = run(
        __import__("lumirss.item_relations", fromlist=["ItemRelationStore"])
        .ItemRelationStore(app.state.db)
        .list_for_item(pair["aRef"])
    )
    assert any(r["kind"] == "duplicate" and {r["srcRef"], r["dstRef"]} == {pair["aRef"], pair["bRef"]} for r in relations)

    # 不存在的对 → 404
    assert (
        client.post("/api/v1/library/duplicates/nope/confirm").status_code == 404
    )


def test_f071_rescan_idempotent_status_persists_no_auto_delete(client):
    _seed(client)
    first = client.post("/api/v1/library/duplicates/scan").json()
    second = client.post("/api/v1/library/duplicates/scan").json()
    # 幂等：第二次扫描不再新增
    assert second["created"] == 0
    assert second["pending"] == first["pending"]

    # ignore 一对 → 状态保留（重启持久：同一 DB 再次进入仍可读）
    queue = client.get("/api/v1/library/duplicates", params={"status": "pending"}).json()["items"]
    target = queue[0]
    client.post(f"/api/v1/library/duplicates/{target['id']}/ignore")

    from fastapi.testclient import TestClient

    # 0067：重启（新 TestClient）的 lifespan 会把 app.state.db 重绑成
    # RoutingDatabase——先捕获普通 Database 句柄，启动后再覆盖回去
    #（与 conftest client fixture 同一约定）。
    plain_db = app.state.db
    with TestClient(app) as client2:
        client2.app.state.db = plain_db
        pairs = client2.get("/api/v1/library/duplicates", params={"status": "ignored"}).json()["items"]
        assert any(p["id"] == target["id"] for p in pairs)
        assert all(p["status"] == "ignored" for p in pairs)

    # 负向：扫描/审核从不删除任何条目
    async def _count():
        row = await app.state.db.fetch_one(
            "SELECT COUNT(*) AS n FROM library_bookmarks"
        )
        return int(row["n"])

    assert asyncio.run(_count()) == 4  # 4 条书签全部健在（剪藏在另一表）
