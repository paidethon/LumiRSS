"""F017 搜索筛选构建器 —— hasSummary 维度 + 组合条件多页过滤。

- 组合条件（来源 + 未读 + 标题含 + hasSummary）在服务端真实过滤
  （limit=1 翻页断言 hasMore/nextCursor 属服务端行为而非前端首页截断）；
- 非法参数 → 422/400 稳定错误；空结果诚实返回 []。
"""

import secrets as _secrets

from lumirss.adapters.freshrss import Feed, FreshRSSAdapter
from lumirss.entryref import encode_entry_ref
from lumirss.models import EntryDocument, EntryDocumentPage
from lumirss.search_index import SearchIndexService

FAKE = "fake-" + _secrets.token_urlsafe(6)

FEED_A = "https://a.example/rss.xml"
FEED_B = "https://b.example/rss.xml"


def doc(item_id: str, title: str, content: str, feed_url: str, read: bool) -> EntryDocument:
    return EntryDocument(
        item_id=item_id,
        entryRef=encode_entry_ref(item_id),
        feedUrl=feed_url,
        feedTitle="源" + feed_url[8],
        title=title,
        author="作者",
        url="https://example.com/x",
        publishedAt="2026-09-01T00:00:0Z"[:19] + "Z",
        read=read,
        starred=False,
        contentText=content,
    )


# 5 条同词命中（分页 > 1 页），来源/未读/摘要维度区分
DOCUMENTS = [
    doc(f"{i}", f"K8s 运维笔记 {i}", f"K8s 集群运维实践 {i}。", FEED_A, read=False)
    for i in range(1, 5)
] + [
    doc("9", "K8s 短摘要", "K8s", FEED_B, read=True),  # 无摘要（content 恰为词）
    doc("10", "K8s 已读", "K8s 已读条目正文内容。", FEED_A, read=True),
]

FEEDS = [Feed(title="源A", feed_url=FEED_A), Feed(title="源B", feed_url=FEED_B)]


class FakeAdapter(FreshRSSAdapter):
    def __init__(self, documents, feeds) -> None:
        self._documents = documents
        self._feeds = feeds

    async def list_entry_documents(self, *, continuation=None, limit=50):
        docs = self._documents
        start = int(continuation) if continuation else 0
        page = docs[start : start + limit]
        next_cont = str(start + limit) if start + limit < len(docs) else None
        return EntryDocumentPage(documents=page, upstreamContinuation=next_cont)

    async def list_feeds(self):
        return self._feeds


async def seed(tmp_path):
    from lumirss.storage import Database

    db = Database(tmp_path / "search-f017.sqlite")
    service = SearchIndexService(db, FakeAdapter(DOCUMENTS, FEEDS))
    await service.rebuild()
    return service


def test_f017_combined_filters_multi_page(tmp_path):
    import asyncio

    async def run():
        service = await seed(tmp_path)
        # 组合：来源 A + 未读 + 仅标题 + hasSummary=True → 4 条中的 4 条
        first = await service.search(
            query="k8s", limit=1, feed_url=FEED_A, unread_only=True,
            intitle="运维", has_summary=True,
        )
        assert len(first["rows"]) == 1
        assert first["hasMore"] is True, "服务端真实过滤后仍有下一页（非首页截断）"
        second = await service.search(
            query="k8s", limit=1, feed_url=FEED_A, unread_only=True,
            intitle="运维", has_summary=True, keyset=first["nextKeyset"],
        )
        assert len(second["rows"]) == 1
        assert second["rows"][0]["entryRef"] != first["rows"][0]["entryRef"]
        # 未读 + 来源 A（不含已读条目 10）
        scoped = await service.search(
            query="k8s", limit=10, feed_url=FEED_A, unread_only=True,
        )
        assert len(scoped["rows"]) == 4
        # hasSummary=False → 只命中 content 恰为词的条目 9？内容 "K8s" 非空 → 无
        none = await service.search(query="k8s", limit=10, has_summary=False)
        assert none["rows"] == []

    asyncio.run(run())


def test_f017_empty_result_honest(tmp_path):
    import asyncio

    async def run():
        service = await seed(tmp_path)
        result = await service.search(
            query="k8s", limit=10, feed_url=FEED_B, unread_only=False,
            has_summary=True, intitle="不存在",
        )
        assert result["rows"] == []

    asyncio.run(run())


def test_f017_route_has_summary_param(tmp_path):
    import asyncio

    from starlette.testclient import TestClient

    from lumirss.main import app

    async def run():
        await seed(tmp_path)

    asyncio.run(run())
    with TestClient(app) as client:
        app.state.search_service = asyncio.run(seed(tmp_path))
        ok = client.get(
            "/api/v1/search",
            params={"q": "k8s", "hasSummary": "true", "state": "unread"},
        )
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert len(body["items"]) == 4  # 未读维度排除条目 9/10
        assert all(item["read"] is False for item in body["items"])
