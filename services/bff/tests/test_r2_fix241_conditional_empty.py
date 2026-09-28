"""FIX-241 — 「缓存验证成功」式空响应不得当空 feed 覆盖已有文章。

场景：投影重建（refresh）时上游对条件请求答「内容未变」——在 greader
投影里的形态是：一页零条目 + 无 continuation。旧实现会把这次重建
swap 成空投影：所有已收录文章被清空（HTTP 304 被当成空 feed 覆盖）。

承诺：空收获 + 非空既有投影 = 缓存验证成功——保留旧内容，仅记录
检查时间（last_synced_at），清除 rebuild_incomplete；真空库仍按空
投影如实重建。报告如实区分（keptExisting）。
"""

import secrets as _secrets

import pytest

from lumirss.adapters.freshrss import Feed, FreshRSSAdapter
from lumirss.entryref import encode_entry_ref
from lumirss.models import EntryDocument, EntryDocumentPage
from lumirss.search_index import SearchIndexService

FAKE = "fake-" + _secrets.token_urlsafe(6)

FEEDS = [Feed(title="示例源", feed_url="https://feed.example/rss.xml")]


def doc(item_id: str, title: str) -> EntryDocument:
    return EntryDocument(
        item_id=item_id,
        entryRef=encode_entry_ref(item_id),
        feedUrl="https://feed.example/rss.xml",
        feedTitle="示例源",
        title=title,
        author=None,
        url="https://example.com/x",
        publishedAt="2026-09-01T00:00:00Z",
        read=False,
        starred=False,
        contentText="body " + title,
    )


class ConditionalAdapter(FreshRSSAdapter):
    """先交付两篇条目；置空后表现为「缓存验证成功」的空流。"""

    def __init__(self) -> None:
        self.documents: list[EntryDocument] = [
            doc("item-1", "第一篇"),
            doc("item-2", "第二篇"),
        ]

    async def list_entry_documents(self, *, continuation=None, limit=50):
        if continuation is not None:
            return EntryDocumentPage(documents=[], upstreamContinuation=None)
        if self.documents:
            return EntryDocumentPage(
                documents=list(self.documents), upstreamContinuation=None
            )
        return EntryDocumentPage(documents=[], upstreamContinuation=None)

    async def list_feeds(self):
        return FEEDS


def make_service(tmp_path, adapter) -> SearchIndexService:
    from lumirss.storage import Database

    return SearchIndexService(Database(str(tmp_path / f"fix241-{FAKE[:6]}.sqlite")), adapter)


@pytest.mark.anyio
async def test_fix241_empty_validation_response_keeps_articles_and_records_check(tmp_path):
    adapter = ConditionalAdapter()
    service = make_service(tmp_path, adapter)

    first = await service.rebuild()
    assert first["entryCount"] == 2
    assert await service.entry_count() == 2

    # 上游「内容未变」：空页、无 continuation（304 语义的投影形态）。
    adapter.documents = []
    second = await service.rebuild()

    assert second["keptExisting"] is True, "空收获必须如实标注为保留既有内容"
    assert second["entryCount"] == 0, "本次收获 0 篇（诚实统计）"
    assert await service.entry_count() == 2, "既有文章绝不被空响应清空"

    async def meta(key: str) -> str | None:
        return await service._store.meta_get(key)

    # 检查时间已记录；重建状态健康（不卡 incomplete）。
    assert await meta("last_synced_at") is not None
    assert await meta("rebuild_incomplete") == "0"


@pytest.mark.anyio
async def test_fix241_genuinely_empty_index_still_rebuilds_to_empty(tmp_path):
    """空库 + 真空上游：如实建空投影（keptExisting=False），不是异常。"""
    service = make_service(tmp_path, ConditionalAdapter())
    service._adapter.documents = []

    report = await service.rebuild()
    assert report["entryCount"] == 0
    assert report["keptExisting"] is False
    assert await service.entry_count() == 0
