"""N031 文章修订差异 — 同 id 内容哈希变化的修订捕获 / 上限 / API。

主路径：FreshRSS 适配器替身（FakeAdapter）→ SearchIndexService 增量同步
→ replace_entries 捕获修订。断言：
- 修订行有有意义的结构差异摘要（retained_variant 基准 + 摘录）；
- 每条目最多 5 条修订（插入时剪枝）；
- 修订行绝不携带全文副本（秘密标记 grep + 行负载上界）。
"""

import asyncio

import pytest

from lumirss.entry_intake import content_hash
from lumirss.entryref import InvalidEntryReference, decode_entry_ref
from lumirss.models import EntryDocument, EntryDocumentPage
from lumirss.search_index import SearchIndexService

REF_SECRET = "nd031-full-content-marker-绝不入库"


def doc(item_id: str, title: str, html: str, *, published_at="2026-09-01T00:00:00Z"):
    return EntryDocument(
        item_id=item_id,
        entryRef=f"e1.{item_id}",
        feedUrl="https://example.com/feed.xml",
        feedTitle="Example",
        title=title,
        author=None,
        url="https://example.com/a",
        publishedAt=published_at,
        read=False,
        starred=False,
        contentText="body",
        contentHtml=html,
    )


class FakeAdapter:
    """单页 FreshRSS 适配器替身：每次调用返回当前 documents。"""

    def __init__(self, documents):
        self.documents = documents

    async def list_entry_documents(self, *, continuation=None, limit=50):
        return EntryDocumentPage(documents=list(self.documents), upstreamContinuation=None)

    async def list_feeds(self):
        return []


def make_service(tmp_path, documents):
    from lumirss.storage import Database

    db = Database(tmp_path / "nd031.sqlite")
    return SearchIndexService(db, FakeAdapter(documents)), db


V1_HTML = (
    "<h2>标题一</h2><p>第一段完整内容。</p>"
    "<h2>标题二</h2><p>第二段带 <a href='https://e.example/x'>链接</a>。</p>"
)
V2_HTML = (
    "<h2>标题一</h2><p>第一段被修订过的内容。</p>"
    "<p>新增的第三段。</p>"
)


def test_revision_captured_with_meaningful_summary(tmp_path):
    service, db = make_service(tmp_path, [doc("i1", "原标题", V1_HTML)])
    asyncio.run(service.sync_incremental())
    # 同一 id 重新交付：内容修改 + 标题未变
    service._adapter = FakeAdapter([doc("i1", "原标题", V2_HTML)])
    report = asyncio.run(service.sync_incremental())
    assert report["updated"] == 1, "内容哈希变化必须被增量同步识别"

    async def _read():
        rows = await db.fetch_all("SELECT * FROM entry_revisions WHERE entry_ref = 'e1.i1'")
        return rows

    rows = asyncio.run(_read())
    assert len(rows) == 1
    row = rows[0]
    import json

    summary = json.loads(row["content_diff_summary"])
    assert summary["basis"] == "retained_variant"
    assert summary["paragraphsChanged"] == 0, "两版各 2 段：1 段修订 + 1 段新增 - 1 段消失"
    assert summary["headingsChanged"] == -1
    assert "第一段" in summary["excerptPrev"] or "第一段" in summary["excerptNew"], (
        "首个差异段摘录必须可见"
    )
    assert row["title_changed"] == 0
    assert row["prev_hash"] == content_hash(V1_HTML)
    assert row["new_hash"] == content_hash(V2_HTML)


def test_revision_cap_five_pruned_on_insert(tmp_path):
    service, db = make_service(
        tmp_path, [doc("i1", "标题", "<p>v0</p>")]
    )
    asyncio.run(service.sync_incremental())
    for version in range(1, 9):  # 8 次内容变化
        service._adapter = FakeAdapter(
            [doc("i1", "标题", f"<p>版本 {version} 的内容</p>")]
        )
        asyncio.run(service.sync_incremental())

    async def _read():
        rows = await db.fetch_all(
            "SELECT new_hash FROM entry_revisions WHERE entry_ref = 'e1.i1' ORDER BY id DESC"
        )
        count = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM entry_revisions WHERE entry_ref = 'e1.i1'"
        )
        return rows, int(count["n"])

    rows, count = asyncio.run(_read())
    assert count == 5, "cap 5：旧修订在插入时剪枝"
    newest_hash = content_hash("<p>版本 8 的内容</p>")
    assert rows[0]["new_hash"] == newest_hash, "保留最新的修订"


def test_revision_rows_never_carry_full_content(tmp_path):
    # v1 = 1 段独特开头 + 200 段填充正文（完整内容远大于任何摘录上界）。
    filler = "<p>普通填充段落内容。</p>" * 200
    v1_html = f"<p>{REF_SECRET} 独有的开头段落。</p>{filler}"
    service, db = make_service(tmp_path, [doc("i1", "原标题", v1_html)])
    asyncio.run(service.sync_incremental())
    service._adapter = FakeAdapter(
        [doc("i1", "原标题", "<p>修订后的完全不同内容。</p>")]
    )
    asyncio.run(service.sync_incremental())

    async def _read():
        return await db.fetch_all("SELECT * FROM entry_revisions")

    rows = asyncio.run(_read())
    assert len(rows) == 1
    row = rows[0]
    payload = "".join(
        str(row[key] or "")
        for key in (
            "captured_at",
            "prev_title",
            "new_title",
            "content_diff_summary",
            "prev_hash",
            "new_hash",
        )
    )
    assert len(payload) < 4000, "修订行是元数据行（有界负载），不是内容副本"
    assert "普通填充段落内容" not in payload, "正文填充段绝不进入修订行"
    assert payload.count(REF_SECRET) <= 1, "至多出现首个差异段的 ≤200 字摘录"


def test_unchanged_delivery_writes_no_revision(tmp_path):
    service, db = make_service(tmp_path, [doc("i1", "标题", V1_HTML)])
    asyncio.run(service.sync_incremental())
    asyncio.run(service.sync_incremental())  # 完全相同的交付

    async def _count():
        row = await db.fetch_one("SELECT COUNT(*) AS n FROM entry_revisions")
        return int(row["n"])

    assert asyncio.run(_count()) == 0


# -- API：GET /api/v1/entries/{ref}/revisions --------------------------------


def test_revisions_route_shape_and_validation(client, tmp_path, monkeypatch):

    from lumirss.entryref import encode_entry_ref

    async def _seed():
        db = client.app.state.db
        await db.migrate()
        await db.execute(
            "INSERT INTO entry_revisions (entry_ref, captured_at, title_changed, prev_title, new_title, content_diff_summary, prev_hash, new_hash) VALUES ('e1.aTE', '2026-09-20T00:00:00Z', 1, '旧题', '新题', '{\"basis\":\"retained_variant\",\"headingsChanged\":0,\"paragraphsChanged\":1,\"linksChanged\":0,\"excerptPrev\":\"旧段\",\"excerptNew\":\"新段\"}', 'aa', 'bb')"
        )

    asyncio.run(_seed())
    ref = encode_entry_ref("i1")
    response = client.get(f"/api/v1/entries/{ref}/revisions")
    assert response.status_code == 200
    body = response.json()
    assert body["entryRef"] == ref
    assert len(body["revisions"]) == 1
    rev = body["revisions"][0]
    assert rev["titleChanged"] is True
    assert rev["summary"]["excerptNew"] == "新段"
    assert rev["capturedAt"] == "2026-09-20T00:00:00Z"

    # 未修订过的条目 → 空表 200（不臆造）
    empty = client.get(f"/api/v1/entries/{encode_entry_ref('never-seen')}/revisions")
    assert empty.status_code == 200
    assert empty.json()["revisions"] == []

    # 非法 ref → 400
    bad = client.get("/api/v1/entries/not-a-ref/revisions")
    assert bad.status_code == 400


def test_decode_entry_ref_still_guards():  # noqa: ARG001 - sanity guard
    with pytest.raises(InvalidEntryReference):
        decode_entry_ref("../../escape")
