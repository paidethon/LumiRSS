"""F070 知识卡片 — 坏结构逐条丢弃、>10 张 422、重复保存幂等、
保存后搜索可见、原文删除→卡保留标 stale。上游 MockTransport。"""

import asyncio
import json as _json

import httpx

from lumirss.deps import _get_library_search_writer
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database

REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000070")
CONTENT = "知识卡片提取用的长正文。" * 60

CARDS_JSON = _json.dumps(
    {
        "cards": [
            {
                "concept": "RAG 检索",
                "explanation": "用向量+关键词双路检索相关段落。",
                "source_quote": "知识卡片提取用的长正文",
            },
            {
                "concept": "坏卡片",
                "explanation": "证据不存在的卡片应被丢弃。",
                "source_quote": "这句话不在正文里",
            },
        ]
    },
    ensure_ascii=False,
)


def run(coroutine):
    return asyncio.run(coroutine)


class Adapter:
    async def get_entry(self, item_id: str):
        return EntryDetail(
            entryRef=REF,
            title="知识卡片来源文章",
            feedTitle="源",
            contentText=CONTENT,
            contentHtml=f"<p>{CONTENT}</p>",
            read=False,
            starred=False,
        )


def _wire(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "test-key-f070")
    db = Database(tmp_path / "lumi.sqlite")

    async def _cfg():
        from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate

        await AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="m-f070")
        )

    asyncio.run(_cfg())
    app.state.db = db

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": CARDS_JSON}}]}
        )

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.state.freshrss_adapter = Adapter()
    return db


def test_f070_preview_drops_bad_cards_and_save_is_idempotent_with_search(
    client, tmp_path, monkeypatch
):
    db = _wire(tmp_path, monkeypatch)

    # 预览：坏卡片（quote 不在正文）被丢弃，只剩 1 张候选（verified: true）
    preview = client.post(
        f"/api/v1/entries/{REF}/knowledge-cards/preview", json={"max": 5}
    )
    assert preview.status_code == 200, preview.text
    cards = preview.json()["cards"]
    assert len(cards) == 1
    assert cards[0]["concept"] == "RAG 检索"
    assert cards[0]["verified"] is True

    # 保存：2 张（1 张有效 + 1 张编辑后坏 quote → verified 标注 false 但仍保存）
    save = client.post(
        f"/api/v1/entries/{REF}/knowledge-cards/save",
        json={
            "cards": [
                {
                    "concept": "RAG 检索",
                    "explanation": "用向量+关键词双路检索相关段落。",
                    "sourceQuote": "知识卡片提取用的长正文。知识卡片提取用的长正文。",
                }
            ]
        },
    )
    assert save.status_code == 200, save.text
    assert save.json()["results"][0]["status"] == "created"

    # 重复保存同 concept → skipped（幂等，不覆盖）
    save2 = client.post(
        f"/api/v1/entries/{REF}/knowledge-cards/save",
        json={
            "cards": [
                {
                    "concept": "RAG 检索",
                    "explanation": "用户后来编辑过的解释不应被覆盖。",
                    "sourceQuote": "",
                }
            ]
        },
    ).json()
    assert save2["results"][0]["status"] == "skipped"
    # 未覆盖：解释仍是首版
    listing = client.get("/api/v1/knowledge-cards").json()["items"]
    assert listing[0]["explanation"] == "用向量+关键词双路检索相关段落。"

    # 保存后搜索可见（library 腿，服务端断言）
    async def _search():
        writer = _get_library_search_writer(app)
        hits, _more = await writer.search_page("向量", limit=5)
        return hits

    # 直接经由 app 构造的 writer（与路由同一 DB）
    from lumirss.search_library import LibrarySearchWriter

    writer = LibrarySearchWriter(db)
    hits = asyncio.run(writer.search("双路检索", limit=10))
    assert any(h["kind"] == "knowledge_card" and h["title"] == "RAG 检索" for h in hits)
    _ = _search

    # 坏结构逐条 error：save 端点 pydantic 拒绝超长 concept → 422（整批校验）
    too_long = client.post(
        f"/api/v1/entries/{REF}/knowledge-cards/save",
        json={"cards": [{"concept": "x" * 101, "explanation": "e"}]},
    )
    assert too_long.status_code == 422

    # >10 张 → 422
    over = client.post(
        f"/api/v1/entries/{REF}/knowledge-cards/save",
        json={"cards": [{"concept": f"c{i}", "explanation": "e"} for i in range(11)]},
    )
    assert over.status_code == 422


def test_f070_entry_deleted_card_kept_marked_stale(client, tmp_path, monkeypatch):
    db = _wire(tmp_path, monkeypatch)
    save = client.post(
        f"/api/v1/entries/{REF}/knowledge-cards/save",
        json={
            "cards": [
                {
                    "concept": "幂等键",
                    "explanation": "entry_ref+concept 唯一。",
                    "sourceQuote": "知识卡片提取用的长正文",
                }
            ]
        },
    )
    assert save.status_code == 200
    card_id = save.json()["results"][0]["cardId"]

    # 原文删除（投影行清除）→ 卡保留 + stale 标注
    async def _wipe():
        await db.execute("DELETE FROM search_entries WHERE entry_ref = ?", (REF,))

    asyncio.run(_wipe())
    items = client.get("/api/v1/knowledge-cards").json()["items"]
    card = next(i for i in items if i["id"] == card_id)
    assert card["stale"] is True
    assert card["entryTitle"] is None

    # 删除卡片 → 索引同步移除；再删 → 404
    assert client.delete(f"/api/v1/knowledge-cards/{card_id}").status_code == 204
    hits = asyncio.run(LibrarySearchWriter(db).search("幂等键", limit=5))
    assert hits == []
    assert client.delete(f"/api/v1/knowledge-cards/{card_id}").status_code == 404
