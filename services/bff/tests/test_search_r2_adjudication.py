"""R2 search adjudication batch — FIX-311 / FIX-313 / FIX-314 / FIX-320.

Each FIX id gets an honest verdict against the actual engine:

- FIX-311：检索引擎是 LIKE + ESCAPE（绑定参数，like_pattern 转义
  %/_/\\），全仓不存在 FTS5 MATCH——FTS 语法字符对引擎是普通文本，
  不可能抛 sqlite3.OperationalError → 500。测试用 hostile 样本全集
  钉死「不 500 + 普通查询仍命中 + 结构非法走稳定 400 错误契约」。
- FIX-313：BFF 从不构造 HTML 高亮——snippet 是纯文本摘录
  （search_index.build_snippet），命中标注是结构化字段
  （matchedFields/matchPositions 偏移量）；Atom 视图腿
  （atom_render.render_feed）对全部内容做 stdlib XML 转义。测试用
  `<img src=x onerror=alert(1)>` 样本钉死「原文以惰性文本原样返回，
  任何输出字符串中不出现 <mark> 或被构造的标记」。
- FIX-314：日期筛选单一口径——投影 published_at 在适配器入口统一为
  UTC ISO 文本（epoch 秒/毫秒都在 FreshRSSAdapter._common_fields 归一），
  过滤链只做 ISO 文本比较（from 含端点、to 排他），N143 解释路径
  （search_debug.diagnose_row）复刻同一比较。测试钉住边界恰含一次 +
  秒/毫秒/ISO 三种输入归一到同一文本。
- FIX-320：搜索不存在结果缓存——每请求直读投影（无 memo/无 LRU），
  HTTP 层 NoStoreCacheMiddleware 对全部 /api/* 盖 Cache-Control:
  no-store（FIX-368），重建（swap_staged）与删除（delete_entry）原子
  生效。测试钉住「热查询后删除/重建 → 下一次查询立即反映，无任何
  失效步骤」+ no-store 响应头契约。

Conventions: isolated temp DB per test (make_service), no network
(FakeAdapter), SQL exercised through the production service paths.
"""

import asyncio
import json

from fastapi.testclient import TestClient

from lumirss.adapters.freshrss import FreshRSSAdapter
from lumirss.main import app
from lumirss.models import EntryDocument, EntryDocumentPage
from lumirss.search_index import SearchIndexService, SearchQueryError
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

    db = Database(tmp_path / "search-adjudication.sqlite")
    return SearchIndexService(db, FakeAdapter(documents, feeds))


# ---------------------------------------------------------------------------
# FIX-311：FTS 语法字符样本不得 500；普通搜索与结构非法错误有稳定契约
# ---------------------------------------------------------------------------


def test_fix311_fts_metacharacter_samples_never_error(tmp_path):
    documents = [
        doc(
            "i1",
            'Progress report with "quotes" and (parens)',
            content="body with asterisk * colon : dash - plus OR AND NOT operators",
        ),
        doc("i2", "plain article", content="ordinary words only"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    # FTS5/MATCH 语法字符全集样本（含组合）；任何一项抛异常都会让
    # 路由层变 500 —— 全部必须安静返回普通结果集。
    hostile_queries = [
        '"',
        "(",
        ")",
        "*",
        ":",
        "-",
        "OR",
        "AND",
        "NOT",
        '"quoted phrase"',
        "(a OR b) AND NOT c*",
        "a:b",
        "x-y",
        'title:"quotes"',
        "NEAR(a b) AND (c OR d)",
        "**bold** :starts -minus",
    ]
    for query in hostile_queries:
        try:
            result = run(service.search(query=query, limit=10))
        except SearchQueryError:
            # 仓库既有错误契约：结构非法（如 >4 词条）→ 稳定类型化 400，
            # 而不是 sqlite3.OperationalError → 500。
            continue
        assert isinstance(result["rows"], list), query


def test_fix311_plain_query_still_matches_and_syntax_is_literal(tmp_path):
    """普通词命中 + 语法字符按字面子串解释（可解释结果）。"""
    documents = [
        doc(
            "i1",
            'Title with "quotes"',
            content="NEAR body OR content",
        ),
        doc("i2", "cooking pasta", content="boil water"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    # 普通搜索照常命中。
    plain = run(service.search(query="pasta", limit=10))
    assert [row["title"] for row in plain["rows"]] == ["cooking pasta"]
    # 引号字符是普通文本：字面出现在标题里 → 字面查询命中该条且仅该条。
    quoted = run(service.search(query='"quotes"', limit=10))
    assert [row["title"] for row in quoted["rows"]] == ['Title with "quotes"']
    # 布尔运算符不是语法：作为字面子串命中正文里的 "NEAR body OR content"。
    operators = run(service.search(query="NEAR", limit=10))
    assert [row["title"] for row in operators["rows"]] == ['Title with "quotes"']


def test_fix311_structurally_invalid_query_is_typed_400_not_500(tmp_path, monkeypatch):
    """结构非法（空/超长/超词）走 SearchQueryError → 稳定 400 错误契约；
    语法字符样本经真实 HTTP 栈返回 200 而非 500。"""
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "data" / "lumi.sqlite"))
    with TestClient(app) as client:
        empty = client.get("/api/v1/search", params={"q": "   "})
        assert empty.status_code == 400
        assert empty.json()["error"]["type"] == "invalid_search_query"

        too_long = client.get("/api/v1/search", params={"q": "x" * 201})
        assert too_long.status_code == 400
        assert too_long.json()["error"]["type"] == "invalid_search_query"

        too_many_terms = client.get("/api/v1/search", params={"q": "a b c d e"})
        assert too_many_terms.status_code == 400
        assert too_many_terms.json()["error"]["type"] == "invalid_search_query"

        # 语法字符样本经真实 HTTP 栈：≤4 词条 → 200（不 500）；
        # >4 词条的组合样本 → 同一稳定 400 契约（绝不 500）。
        for hostile in ('"', "a:b", "x-y", "c*", "(a b)"):
            response = client.get("/api/v1/search", params={"q": hostile})
            assert response.status_code == 200, (hostile, response.text)
        combo = client.get("/api/v1/search", params={"q": "(a OR b) AND NOT c*"})
        assert combo.status_code == 400
        assert combo.json()["error"]["type"] == "invalid_search_query"

# ---------------------------------------------------------------------------
# FIX-313：高亮/摘录绝不把未清洗内容当 HTML 插入——惰性文本原样返回
# ---------------------------------------------------------------------------


def test_fix313_hostile_title_and_content_stay_inert_text(tmp_path):
    xss_img = "<img src=x onerror=alert(1)>"
    script = "<script>alert(2)</script>"
    documents = [
        doc(
            "i1",
            f"Breached {xss_img} today",
            content=f"body {script} continues here with probe term",
        ),
        doc("i2", "second article", content="filler body"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    result = run(service.search(query="breached", limit=10))
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    # 标题原样（惰性文本），无任何截断改写或标记包裹。
    assert row["title"] == f"Breached {xss_img} today"
    # 摘录中脚本标签保持字面文本。
    assert script in row["snippet"]
    # BFF 输出全量字符串中绝不出现高亮标记或新构造的标签。
    dumped = json.dumps(result, ensure_ascii=False)
    assert "<mark" not in dumped
    assert "<strong" not in dumped
    assert "<em>" not in dumped
    # 命中标注是结构化偏移，不是 HTML 片段。
    assert all(
        isinstance(position["offset"], int) and isinstance(position["term"], str)
        for position in row["matchPositions"]
    )
    assert all(field in {"title", "feed", "author", "content"} for field in row["matchedFields"])


def test_fix313_search_route_serializes_hostile_markup_as_json_text(client):
    """HTTP 层：恶意标记以 JSON 字符串出站（FastAPI JSON 序列化），
    响应体不携带可执行的 HTML 结构。"""
    from lumirss.main import app

    xss_img = "<img src=x onerror=alert(1)>"

    def _seed(db):
        async def _seed_inner():
            await db.migrate()
            await db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, 'https://f.example/rss', '源', ?, '作者', 'u', 'probe body', '2026-09-01T00:00:00Z', 0, 0, 0)",
                ("x1", "ref.x1", f"probe {xss_img} end"),
            )

        return _seed_inner

    run(_seed(app.state.db)())
    response = client.get("/api/v1/search", params={"q": "probe"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    titles = [item["title"] for item in payload["items"]]
    assert any(xss_img in title for title in titles)
    # JSON 文本层面不存在未转义的标签开闭对（序列化后为文本）。
    raw_body = response.text
    assert "<mark" not in raw_body


# ---------------------------------------------------------------------------
# FIX-314：日期筛选单一 ISO-UTC 口径——边界恰含一次，秒/毫秒/ISO 归一
# ---------------------------------------------------------------------------


def test_fix314_date_boundaries_inclusive_from_exclusive_to(tmp_path):
    documents = [
        doc("before", "before window", published_at="2026-08-31T23:59:59Z"),
        doc("at-from", "at from boundary", published_at="2026-09-01T00:00:00Z"),
        doc("inside", "inside window", published_at="2026-09-03T12:00:00Z"),
        doc("at-to", "at to boundary", published_at="2026-09-05T00:00:00Z"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    result = run(
        service.search(
            query="body",  # doc() 默认正文 "body text"，四条全命中词条
            limit=10,
            published_from="2026-09-01",
            published_to="2026-09-05",
        )
    )
    titles = [row["title"] for row in result["rows"]]
    # from 含端点、to 排他：from 边界行恰含一次，to 边界行被排除。
    assert titles == ["inside window", "at from boundary"]
    assert titles.count("at from boundary") == 1


def test_fix314_full_timestamp_bounds_match_sql_and_diagnose(tmp_path):
    """完整 ISO 时间戳边界与 SQL 一致，且 N143 解释路径同口径判定。"""
    from lumirss.search_debug import diagnose_row

    documents = [
        doc("at-from", "at from boundary", published_at="2026-09-01T00:00:00Z"),
        doc("at-to", "at to boundary", published_at="2026-09-05T00:00:00Z"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    result = run(
        service.search(
            query="body",
            limit=10,
            published_from="2026-09-01T00:00:00Z",
            published_to="2026-09-05T00:00:00Z",
        )
    )
    titles = {row["title"] for row in result["rows"]}
    assert titles == {"at from boundary"}
    # 解释路径对同两行给出与 SQL 相同的日期判定（同单位、同端点语义）。
    rows = {
        "at-from": {
            "title": "at from boundary",
            "author": "Ada",
            "feed_url": "https://example.com/feed.xml",
            "feed_title": "Example",
            "content_text": "body text",
            "published_at": "2026-09-01T00:00:00Z",
            "read": 0,
            "starred": 0,
        },
        "at-to": {
            "title": "at to boundary",
            "author": "Ada",
            "feed_url": "https://example.com/feed.xml",
            "feed_title": "Example",
            "content_text": "body text",
            "published_at": "2026-09-05T00:00:00Z",
            "read": 0,
            "starred": 0,
        },
    }
    for key, row in rows.items():
        reasons = diagnose_row(
            row,
            terms=["body"],
            intitle_terms=[],
            phrase=None,
            exclude_terms=[],
            feed_url=None,
            in_category=True,
            unread_only=False,
            starred_only=False,
            published_from="2026-09-01T00:00:00Z",
            published_to="2026-09-05T00:00:00Z",
            has_summary=None,
        )
        date_reasons = [r for r in reasons if r["kind"] == "date"]
        if key == "at-from":
            assert date_reasons == []
        else:
            assert any("不早于截止日期" in r["detail"] for r in date_reasons)


def test_fix314_epoch_seconds_and_millis_unify_to_same_iso_text():
    """入口归一：上游 epoch 秒（published）与 epoch 毫秒
    （crawlTimestampMsec）都归一为同一 UTC ISO 文本——过滤链只见过
    一种单位，不存在秒/毫秒混比。"""
    from datetime import UTC, datetime

    epoch = 1788220800  # 2026-09-01T00:00:00Z，int 秒
    expected = datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert expected == "2026-09-01T00:00:00Z"
    seconds_item = {"id": "s1", "published": epoch}
    millis_item = {"id": "m1", "published": epoch, "crawlTimestampMsec": str(epoch * 1000)}
    parsed_seconds = FreshRSSAdapter._common_fields(seconds_item)
    parsed_millis = FreshRSSAdapter._common_fields(millis_item)
    assert parsed_seconds is not None and parsed_millis is not None
    assert parsed_seconds["published_at"] == expected
    assert parsed_millis["crawled_at"] == expected


# ---------------------------------------------------------------------------
# FIX-320：无结果缓存——热查询后删除/重建，下一次查询立即如实反映
# ---------------------------------------------------------------------------


def test_fix320_delete_reflects_on_next_search_without_invalidation(tmp_path):
    from lumirss.search_writer import SearchEntryWriter

    documents = [
        doc("k1", "cache probe alpha"),
        doc("k2", "cache probe beta"),
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    # 预热：同一查询先跑一遍（若存在按代次失效的结果缓存，这里是热态）。
    warm = run(service.search(query="probe", limit=10))
    assert len(warm["rows"]) == 2
    # 删除一条（投影删除原语），无任何缓存失效步骤。
    run(SearchEntryWriter(service._db).delete_entry("k1"))
    again = run(service.search(query="probe", limit=10))
    titles = {row["title"] for row in again["rows"]}
    assert titles == {"cache probe beta"}


def test_fix320_rebuild_reflects_on_next_search(tmp_path):
    documents = [doc("k1", "cache probe alpha")]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    warm = run(service.search(query="probe", limit=10))
    assert len(warm["rows"]) == 1
    # 换一批文档重建（swap_staged 原子换入）→ 下一次查询立即反映。
    service._adapter._documents = [doc("k2", "cache probe gamma")]
    run(service.rebuild())
    after = run(service.search(query="probe", limit=10))
    assert {row["title"] for row in after["rows"]} == {"cache probe gamma"}


def test_fix320_search_route_stamps_no_store(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "data" / "lumi.sqlite"))
    with TestClient(app) as client:
        response = client.get("/api/v1/search", params={"q": "anything"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# FIX-315：分页排序的稳定次级键 + 跨页不重复不丢失
# ---------------------------------------------------------------------------


def test_fix315_same_published_at_rows_page_without_dup_or_drop(tmp_path):
    """同分（published_at 全相同）行必须被 (published_at, item_id)
    次级键完全定序；按应用页大小翻页 → 每条恰出现一次。"""
    documents = [
        doc(f"t{n}", f"tie row {n}", published_at="2026-09-01T00:00:00Z")
        for n in range(9)
    ]
    service = make_service(tmp_path, documents)
    run(service.rebuild())
    seen: list[str] = []
    keyset = None
    pages = 0
    while True:
        page = run(service.search(query="tie", limit=4, keyset=keyset))
        seen.extend(row["title"] for row in page["rows"])
        pages += 1
        if not page["hasMore"] or page["nextKeyset"] is None:
            break
        keyset = page["nextKeyset"]
    assert pages == 3
    assert sorted(seen) == sorted(f"tie row {n}" for n in range(9))
    assert len(seen) == len(set(seen)) == 9
