"""F29 高级搜索条件 — 服务端回归（2026-09 移动端专项）。

验证 intitle（仅标题）/ phrase（精确短语）/ exclude（排除词）真实参与
SQL 检索（绑定参数，非字符串拼接），并通过路由 query param 透传。
"""

import secrets as _secrets

import pytest

from lumirss.adapters.freshrss import Feed, FreshRSSAdapter
from lumirss.entryref import encode_entry_ref
from lumirss.models import EntryDocument, EntryDocumentPage
from lumirss.search_index import SearchIndexService, SearchQueryError

FAKE = "fake-" + _secrets.token_urlsafe(6)


def doc(
    item_id: str,
    title: str,
    content: str,
    author: str = "作者甲",
) -> EntryDocument:
    return EntryDocument(
        item_id=item_id,
        entryRef=encode_entry_ref(item_id),
        feedUrl="https://feed.example/rss.xml",
        feedTitle="示例源",
        title=title,
        author=author,
        url="https://example.com/x",
        publishedAt="2026-09-01T00:00:00Z",
        read=False,
        starred=False,
        contentText=content,
    )


DOCUMENTS = [
    doc("1", "Rust 发布新版本", "Rust 1.80 发布，性能提升明显。"),
    doc("2", "Python 之父访谈", "Guido 谈 Python 的未来与 Rust 的关系。"),
    doc("3", "经济周报", "本周经济数据汇总，无技术内容。"),
]

FEEDS = [Feed(title="示例源", feed_url="https://feed.example/rss.xml")]


class FakeAdapter(FreshRSSAdapter):
    def __init__(self, documents, feeds) -> None:
        # 不调用父类 __init__：纯读路径 double，不建 HTTP 客户端。
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


def make_service(tmp_path) -> SearchIndexService:
    from lumirss.storage import Database

    db = Database(tmp_path / "search-advanced.sqlite")
    return SearchIndexService(db, FakeAdapter(DOCUMENTS, FEEDS))


async def seed(service: SearchIndexService) -> None:
    report = await service.rebuild()
    assert report["entryCount"] == 3


@pytest.mark.anyio
async def test_intitle_restricts_match_to_title(tmp_path):
    service = make_service(tmp_path)
    await seed(service)
    # "rust" 只在标题命中：文档 1；文档 2 正文含 Rust 但标题无 → 排除。
    result = await service.search(query="rust", limit=10, intitle="rust")
    titles = [row["title"] for row in result["rows"]]
    assert titles == ["Rust 发布新版本"]


@pytest.mark.anyio
async def test_phrase_requires_exact_substring(tmp_path):
    service = make_service(tmp_path)
    await seed(service)
    hit = await service.search(query="周报", limit=10, phrase="经济数据汇总")
    assert len(hit["rows"]) == 1
    miss = await service.search(query="周报", limit=10, phrase="汇总经济数据")
    assert len(miss["rows"]) == 0  # 词序不同 ≠ 短语命中


@pytest.mark.anyio
async def test_exclude_removes_hits(tmp_path):
    service = make_service(tmp_path)
    await seed(service)
    base = await service.search(query="rust", limit=10)
    assert len(base["rows"]) == 2
    filtered = await service.search(query="rust", limit=10, exclude="访谈")
    assert [row["title"] for row in filtered["rows"]] == ["Rust 发布新版本"]


@pytest.mark.anyio
async def test_advanced_conditions_combine(tmp_path):
    service = make_service(tmp_path)
    await seed(service)
    result = await service.search(
        query="rust", limit=1, intitle="rust", exclude="访谈"
    )
    assert len(result["rows"]) == 1
    assert result["hasMore"] is False


@pytest.mark.anyio
async def test_advanced_conditions_validated(tmp_path):
    service = make_service(tmp_path)
    await seed(service)
    with pytest.raises(SearchQueryError):
        await service.search(query="rust", limit=10, intitle="a b c")
    with pytest.raises(SearchQueryError):
        await service.search(query="rust", limit=10, exclude="a b c")
    with pytest.raises(SearchQueryError):
        await service.search(query="rust", limit=10, phrase="x" * 121)


@pytest.mark.anyio
async def test_route_accepts_advanced_params(tmp_path):
    """路由层参数透传（query param → service.search）。"""
    from starlette.testclient import TestClient

    from lumirss.main import app

    service = make_service(tmp_path)
    await seed(service)

    with TestClient(app) as client:
        app.state.search_service = service
        response = client.get(
            "/api/v1/search",
            params={"q": "rust", "intitle": "rust", "exclude": "访谈"},
        )
        assert response.status_code == 200
        body = response.json()
        assert [row["title"] for row in body["items"]] == ["Rust 发布新版本"]

        rejected = client.get(
            "/api/v1/search", params={"q": "rust", "intitle": "a b c"}
        )
        assert rejected.status_code == 400
