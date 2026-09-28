"""FIX-231 — 条目身份作用域：同 ID 的两篇不同文章不归并。

FreshRSS 承诺条目 ID 在账户内全局唯一；当上游异常地让两个不同 feed
交付同一 ID 时，投影不得把两篇文章当作同一条目做状态/元数据归并：

- 增量 replace：跨 feed 的同 ID 交付绝不与既有行做跨文章修订捕获、
  不保留属于旧文章的变体/修订、不继承其 content_max_len；新行如实
  携带本次交付自身的状态。
- 全量 rebuild：同 ID 碰撞不再让 IntegrityError 中止整个重建
  （投影被冻结在 rebuild_incomplete）；按交付顺序最后一个交付生效。
- 正常同 feed 重交付：修订/变体捕获行为保持不变。
"""

import asyncio
import secrets as _secrets

from lumirss.entryref import encode_entry_ref
from lumirss.models import EntryDocument
from lumirss.search_writer import SearchEntryWriter
from lumirss.storage import Database

FAKE = "fake-" + _secrets.token_urlsafe(6)


def doc(item_id: str, feed_url: str, title: str, html: str, *, read: bool = False, starred: bool = False) -> EntryDocument:
    return EntryDocument(
        item_id=item_id,
        entryRef=encode_entry_ref(item_id),
        feedUrl=feed_url,
        feedTitle=f"feed-{feed_url[-4:]}",
        title=title,
        author=None,
        url=f"{feed_url}article",
        publishedAt="2026-09-01T00:00:00Z",
        read=read,
        starred=starred,
        contentText="text " + title,
        contentHtml=html,
    )


FEED_A = "https://a.example/feed.xml"
FEED_B = "https://b.example/feed.xml"
SHARED_ID = "tag:google.com,2005:reader/item/0000000000000099"


def make_db(tmp_path) -> Database:
    return Database(str(tmp_path / f"fix231-{FAKE[:6]}.sqlite"))


def test_fix231_cross_feed_same_id_delivery_records_no_cross_article_revision(tmp_path):
    """feed B 的同 ID 交付不得与 feed A 的旧内容做修订 diff/变体保留。"""
    db = make_db(tmp_path)

    async def scenario():
        await db.migrate()
        writer = SearchEntryWriter(db)
        a_html = "<p>" + "A 篇文章内容" * 50 + "</p>"
        b_html = "<p>B 篇完全不同的文章</p>"
        await writer.replace_entries(
            [doc(SHARED_ID, FEED_A, "A 的文章", a_html, read=True)],
            feed_urls=[FEED_A],
            fetched_at=1000,
        )
        await writer.replace_entries(
            [doc(SHARED_ID, FEED_B, "B 的文章", b_html, starred=True)],
            feed_urls=[FEED_B],
            fetched_at=2000,
        )
        return a_html, b_html

    a_html, b_html = asyncio.run(scenario())

    async def read_back():
        row = await db.fetch_one(
            "SELECT * FROM search_entries WHERE item_id = ?", (SHARED_ID,)
        )
        variants = await db.fetch_all(
            "SELECT content_html FROM entry_content_variants WHERE entry_ref = ?",
            (encode_entry_ref(SHARED_ID),),
        )
        revisions = await db.fetch_all(
            "SELECT prev_title, new_title FROM entry_revisions WHERE entry_ref = ?",
            (encode_entry_ref(SHARED_ID),),
        )
        return row, variants, revisions

    row, variants, revisions = asyncio.run(read_back())

    assert row is not None
    # 新行如实携带本次（feed B）交付的状态，不继承 feed A 的 read。
    assert row["feed_url"] == FEED_B
    assert row["title"] == "B 的文章"
    assert int(row["read"]) == 0
    assert int(row["starred"]) == 1
    # 无跨文章修订记录（旧实现会把 A 的标题/内容与 B diff 出一条假修订）。
    assert revisions == [], "跨 feed 同 ID 不得产生跨文章修订"
    # 保留变体不属于旧文章：A 的正文不得残留。
    for variant in variants:
        assert a_html not in str(variant["content_html"])
    # 不继承旧文章的内容记忆：content_max_len = 本次交付长度。
    assert int(row["content_max_len"]) == len(b_html)


def test_fix231_rebuild_survives_same_id_collision_last_delivery_wins(tmp_path):
    """rebuild 阶段同 ID 碰撞不得中止重建（旧实现 UNIQUE 冲突抛
    IntegrityError，rebuild_incomplete 永久置位）；最后交付者生效。"""
    from lumirss.search_index import SearchIndexService

    class CollidingAdapter:
        """同一次 rebuild 内跨页交付同 ID：第 1 页 A，第 2 页 B（碰撞）。"""

        def __init__(self) -> None:
            self.turn = 0

        async def list_entry_documents(self, *, continuation=None, limit=50):
            from lumirss.models import EntryDocumentPage

            if continuation is None:
                payload = [
                    doc(SHARED_ID, FEED_A, "A 的文章", "<p>A</p>", read=True)
                ]
                return EntryDocumentPage(
                    documents=payload, upstreamContinuation="2"
                )
            payload = [
                doc(SHARED_ID, FEED_B, "B 的文章", "<p>B</p>", starred=True)
            ]
            return EntryDocumentPage(documents=payload, upstreamContinuation=None)

        async def list_feeds(self):
            from lumirss.adapters.freshrss import Feed

            return [
                Feed(title="feed-A", feed_url=FEED_A),
                Feed(title="feed-B", feed_url=FEED_B),
            ]

    db = make_db(tmp_path)
    service = SearchIndexService(db, CollidingAdapter())

    async def scenario():
        await service.rebuild()  # 单次 rebuild 内第 1 页 A + 第 2 页 B（同 ID）
        row = await db.fetch_one(
            "SELECT * FROM search_entries WHERE item_id = ?", (SHARED_ID,)
        )
        incomplete = await db.fetch_one(
            "SELECT value FROM search_meta WHERE key = 'rebuild_incomplete'"
        )
        count = await db.fetch_one("SELECT COUNT(*) AS n FROM search_entries")
        return row, incomplete, int(count["n"]) if count else 0

    row, incomplete, count = asyncio.run(scenario())

    assert incomplete is not None and str(incomplete["value"]) == "0", "碰撞不得让重建卡在 incomplete"
    assert row is not None
    assert row["feed_url"] == FEED_B, "最后一次交付生效"
    assert int(row["starred"]) == 1
    assert count == 1


def test_fix231_same_feed_redelivery_keeps_revision_capture(tmp_path):
    """正常同 feed 重交付（内容变化）仍记录修订——修复不得误伤。"""
    db = make_db(tmp_path)

    async def scenario():
        await db.migrate()
        writer = SearchEntryWriter(db)
        await writer.replace_entries(
            [doc(SHARED_ID, FEED_A, "原标题", "<p>v1</p>")],
            feed_urls=[FEED_A],
            fetched_at=1000,
        )
        await writer.replace_entries(
            [doc(SHARED_ID, FEED_A, "新标题", "<p>v2</p>")],
            feed_urls=[FEED_A],
            fetched_at=2000,
        )

    asyncio.run(scenario())

    async def read_back():
        return await db.fetch_all(
            "SELECT prev_title, new_title FROM entry_revisions WHERE entry_ref = ?",
            (encode_entry_ref(SHARED_ID),),
        )

    revisions = asyncio.run(read_back())
    assert len(revisions) == 1
    assert str(revisions[0]["prev_title"]) == "原标题"
    assert str(revisions[0]["new_title"]) == "新标题"
