"""0022: search projection unit + route tests.

Covers: term splitting, LIKE escaping (injection-neutral queries),
rebuild → search roundtrip, incremental sync stop condition, keyset
pagination, filters (feed/category/state/starred/date), the q1 cursor,
matched-field reporting, plain-text snippets, and the stable error
envelope for invalid queries.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from lumirss.adapters.freshrss import Feed
from lumirss.main import app
from lumirss.models import EntryDocument, EntryDocumentPage
from lumirss.search_index import (
    SearchIndexService,
    SearchQueryError,
    decode_search_cursor,
    encode_search_cursor,
    split_terms,
)
from lumirss.search_store import like_pattern


def run(coroutine):
    return asyncio.run(coroutine)


def doc(
    item_id: str,
    title: str,
    *,
    content: str = "body text",
    feed_url: str = "https://example.com/feed.xml",
    feed_title: str = "Example",
    author: str | None = "Ada",
    published_at: str = "2026-09-01T00:00:00Z",
    read: bool = False,
    starred: bool = False,
) -> EntryDocument:
    return EntryDocument(
        item_id=item_id,
        entryRef=f"e1.{item_id}",
        feedUrl=feed_url,
        feedTitle=feed_title,
        title=title,
        author=author,
        url="https://example.com/a",
        publishedAt=published_at,
        read=read,
        starred=starred,
        contentText=content,
    )


class FakeAdapter:
    """Minimal FreshRSSAdapter double for projection tests."""

    def __init__(self, documents, feeds=None):
        self._documents = documents
        self._feeds = feeds or []

    async def list_entry_documents(self, *, continuation=None, limit=50):
        docs = self._documents
        start = int(continuation) if continuation else 0
        page = docs[start : start + limit]
        next_cont = str(start + limit) if start + limit < len(docs) else None
        return EntryDocumentPage(documents=page, upstreamContinuation=next_cont)

    async def list_feeds(self):
        return self._feeds


def make_service(tmp_path, documents, feeds=None) -> SearchIndexService:
    from lumirss.storage import Database

    db = Database(tmp_path / "search-test.sqlite")
    return SearchIndexService(db, FakeAdapter(documents, feeds))


# ---------------------------------------------------------------------------
# unit: terms + patterns
# ---------------------------------------------------------------------------


def test_split_terms_whitespace_and_empty():
    assert split_terms("  machine   learning ") == ["machine", "learning"]
    assert split_terms("   ") == []


def test_like_pattern_escapes_wildcards():
    assert like_pattern("100%") == "%100\\%%"
    assert like_pattern("a_b") == "%a\\_b%"
    assert like_pattern("back\\slash") == "%back\\\\slash%"
    assert like_pattern("plain") == "%plain%"


# ---------------------------------------------------------------------------
# service: rebuild → search roundtrip
# ---------------------------------------------------------------------------


def test_rebuild_then_search_roundtrip(tmp_path):
    documents = [
        doc("i1", "Machine learning weekly", content="transformers everywhere"),
        doc("i2", "Cooking pasta", content="boil water, add salt"),
        doc(
            "i3",
            "科技爱好者周刊",
            content="程序员的职业未来与 AI 工具",
            published_at="2026-09-03T00:00:00Z",
        ),
    ]
    service = make_service(tmp_path, documents)
    report = run(service.rebuild())
    assert report["entryCount"] == 3
    assert report["partial"] is False

    hits = run(service.search(query="machine learning", limit=10))
    assert hits["hasMore"] is False
    assert [row["title"] for row in hits["rows"]] == [
        "Machine learning weekly"
    ]


def test_search_cjk_substring(tmp_path):
    documents = [
        doc("i1", "科技爱好者周刊：程序员的职业未来", content="AI 缓存知识"),
        doc("i2", "Cooking pasta", content="boil water"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    hits = run(service.search(query="周刊", limit=10))
    assert len(hits["rows"]) == 1
    assert hits["rows"][0]["title"].startswith("科技爱好者周刊")


def test_search_case_insensitive_and_content_match(tmp_path):
    documents = [
        doc("i1", "Weekly notes", content="LLM Agents everywhere"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    hits = run(service.search(query="llm agents", limit=10))
    assert len(hits["rows"]) == 1
    assert hits["rows"][0]["matchedFields"] == ["content"]


def test_search_special_characters_stay_literal(tmp_path):
    documents = [
        doc("i1", "Progress at 100%", content="under_score and back\\slash"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    for query in ("100%", "under_score", "back\\slash"):
        hits = run(service.search(query=query, limit=10))
        assert len(hits["rows"]) == 1, query


def test_search_fts_operators_inert(tmp_path):
    documents = [
        doc("i1", 'Title with "quotes"', content="NEAR body OR content"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    for query in ('"quotes"', "NEAR OR body", "a) (", "intitle:"):
        hits = run(service.search(query=query, limit=10))
        assert isinstance(hits["rows"], list)


def test_search_filters(tmp_path):
    documents = [
        doc(
            "i1",
            "read pasta",
            content="x",
            feed_url="https://a.com/feed",
            read=True,
            published_at="2026-08-01T00:00:00Z",
        ),
        doc(
            "i2",
            "starred pasta",
            content="y",
            feed_url="https://b.com/feed",
            starred=True,
        ),
        doc(
            "i3",
            "plain pasta",
            content="z",
            feed_url="https://b.com/feed",
        ),
    ]
    feeds = [
        Feed("A", "https://a.com/feed", "user/-/label/News", "News"),
        Feed("B", "https://b.com/feed", "user/-/label/News", "News"),
    ]
    service = make_service(tmp_path, documents, feeds)
    run(service.rebuild())

    all_hits = run(service.search(query="pasta", limit=10))
    assert len(all_hits["rows"]) == 3

    unread = run(service.search(query="pasta", limit=10, unread_only=True))
    assert {row["title"] for row in unread["rows"]} == {
        "starred pasta",
        "plain pasta",
    }

    starred = run(service.search(query="pasta", limit=10, starred_only=True))
    assert [row["title"] for row in starred["rows"]] == ["starred pasta"]

    in_feed = run(
        service.search(query="pasta", limit=10, feed_url="https://b.com/feed")
    )
    assert len(in_feed["rows"]) == 2

    in_category = run(
        service.search(query="pasta", limit=10, category_id="user/-/label/News")
    )
    assert len(in_category["rows"]) == 3

    unknown_category = run(
        service.search(
            query="pasta", limit=10, category_id="user/-/label/Nope"
        )
    )
    assert unknown_category["rows"] == []

    august = run(
        service.search(
            query="pasta",
            limit=10,
            published_from="2026-08-01",
            published_to="2026-09-01",
        )
    )
    assert [row["title"] for row in august["rows"]] == ["read pasta"]


def test_search_pagination_keyset(tmp_path):
    documents = [
        doc(f"i{n}", f"pasta {n}", published_at=f"2026-09-{n + 1:02d}T00:00:00Z")
        for n in range(6)
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    page1 = run(service.search(query="pasta", limit=4))
    assert page1["hasMore"] is True and len(page1["rows"]) == 4
    cursor = encode_search_cursor(*page1["nextKeyset"])
    page2 = run(
        service.search(
            query="pasta", limit=4, keyset=decode_search_cursor(cursor)
        )
    )
    assert page2["hasMore"] is False and len(page2["rows"]) == 2
    seen = {row["title"] for row in page1["rows"] + page2["rows"]}
    assert len(seen) == 6


def test_incremental_sync_updates_and_stops(tmp_path):
    documents = [
        doc("i1", "fresh one", content="a"),
        doc("i2", "fresh two", content="b"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())

    # mark one entry read upstream and add a new one at the top
    documents[1] = doc("i2", "fresh two", content="b", read=True)
    documents.insert(0, doc("i0", "newest", content="c"))
    report = run(service.sync_incremental())
    assert report["updated"] == 2

    newest = run(service.search(query="newest", limit=10))
    assert {row["title"] for row in newest["rows"]} == {"newest"}
    unread = run(service.search(query="fresh", limit=10, unread_only=True))
    assert {row["title"] for row in unread["rows"]} == {"fresh one"}


def test_state_mirror_and_index_info(tmp_path):
    service = make_service(tmp_path, [doc("i1", "hello", content="world")])
    run(service.rebuild())
    info = run(service.index_info())
    assert info["entryCount"] == 1
    assert info["lastSyncedAt"] is not None
    hits = run(service.search(query="hello", limit=5))
    ref = hits["rows"][0]["entryRef"]
    run(service.set_entry_read(ref, True))
    run(service.set_entry_starred(ref, True))
    unread = run(service.search(query="hello", limit=5, unread_only=True))
    assert unread["rows"] == []
    starred = run(service.search(query="hello", limit=5, starred_only=True))
    assert len(starred["rows"]) == 1


def test_query_validation(tmp_path):
    service = make_service(tmp_path, [])
    with pytest.raises(SearchQueryError):
        run(service.search(query="   ", limit=5))
    with pytest.raises(SearchQueryError):
        run(service.search(query="a b c d e", limit=5))


# ---------------------------------------------------------------------------
# route contract
# ---------------------------------------------------------------------------


def test_search_route_rejects_missing_and_empty_query(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        missing = client.get("/api/v1/search")
        assert missing.status_code == 422
        assert missing.json()["error"]["type"] == "invalid_request"

        empty = client.get("/api/v1/search", params={"q": "   "})
        assert empty.status_code == 400
        assert empty.json()["error"]["type"] == "invalid_search_query"


def test_search_route_reports_empty_index_honestly(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "data" / "lumi.sqlite"))
    with TestClient(app) as client:
        response = client.get("/api/v1/search", params={"q": "anything"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["index"]["entryCount"] == 0
    assert payload["hasMore"] is False
