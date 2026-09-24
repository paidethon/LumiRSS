"""N142 自然语言转过滤条件 — 纯规则预处理器回归。

固定 today 注入保证可测：日期短语（今天/昨天/本周/本月/去年/近 N 天/
last N days/YYYY-MM-DD）、来源前缀（解析成功/失败）、否定词、引号
短语的转换；未识别部分逐词诚实列出；路由层契约 + 「应用解析结果 =
手工设置同参过滤」的等价性。
"""

import secrets as _secrets
from datetime import date, timedelta

import pytest

from lumirss.adapters.freshrss import Feed, FreshRSSAdapter
from lumirss.entryref import encode_entry_ref
from lumirss.models import EntryDocument, EntryDocumentPage
from lumirss.search_index import SearchIndexService
from lumirss.search_parse import parse_query

TODAY = date(2026, 9, 23)
FAKE = "fake-" + _secrets.token_urlsafe(6)


def _parse(query, resolve_source=None):
    import asyncio

    return asyncio.run(
        parse_query(query, today=TODAY, resolve_source=resolve_source)
    )


# ---- 日期短语 ---------------------------------------------------------------


def test_today_maps_to_today_window():
    parsed = _parse(" rust 今天 ")
    assert parsed.filters["from"] == "2026-09-23"
    assert parsed.filters["to"] == "2026-09-24"  # to 为排他上界
    assert parsed.remaining_text == "rust"
    assert {"kind": "date", "text": "今天"} in [
        dict(r) for r in parsed.recognized
    ]


def test_yesterday_window():
    parsed = _parse("发布说明 昨天")
    assert parsed.filters["from"] == "2026-09-22"
    assert parsed.filters["to"] == "2026-09-23"
    assert parsed.remaining_text == "发布说明"


def test_this_week_and_this_month_and_last_year():
    assert _parse("周报 本周").filters["from"] == "2026-09-21"  # 周一
    assert _parse("周报 本周").filters["to"] == "2026-09-28"
    assert _parse("账单 本月").filters["from"] == "2026-09-01"
    assert _parse("账单 本月").filters["to"] == "2026-10-01"
    assert _parse("回顾 去年").filters["from"] == "2025-01-01"
    assert _parse("回顾 去年").filters["to"] == "2026-01-01"


def test_last_n_days_chinese_and_english():
    parsed = _parse("故障 近 7 天")
    assert parsed.filters["from"] == str(TODAY - timedelta(days=6))
    assert parsed.filters["to"] == "2026-09-24"
    assert parsed.remaining_text == "故障"
    parsed = _parse("incident in last 3 days")
    assert parsed.filters["from"] == str(TODAY - timedelta(days=2))
    assert parsed.remaining_text == "incident in"


def test_iso_date_specific_day():
    parsed = _parse("公告 2026-09-01 上线")
    assert parsed.filters["from"] == "2026-09-01"
    assert parsed.filters["to"] == "2026-09-02"
    assert parsed.remaining_text == "公告 上线"


def test_first_date_phrase_wins_later_stays_free():
    parsed = _parse("今天 还是 去年")
    assert parsed.filters["from"] == "2026-09-23"
    # 后一个日期短语不消费：留在自由词并列 unrecognized（诚实）。
    assert "去年" in parsed.remaining_text
    assert "去年" in parsed.unrecognized


def test_invalid_iso_date_not_recognized():
    parsed = _parse("版本 2026-13-99 发布")
    assert "from" not in parsed.filters
    assert "2026-13-99" in parsed.remaining_text


# ---- 来源前缀 ---------------------------------------------------------------


def test_source_prefix_resolved_via_callback():
    parsed = _parse(
        "泄露 通报 来源:ExampleBlog",
        resolve_source=lambda token: (
            "https://example.blog/rss" if token == "ExampleBlog" else None
        ),
    )
    assert parsed.filters["feedRef"] == "https://example.blog/rss"
    assert parsed.remaining_text == "泄露 通报"


def test_site_prefix_unresolved_stays_free_and_listed():
    parsed = _parse("漏洞 site:unknown.example")
    assert "feedRef" not in parsed.filters
    assert "site:unknown.example" in parsed.remaining_text
    assert "site:unknown.example" in parsed.unrecognized


# ---- 否定词与短语 -----------------------------------------------------------


def test_negation_maps_to_exclude():
    parsed = _parse("模型发布 -广告 -招聘 补充说明")
    assert parsed.filters["exclude"] == "广告 招聘"
    assert parsed.remaining_text == "模型发布 补充说明"


def test_negation_overflow_stays_free():
    parsed = _parse("发布会 -广告 -招聘 -税收")
    assert parsed.filters["exclude"] == "广告 招聘"  # 服务端上限 2 词
    assert "-税收" in parsed.remaining_text
    assert "-税收" in parsed.unrecognized


def test_quoted_phrase_maps_to_phrase():
    parsed = _parse("报告 \"量子计算 投资\" 摘要")
    assert parsed.filters["phrase"] == "量子计算 投资"
    assert parsed.remaining_text == "报告 摘要"


def test_curly_quotes_phrase():
    parsed = _parse("“开源 治理” 讨论")
    assert parsed.filters["phrase"] == "开源 治理"
    assert parsed.remaining_text == "讨论"


def test_phrase_overflow_stays_free():
    parsed = _parse('" alpha " 和 "beta"')
    assert parsed.filters["phrase"] == "alpha"
    assert "beta" in parsed.remaining_text


def test_nothing_recognized_all_words_listed():
    parsed = _parse("普通 关键词")
    assert parsed.filters == {}
    assert parsed.remaining_text == "普通 关键词"
    assert parsed.unrecognized == ["普通", "关键词"]


def test_combined_constructs():
    parsed = _parse(
        '数据合规 "fine structure" 来源:News -访谈 近 30 天',
        resolve_source=lambda token: {"News": "https://news.example/rss"}.get(token),
    )
    assert parsed.filters == {
        "feedRef": "https://news.example/rss",
        "from": str(TODAY - timedelta(days=29)),
        "to": "2026-09-24",
        "phrase": "fine structure",
        "exclude": "访谈",
    }
    assert parsed.remaining_text == "数据合规"


# ---- 路由层：契约 + 与手工设置过滤的等价性 -----------------------------------


def doc(item_id, title, content, published_at, feed_url, feed_title):
    return EntryDocument(
        item_id=item_id,
        entryRef=encode_entry_ref(item_id),
        feedUrl=feed_url,
        feedTitle=feed_title,
        title=title,
        author="作者甲",
        url="https://example.com/x",
        publishedAt=published_at,
        read=False,
        starred=False,
        contentText=content,
    )


FEED_A = "https://a.example/rss"
FEED_B = "https://b.example/rss"
DOCUMENTS = [
    doc("1", "Rust 1.80 发布", "Rust 性能提升明显。", "2026-09-23T08:00:00Z", FEED_A, "源A"),
    doc("2", "Rust 旧闻", "去年的 Rust 内容。", "2025-03-01T08:00:00Z", FEED_B, "源B"),
    doc("3", "Rust 广告合集", "推广内容。", "2026-09-22T08:00:00Z", FEED_A, "源A"),
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


def _feed_title_feeder(tmp_path):
    """带同源投影的 service（解析器来源解析走 search_feeds 投影）。"""
    from lumirss.storage import Database

    db = Database(tmp_path / "n142.sqlite")
    return SearchIndexService(db, FakeAdapter(DOCUMENTS, FEEDS))


@pytest.mark.anyio
async def test_parse_endpoint_and_equivalence_with_manual_filters(tmp_path):
    """应用解析结果执行的搜索 = 手工设置同参过滤的搜索（同一 SQL）。"""
    from starlette.testclient import TestClient

    from lumirss.main import app

    service = _feed_title_feeder(tmp_path)
    report = await service.rebuild()
    assert report["entryCount"] == 3

    with TestClient(app) as client:
        app.state.search_service = service
        # 来源解析经 search_feeds 投影（rebuild 已同步订阅清单）。
        parsed = client.post(
            "/api/v1/search/parse-query",
            json={"query": "rust 今天 -广告 来源:源A"},
        )
        assert parsed.status_code == 200
        body = parsed.json()
        # 端点使用服务端当日（纯函数层已用固定 TODAY 覆盖日期规则）。
        server_today = date.today()
        assert body["filters"]["from"] == server_today.isoformat()
        assert body["filters"]["to"] == (server_today + timedelta(days=1)).isoformat()
        assert body["filters"]["exclude"] == "广告"
        assert body["filters"]["feedRef"] == FEED_A
        assert body["remainingText"] == "rust"
        # 剩余自由词即未转换部分，逐词诚实列出（与 remainingText 一致）。
        assert body["unrecognized"] == ["rust"]
        kinds = {r["kind"] for r in body["recognized"]}
        assert kinds == {"date", "exclude", "source"}

        # 解析结果执行搜索（remainingText + filters → 手工同参请求）。
        f = body["filters"]
        via_parse = client.get(
            "/api/v1/search",
            params={
                "q": body["remainingText"],
                "from": f["from"],
                "to": f["to"],
                "exclude": f["exclude"],
                "feedUrl": f["feedRef"],
            },
        )
        manual = client.get(
            "/api/v1/search",
            params={
                "q": "rust",
                "from": server_today.isoformat(),
                "to": (server_today + timedelta(days=1)).isoformat(),
                "exclude": "广告",
                "feedUrl": FEED_A,
            },
        )
        assert via_parse.status_code == manual.status_code == 200
        assert via_parse.json()["items"] == manual.json()["items"]
        assert [row["title"] for row in via_parse.json()["items"]] == [
            "Rust 1.80 发布"
        ]


@pytest.mark.anyio
async def test_parse_endpoint_lists_unrecognized_honestly(tmp_path):
    from starlette.testclient import TestClient

    from lumirss.main import app

    service = _feed_title_feeder(tmp_path)
    await service.rebuild()
    with TestClient(app) as client:
        app.state.search_service = service
        body = client.post(
            "/api/v1/search/parse-query",
            json={"query": "量子 计算机架构 site:nosuch.example"},
        ).json()
        assert body["filters"] == {}
        assert body["remainingText"] == "量子 计算机架构 site:nosuch.example"
        assert "量子" in body["unrecognized"]
        assert "site:nosuch.example" in body["unrecognized"]


@pytest.mark.anyio
async def test_parse_endpoint_validates_query(tmp_path):
    from starlette.testclient import TestClient

    from lumirss.main import app

    service = _feed_title_feeder(tmp_path)
    await service.rebuild()
    with TestClient(app) as client:
        app.state.search_service = service
        empty = client.post("/api/v1/search/parse-query", json={"query": ""})
        assert empty.status_code == 422
        long = client.post(
            "/api/v1/search/parse-query", json={"query": "x" * 201}
        )
        assert long.status_code == 422
