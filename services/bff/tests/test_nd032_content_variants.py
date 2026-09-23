"""N032 内容丢失恢复选择 — content_variants 触发 / 保留版本 / API。

- 当前内容 < 历史最大内容 40% → 详情响应携带 contentVariants 块
  （current + 保留的 last_known_full）；
- 正常长度不触发；
- 保留版本 ≤200KB（keep_latest=1，单行轮转）；超限不保留（诚实降级）；
- 变体 HTML 仍是不可信上游内容 —— Web 渲染经同一 DOMPurify 边界
  （对应 Web 测试见 apps/web src/__tests__）。
"""

import asyncio

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail, EntryDocument, EntryDocumentPage
from lumirss.search_index import SearchIndexService


def doc(item_id: str, html: str):
    from lumirss.entryref import encode_entry_ref

    return EntryDocument(
        item_id=item_id,
        entryRef=encode_entry_ref(item_id),
        feedUrl="https://example.com/feed.xml",
        feedTitle="Example",
        title="T",
        author=None,
        url="https://example.com/a",
        publishedAt="2026-09-01T00:00:00Z",
        read=False,
        starred=False,
        contentText="body",
        contentHtml=html,
    )


class FakeAdapter:
    def __init__(self, documents):
        self.documents = documents

    async def list_entry_documents(self, *, continuation=None, limit=50):
        return EntryDocumentPage(documents=list(self.documents), upstreamContinuation=None)

    async def list_feeds(self):
        return []


def make_service(db, documents):
    return SearchIndexService(db, FakeAdapter(documents)), db


LONG_HTML = "".join(f"<p>这是第 {i} 段完整正文，内容足够长。</p>" for i in range(40))
SHORT_HTML = "<p>只剩一小段摘要。</p>"


def test_shortening_triggers_variants_block(client, tmp_path):
    service, db = make_service(client.app.state.db, [doc("i1", LONG_HTML)])
    asyncio.run(service.sync_incremental())
    service._adapter = FakeAdapter([doc("i1", SHORT_HTML)])
    asyncio.run(service.sync_incremental())
    # 详情路由读 app.state.db —— 与服务同一个库（client 夹具的临时库）。
    app.state.db = db

    detail = EntryDetail(
        entryRef=encode_entry_ref("i1"),
        title="T",
        feedTitle="Example",
        read=False,
        starred=False,
        contentText="正文",
        contentHtml=SHORT_HTML,
    )

    async def _detail_route():
        app.state.freshrss_adapter = _DetailFake(detail)
        try:
            response = client.get(f"/api/v1/entries/{encode_entry_ref('i1')}")
        finally:
            app.state.freshrss_adapter = None
        return response

    response = asyncio.run(_detail_route())
    assert response.status_code == 200
    block = response.json()["contentVariants"]
    assert block is not None, "明显变短必须触发 contentVariants"
    assert block["triggered"] is True
    assert block["currentLength"] == len(SHORT_HTML)
    assert block["maxLength"] == len(LONG_HTML)
    kinds = {v["kind"]: v for v in block["variants"]}
    assert kinds["current"]["contentHtml"] == SHORT_HTML
    assert kinds["last_known_full"]["contentHtml"] == LONG_HTML
    assert kinds["last_known_full"]["capturedAt"], "保留版本必须带捕获时间"


class _DetailFake:
    def __init__(self, detail):
        self.detail = detail

    async def get_entry(self, item_id):
        return self.detail


def test_normal_length_never_triggers(client, tmp_path):
    service, db = make_service(client.app.state.db, [doc("i1", LONG_HTML)])
    asyncio.run(service.sync_incremental())
    # 相同长度量级的正常更新（哈希变化但不明显变短）
    service._adapter = FakeAdapter([doc("i1", LONG_HTML + "<p>补充段落。</p>")])
    asyncio.run(service.sync_incremental())
    app.state.db = db

    detail = EntryDetail(
        entryRef=encode_entry_ref("i1"),
        title="T",
        feedTitle="Example",
        read=False,
        starred=False,
        contentText="正文",
        contentHtml=LONG_HTML,
    )
    app.state.freshrss_adapter = _DetailFake(detail)
    try:
        response = client.get(f"/api/v1/entries/{encode_entry_ref('i1')}")
    finally:
        app.state.freshrss_adapter = None
    assert response.status_code == 200
    assert response.json()["contentVariants"] is None, "正常长度绝不触发"


def test_variant_side_table_bounded_and_rotated(tmp_path):
    from lumirss.storage import Database

    ref = encode_entry_ref("i1")
    service, db = make_service(Database(tmp_path / "nd032b.sqlite"), [doc("i1", "x" * 500)])
    asyncio.run(service.sync_incremental())

    async def _counts():
        rows = await db.fetch_all("SELECT entry_ref FROM entry_content_variants")
        return rows

    assert len(asyncio.run(_counts())) == 1, "keep_latest=1：每条目至多一行"

    # 更长版本 → 轮转（仍一行，内容更新）；更短版本 → 不覆盖保留版本
    service._adapter = FakeAdapter([doc("i1", "y" * 900)])
    asyncio.run(service.sync_incremental())

    async def _content():
        row = await db.fetch_one(
            "SELECT content_html FROM entry_content_variants WHERE entry_ref = ?",
            (ref,),
        )
        return str(row["content_html"])

    assert asyncio.run(_content()) == "y" * 900
    service._adapter = FakeAdapter([doc("i1", "short")])
    asyncio.run(service.sync_incremental())
    assert asyncio.run(_content()) == "y" * 900, "更短交付不覆盖保留的完整版本"


def test_variant_byte_cap_honest_degradation(tmp_path):
    from lumirss.storage import Database

    huge = "z" * (200 * 1024 + 1)  # 超过 200KB 上限 1 字节
    service, db = make_service(Database(tmp_path / "nd032c.sqlite"), [doc("i1", huge)])
    asyncio.run(service.sync_incremental())

    async def _state():
        row = await db.fetch_one(
            "SELECT content_max_len FROM search_entries WHERE item_id = 'i1'"
        )
        count = await db.fetch_one("SELECT COUNT(*) AS n FROM entry_content_variants")
        return int(row["content_max_len"]), int(count["n"])

    max_len, variant_rows = asyncio.run(_state())
    assert max_len == len(huge), "最大长度照常记录"
    assert variant_rows == 0, "超限版本不保留（诚实降级：仅当前可选）"

    # 之后明显变短：块触发，但 last_known_full 缺席（未保留即如实缺席）
    service._adapter = FakeAdapter([doc("i1", SHORT_HTML)])
    asyncio.run(service.sync_incremental())
    from lumirss.entry_history import EntryHistoryStore

    block = asyncio.run(
        EntryHistoryStore(db).variants_block(
            encode_entry_ref("i1"), current_html=SHORT_HTML
        )
    )
    assert block is not None and block.triggered is True
    kinds = [v.kind for v in block.variants]
    assert kinds == ["current"], "未保留长版本 → 只提供当前（不臆造）"
