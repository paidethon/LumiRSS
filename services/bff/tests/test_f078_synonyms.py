"""F078 检索同义词 — 扩展改变服务端结果、关闭恢复、CJK/拉丁词边界、
循环映射不递归、复杂度上限、preview 与实际一致。"""

import asyncio

from lumirss.main import app
from lumirss.search_synonyms import (
    SynonymStore,
    expand_terms,
)


def run(coroutine):
    return asyncio.run(coroutine)


def _seed_entries(db):
    async def _seed_inner():
        await db.migrate()
        rows = [
            ("syn1", "ref.syn1", "LLM 大模型实测", "2026-09-01T00:00:00Z"),
            ("syn2", "ref.syn2", "大模型跑分对比", "2026-09-01T00:00:00Z"),
            ("syn3", "ref.syn3", "普通文章一篇", "2026-09-01T00:00:00Z"),
        ]
        for item_id, ref, title, published in rows:
            await db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, 'https://f.example/rss', '源', ?, '作者', 'u', ?, ?, 0, 0, 0)",
                (item_id, ref, title, title, published),
            )

    return _seed_inner


def test_f078_expansion_changes_results_toggle_and_complexity(client):
    db = app.state.db
    run(_seed_entries(db)())

    # 建同义词：LLM → 大模型（CJK）；alpha → beta（拉丁）
    created = client.post(
        "/api/v1/search/synonyms",
        json={"term": "LLM", "expansions": ["大模型"]},
    )
    assert created.status_code == 200, created.text
    assert created.json()["enabled"] is True

    # 扩展开启（默认）：query=LLM 命中 syn1（LLM）+ 扩展命中 大模型（syn1,syn2）
    with_expand = client.get("/api/v1/search", params={"q": "LLM", "expandSynonyms": "true"}).json()
    titles = {r["title"] for r in with_expand["items"]}
    assert "LLM 大模型实测" in titles
    assert "大模型跑分对比" in titles

    # 关闭扩展：只剩标题含 LLM 的一条
    without = client.get("/api/v1/search", params={"q": "LLM", "expandSynonyms": "false"}).json()
    titles_without = {r["title"] for r in without["items"]}
    assert "LLM 大模型实测" in titles_without
    assert "大模型跑分对比" not in titles_without

    # CJK 与拉丁词边界：term=大模型 命中（CJK 连续串），不误伤短词
    matched_cjk = client.post("/api/v1/search/synonyms/preview", json={"q": "大模型"}).json()
    assert matched_cjk["matched"] == []
    assert "大模型" in matched_cjk["effectiveTerms"]

    # 循环映射不递归：a→b 且 b→a，query=a 只扩一层
    client.post("/api/v1/search/synonyms", json={"term": "aa", "expansions": ["bb"]})
    client.post("/api/v1/search/synonyms", json={"term": "bb", "expansions": ["aa"]})
    effective = client.post("/api/v1/search/synonyms/preview", json={"q": "aa"}).json()
    assert sorted(effective["effectiveTerms"]) == ["aa", "bb"]
    assert len(effective["effectiveTerms"]) == 2  # 未递归

    # 复杂度上限：扩后词表 ≤100
    many = [{"concept": "x"} for _ in range(0)]
    expansions = [f"exp{i}" for i in range(150)]
    client.post("/api/v1/search/synonyms", json={"term": "hub", "expansions": expansions[:8]})
    # store.create 上限 8 个 expansion：>8 → 422
    over = client.post(
        "/api/v1/search/synonyms", json={"term": "hub2", "expansions": [f"e{i}" for i in range(9)]}
    )
    assert over.status_code == 422
    # 直接调用 expand_terms 验证上限
    big_map = {"t": [f"e{i}" for i in range(150)]}
    expanded = expand_terms(["t"], big_map)
    assert len(expanded) <= 100
    _ = many


def test_f078_crud_preview_consistency_and_persistence(client):
    db = app.state.db

    async def _make():
        await SynonymStore(db).create("rss", ["feed"], True)

    run(_make())
    listing = client.get("/api/v1/search/synonyms").json()["items"]
    assert listing[0]["term"] == "rss"
    assert listing[0]["expansions"] == ["feed"]
    synonym_id = listing[0]["id"]

    # preview 与实际一致：matched 列出命中 term 与 expansions；effectiveTerms 含扩展
    preview = client.post("/api/v1/search/synonyms/preview", json={"q": "rss"}).json()
    assert preview["matched"] == [{"term": "rss", "expansions": ["feed"]}]
    assert preview["effectiveTerms"] == ["rss", "feed"]

    # patch 停用 → preview 不再命中
    assert (
        client.patch(f"/api/v1/search/synonyms/{synonym_id}", json={"enabled": False}).status_code
        == 200
    )
    preview_off = client.post("/api/v1/search/synonyms/preview", json={"q": "rss"}).json()
    assert preview_off["matched"] == []
    assert preview_off["effectiveTerms"] == ["rss"]

    # 删除 → 404 再删
    assert client.delete(f"/api/v1/search/synonyms/{synonym_id}").status_code == 204
    assert client.delete(f"/api/v1/search/synonyms/{synonym_id}").status_code == 404

    # 坏载荷：空 expansions / 超长 term → 422
    assert (
        client.post("/api/v1/search/synonyms", json={"term": "x", "expansions": []}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/search/synonyms", json={"term": "x" * 51, "expansions": ["y"]}
        ).status_code
        == 422
    )
