"""N034 发布时间可信度提示 — 异常分类 / timeCredibility 附加 / sort=received。

- 分类器：missing / no_timezone / future / too_old 逐类命中；
- 摄取时分类写入投影 time_flags，时间线条目附带 timeCredibility；
- sort=received 由服务端执行（query param 真实生效，按投影接收时间
  降序），未知条目保持原序不冒充。
"""

import asyncio

from lumirss.entry_intake import (
    TIME_FLAG_FUTURE,
    TIME_FLAG_MISSING,
    TIME_FLAG_NO_TIMEZONE,
    TIME_FLAG_TOO_OLD,
    classify_published_at,
    time_flag_codes,
)
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import (
    EntryDocumentPage,
    EntryListItem,
    EntryPage,
)
from lumirss.search_index import SearchIndexService

NOW = 1_789_700_000.0  # 固定「摄取时刻」，测试与墙钟解耦


def test_classifier_each_anomaly():
    assert classify_published_at(None, now_epoch=NOW) == TIME_FLAG_MISSING
    assert classify_published_at("", now_epoch=NOW) == TIME_FLAG_MISSING
    # naive（无时区）— FreshRSS epoch 归一化不会产生，保留类别诚实性
    assert classify_published_at("2026-09-01T00:00:00", now_epoch=NOW) == TIME_FLAG_NO_TIMEZONE
    # 未来 > now + 1d
    assert classify_published_at("2040-01-01T00:00:00Z", now_epoch=NOW) == TIME_FLAG_FUTURE
    # now + 1h：容差内不算未来
    import datetime

    tolerated = datetime.datetime.fromtimestamp(NOW + 3600, tz=datetime.UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert classify_published_at(tolerated, now_epoch=NOW) == 0
    # 过旧（< 2000-01-01）
    assert classify_published_at("1999-12-31T23:59:59Z", now_epoch=NOW) == TIME_FLAG_TOO_OLD
    # 正常
    assert classify_published_at("2026-09-01T00:00:00Z", now_epoch=NOW) == 0
    # 组合：未来且无时区
    assert (
        classify_published_at("2040-01-01T00:00:00", now_epoch=NOW)
        == TIME_FLAG_FUTURE | TIME_FLAG_NO_TIMEZONE
    )


def test_time_flag_codes_order():
    assert time_flag_codes(TIME_FLAG_MISSING | TIME_FLAG_TOO_OLD) == [
        "missing",
        "too_old",
    ]
    assert time_flag_codes(0) == []


# -- 摄取分类写入投影 ----------------------------------------------------------


def doc(item_id, published_at):
    from lumirss.models import EntryDocument

    return EntryDocument(
        item_id=item_id,
        entryRef=encode_entry_ref(item_id),
        feedUrl="https://example.com/feed.xml",
        feedTitle="Example",
        title=f"T-{item_id}",
        author=None,
        url=None,
        publishedAt=published_at,
        read=False,
        starred=False,
        contentText="body",
        contentHtml="<p>body</p>",
    )


class FakeAdapter:
    def __init__(self, documents):
        self.documents = documents

    async def list_entry_documents(self, *, continuation=None, limit=50):
        return EntryDocumentPage(documents=list(self.documents), upstreamContinuation=None)

    async def list_feeds(self):
        return []


def test_ingest_classifies_into_projection(tmp_path):
    from lumirss.storage import Database

    db = Database(tmp_path / "nd034.sqlite")
    service = SearchIndexService(
        db,
        FakeAdapter(
            [
                doc("ok", "2026-09-01T00:00:00Z"),
                doc("missing", ""),
                doc("future", "2040-01-01T00:00:00Z"),
                doc("old", "1999-06-01T00:00:00Z"),
            ]
        ),
    )
    asyncio.run(service.sync_incremental())

    async def _flags():
        rows = await db.fetch_all("SELECT item_id, time_flags FROM search_entries")
        return {r["item_id"]: int(r["time_flags"]) for r in rows}

    flags = asyncio.run(_flags())
    assert flags["ok"] == 0
    assert flags["missing"] == TIME_FLAG_MISSING
    assert flags["future"] == TIME_FLAG_FUTURE
    assert flags["old"] == TIME_FLAG_TOO_OLD


# -- 时间线 API：timeCredibility + sort=received -------------------------------


class ListFakeAdapter:
    """GET /api/v1/entries 的适配器替身：固定页内容。"""

    def __init__(self, refs: list[str]):
        self.refs = refs

    async def list_entries(self, *, view="all", feed_url=None, category_id=None, source_type=None, continuation=None):
        items = [
            EntryListItem(
                entryRef=ref,
                title=f"T-{ref}",
                feedTitle="Example",
                read=False,
                starred=False,
            )
            for ref in self.refs
        ]
        return EntryPage(items=items, upstreamContinuation=None)


def _wire_list_adapter(refs):
    app.state.freshrss_adapter = ListFakeAdapter(refs)


def test_entries_route_attaches_credibility_and_sort(client):
    refs = [encode_entry_ref(item_id) for item_id in ("a", "b", "c")]

    async def _seed():
        db = app.state.db
        await db.migrate()
        rows = [
            # (item_id, fetched_at, time_flags) —— b 最新接收、有 future 异常
            ("a", 1000, TIME_FLAG_TOO_OLD),
            ("b", 3000, TIME_FLAG_FUTURE),
            ("c", 2000, 0),
        ]
        for item_id, fetched_at, flags in rows:
            ref = encode_entry_ref(item_id)
            await db.execute(
                "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at, time_flags) VALUES (?, ?, 'https://e.example/f', '源', 't', '', '', '', '2026-09-01T00:00:00Z', 0, 0, ?, ?)",
                (item_id, ref, fetched_at, flags),
            )

    asyncio.run(_seed())

    _wire_list_adapter(refs)
    try:
        default_page = client.get("/api/v1/entries").json()
        received_page = client.get("/api/v1/entries?sort=received").json()
    finally:
        app.state.freshrss_adapter = None

    # timeCredibility 附加（投影覆盖的条目）；顺序：默认 = 上游原序
    assert [i["entryRef"] for i in default_page["items"]] == refs
    cred = {i["entryRef"]: i["timeCredibility"] for i in default_page["items"]}
    assert cred[refs[0]] == "too_old"
    assert cred[refs[1]] == "future"
    assert cred[refs[2]] is None, "无异常 → null（不冒充正常）"

    # sort=received：服务端按接收时间降序重排（b(3000) > c(2000) > a(1000)）
    assert [i["entryRef"] for i in received_page["items"]] == [
        refs[1],
        refs[2],
        refs[0],
    ]


def test_sort_received_unknown_entries_keep_original_order(client):
    known = encode_entry_ref("known")
    unknown = encode_entry_ref("not-projected")

    async def _seed():
        db = app.state.db
        await db.migrate()
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES ('known', ?, 'https://e.example/f', '源', 't', '', '', '', '2026-09-01T00:00:00Z', 0, 0, 5000)",
            (known,),
        )

    asyncio.run(_seed())
    _wire_list_adapter([unknown, known])  # 上游原序：未知在前
    try:
        page = client.get("/api/v1/entries?sort=received").json()
    finally:
        app.state.freshrss_adapter = None

    assert [i["entryRef"] for i in page["items"]] == [known, unknown], (
        "有接收时间的条目排前；未知条目保持原序垫底（不臆造时间）"
    )
    assert page["items"][1]["timeCredibility"] is None
