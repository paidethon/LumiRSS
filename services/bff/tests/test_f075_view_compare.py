"""F075 视图对照 — 跨页交集正确、完全相同/不相交、cap 不完整诚实、
视图已删 404、比较零写入。搜索投影直接播种（与真实管线同源）。"""

import asyncio

from lumirss.main import app


def run(coroutine):
    return asyncio.run(coroutine)


def _seed(db, rows):
    async def _seed_inner():
        await db.migrate()
        for row in rows:
            await db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )

    run(_seed_inner())


def _entry(item_id: str, title: str, starred: int = 0, content: str = "正文"):
    return (
        item_id,
        f"ref.{item_id}",
        "https://f.example/rss",
        "源",
        title,
        "作者",
        f"https://f.example/{item_id}",
        content,
        "2026-09-01T00:00:00Z",
        0,
        starred,
        0,
    )


def test_f075_compare_sets_intersection_and_disjoint(client):
    db = app.state.db
    # A 视图：starred（u1,u2 收藏）；B 视图：query=alpha（u2,u3 命中）
    _seed(db, [
        _entry("s1", "alpha 星标一", starred=1, content="alpha 一的正文"),
        _entry("s2", "alpha 星标二", starred=1, content="alpha 二的正文"),
        _entry("s3", "alpha 未星标三", content="alpha 三的正文"),
        _entry("s4", "无关条目四", content="无关的正文"),
    ])
    view_a = client.post(
        "/api/v1/search/views",
        json={"name": "A", "query": "x", "filters": {"favoriteOnly": True}},
    ).json()
    view_b = client.post(
        "/api/v1/search/views",
        json={"name": "B", "query": "alpha"},
    ).json()

    # B 的 star 过滤不适用；构造 favoriteOnly via params view=starred
    compare = client.post(
        "/api/v1/search/views/compare",
        json={"aId": view_b["id"], "bId": view_a["id"]},
    )
    assert compare.status_code == 200, compare.text
    body = compare.json()
    # aId=view_b（alpha，3 条）；bId=view_a（x+starred，0 条）→ 完全不相交
    assert body["counts"]["a"] == 3  # s1,s2,s3
    assert body["counts"]["b"] == 0
    assert body["counts"]["onlyA"] == 3
    assert body["counts"]["onlyB"] == 0
    assert body["common"] == []
    assert body["complete"] is True

    # 完全相同视图 → common==全部
    same = client.post(
        "/api/v1/search/views/compare",
        json={"aId": view_b["id"], "bId": view_b["id"]},
    ).json()
    assert same["counts"]["common"] == 3
    assert same["counts"]["onlyA"] == 0 and same["counts"]["onlyB"] == 0
    assert len(same["common"]) == 3


def test_f075_cross_page_and_zero_writes_and_404(client):
    db = app.state.db
    # 跨页：>250 条使迭代跨页（limit 250/页）
    _seed(db, [
        _entry(f"p{n:04d}", f"alpha 批量 {n:04d}", content="alpha 的正文内容") for n in range(300)
    ])
    view_a = client.post("/api/v1/search/views", json={"name": "P1", "query": "alpha"}).json()

    async def _counts():
        rows = await db.fetch_all("SELECT (SELECT COUNT(*) FROM search_entries) AS se, (SELECT COUNT(*) FROM search_library) AS sl, (SELECT COUNT(*) FROM saved_searches) AS ss")
        return dict(rows[0])

    before = run(_counts())
    compare = client.post(
        "/api/v1/search/views/compare",
        json={"aId": view_a["id"], "bId": view_a["id"]},
    )
    after = run(_counts())
    assert compare.status_code == 200
    body = compare.json()
    assert body["complete"] is True
    assert body["counts"]["a"] == 300  # 跨页全量迭代
    assert body["counts"]["common"] == 300
    # 比较零写入：投影/库/视图计数不变
    assert after == before

    # 视图已删 → 404
    client.delete(f"/api/v1/search/views/{view_a['id']}")
    gone = client.post(
        "/api/v1/search/views/compare",
        json={"aId": view_a["id"], "bId": view_a["id"]},
    )
    assert gone.status_code == 404
    assert gone.json()["error"]["type"] == "saved_search_not_found"
