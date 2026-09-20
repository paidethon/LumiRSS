"""F066 per-source AI 禁用 — 服务端执行点（非 UI 隐藏）：

- 直接 API 403（summary/translation/conversation，负向：绕过 UI 无效）；
- gpt_digest 选材排除；agent 工具（search/rag_search）结果过滤；
- RAG：禁用后语料页不再产出该来源条目（重建/增量口径），重新启用恢复；
- 不影响 FreshRSS 投影数据（负向：条目原样保留）。
"""

import asyncio
from datetime import datetime

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.source_ai_gate import (
    ai_disabled_feed_set,
    disabled_entry_refs,
    feed_refs,
    set_ai_disabled,
)

REF = encode_entry_ref("tag:google.com,2005:reader/item/00000000000000f6")
FEED = "https://disabled.example/rss"
ARTICLE_TEXT = "这是一篇需要 AI 的文章。" + "正文" * 60


def run(coroutine):
    return asyncio.run(coroutine)


async def _seed(db):
    await db.migrate()
    await db.execute(
        "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES ('f6', ?, ?, '将禁用的源', 'AI 目标文章', '作者', 'https://disabled.example/1', ?, '2026-09-01T00:00:00Z', 0, 0, 0)",
        (REF, FEED, ARTICLE_TEXT),
    )


def test_f066_api_403_for_disabled_source_and_reenable(client):
    db = app.state.db
    run(_seed(db))
    run(set_ai_disabled(db, FEED, True))
    # 判定位与条目判定
    assert FEED in run(ai_disabled_feed_set(db))
    assert run(disabled_entry_refs(db, [REF])) == {REF}

    # summary：403（服务层不应被触达——若触达会因未配置 provider 而非 403）
    resp = client.post(f"/api/v1/entries/{REF}/summary")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["type"] == "ai_disabled_for_source"
    # translation segments
    resp = client.post(
        f"/api/v1/entries/{REF}/translation/segments/generate",
        json={"blocks": [{"index": 0, "text": "hello"}]},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["type"] == "ai_disabled_for_source"
    # conversation
    resp = client.post(
        f"/api/v1/entries/{REF}/conversation/messages",
        json={"question": "这篇讲了什么？"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["type"] == "ai_disabled_for_source"

    # 重新启用 → 判定关闭
    run(set_ai_disabled(db, FEED, False))
    assert run(disabled_entry_refs(db, [REF])) == set()


def test_f066_digest_excludes_disabled_source(client):
    from lumirss.gpt_digest import select_material_for_config

    class Doc:
        def model_dump(self):
            return {
                "item_id": "x",
                "entryRef": "ref-x",
                "feedUrl": FEED,
                "feedTitle": "源",
                "title": "T",
                "url": "https://x/1",
                "publishedAt": "2026-09-10T00:00:00Z",
                "read": False,
                "starred": False,
                "contentText": "正文",
            }

    class Page:
        documents = [Doc()]

    class Adapter:
        async def list_entry_documents(self, limit):
            return Page()

    db = app.state.db
    run(set_ai_disabled(db, FEED, True))
    config = {
        "sourceKind": "window",
        "timezone": "Asia/Shanghai",
        "windowHours": 48,
        "limitCount": 5,
        "perSourceCap": 0,
        "feedUrlAllow": "",
    }
    selected, _counts, _per, _ws, _we, _ex, _pi = run(
        select_material_for_config(config, Adapter(), db, datetime(2026, 9, 11))
    )
    assert selected == []  # 唯一候选来自禁用来源 → 全部排除

    # 负向→恢复：不禁用时同一材料可被选入
    run(set_ai_disabled(db, FEED, False))
    selected2, _c, _p, _ws2, _we2, _ex2, _pi2 = run(
        select_material_for_config(config, Adapter(), db, datetime(2026, 9, 11))
    )
    assert len(selected2) == 1


def test_f066_agent_tools_filter_disabled(client):
    from lumirss.agent_tools import build_registry

    rows = [
        {"entry_ref": REF, "title": "AI 目标文章", "content_text": ARTICLE_TEXT},
        {"entry_ref": "ref-ok", "title": "正常文章", "content_text": "正常正文"},
    ]

    async def rss_search(query, limit=5):
        return list(rows)

    class LibSearch:
        async def search(self, query, limit=5):
            return [
                {
                    "ref": "lib:1",
                    "title": "库条目",
                    "body": "库正文",
                    "updated_at": "2026-09-01T00:00:00Z",
                    "kind": "bookmark",
                }
            ]

    class Rag:
        async def search(self, query, k=6):
            return {
                "items": [
                    {"ref": REF, "text": "禁用来源的块", "score": 0.9},
                    {"ref": "ref-ok", "text": "正常来源的块", "score": 0.8},
                ],
                "semanticUsed": False,
            }

    db = app.state.db
    run(_seed(db))
    run(set_ai_disabled(db, FEED, True))

    registry = build_registry(
        db=db,
        rss_search=rss_search,
        library_search=LibSearch(),
        rag=Rag(),
        adapter=None,
        library=None,
        workspaces=None,
    )
    result = run(registry.invoke_read("search", {"query": "正文"}))
    titles = [r["title"] for r in result["results"]]
    assert "AI 目标文章" not in titles
    assert "正常文章" in titles
    assert REF not in result["citations"]

    rag_result = run(registry.invoke_read("rag_search", {"query": "块"}))
    rag_refs = [r["ref"] for r in rag_result["results"]]
    assert REF not in rag_refs
    assert "ref-ok" in rag_refs


def test_f066_rag_corpus_drop_and_restore_and_rss_untouched(client):
    """禁用 → 语料页不再产出该来源条目；重新启用 → 恢复包含；
    FreshRSS 投影条目不受影响（负向）。"""
    db = app.state.db
    run(_seed(db))

    from lumirss.rag import RagService

    service = RagService.__new__(RagService)  # 仅测 _document_pages（纯读取）
    service._db = db

    async def _collect():
        pages = []
        async for page in service._document_pages():
            pages.extend(page)
        return pages

    run(set_ai_disabled(db, FEED, True))
    assert run(feed_refs(db, FEED)) == [REF]
    docs = run(_collect())
    assert all(d["ref"] != REF for d in docs)

    run(set_ai_disabled(db, FEED, False))
    docs = run(_collect())
    assert any(d["ref"] == REF for d in docs)

    # 负向：FreshRSS 投影条目原样保留（禁用不删任何数据）
    async def _count():
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM search_entries WHERE feed_url = ?", (FEED,)
        )
        return int(row["n"])

    assert run(_count()) == 1
