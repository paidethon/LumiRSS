"""FIX-248 — 进程重启遗留的 running 状态可恢复（refresh 侧基线验证）。

盘点（负向契约的诚实证据）：refresh 链路没有以「running 标志」持久化
的任务状态——后台循环是进程内 asyncio task，由 ARCH-08 的
SchedulerRegistry 单属主管理；F050 探测与 api_sources 抓取都是
request-scoped；N129 预算是纯时间基。唯一一处持久化 running 痕迹是
投影重建的 ``rebuild_incomplete`` meta 标志 + 可能残留的
``search_rebuild_stage`` 暂存表。

既有测试（test_search_index.test_failed_rebuild_keeps_previous_index_and_heals）
覆盖了**进程内**异常路径（异常处理器顺势清场）。本文件补上硬崩溃
（kill -9，异常处理器没机会跑）变体：标志 + 孤儿暂存表原样留在磁盘
上，**新进程**（全新 service 实例、同一 DB 文件）的下一次 maybe_sync
必须原样接管——孤儿表被丢弃、其行数绝不泄漏进活投影、标志清零、
投影以健康上游重建。
"""

import asyncio

from lumirss.adapters.freshrss import Feed
from lumirss.models import EntryDocument, EntryDocumentPage
from lumirss.search_index import SearchIndexService

FEEDS = [Feed(title="示例源", feed_url="https://example.com/feed.xml")]


def run(coroutine):
    return asyncio.run(coroutine)


def doc(item_id: str, title: str) -> EntryDocument:
    return EntryDocument(
        item_id=item_id,
        entryRef=f"e1.{item_id}",
        feedUrl="https://example.com/feed.xml",
        feedTitle="示例源",
        title=title,
        author=None,
        url="https://example.com/a",
        publishedAt="2026-09-01T00:00:00Z",
        read=False,
        starred=False,
        contentText="body " + title,
    )


class FakeAdapter:
    def __init__(self, documents):
        self._documents = documents

    async def list_entry_documents(self, *, continuation=None, limit=50):
        docs = self._documents
        start = int(continuation) if continuation else 0
        page = docs[start : start + limit]
        next_cont = str(start + limit) if start + limit < len(docs) else None
        return EntryDocumentPage(documents=page, upstreamContinuation=next_cont)

    async def list_feeds(self):
        return FEEDS


def make_service(db_path, documents) -> SearchIndexService:
    from lumirss.storage import Database

    db = Database(db_path)
    return SearchIndexService(db, FakeAdapter(documents))


def test_crash_leftovers_are_taken_over_by_next_process(tmp_path):
    db_path = tmp_path / "fix248.sqlite"
    first = make_service(db_path, [doc("i1", "keep one"), doc("i2", "keep two")])
    report = run(first.rebuild())
    assert report["entryCount"] == 2

    # 硬崩溃模拟：绕过进程内异常处理器，直接把 running 痕迹留在磁盘。
    async def _plant_crash_leftovers():
        await first._db.migrate()
        await first._feeds.meta_set("rebuild_incomplete", "1")
        await first._db.execute(
            "CREATE TABLE search_rebuild_stage (item_id TEXT NOT NULL, entry_ref TEXT NOT NULL)"
        )
        await first._db.execute(
            "INSERT INTO search_rebuild_stage (item_id, entry_ref) VALUES (?, ?)",
            ("orphan-1", "e1.orphan-1"),
        )

    run(_plant_crash_leftovers())

    # 新进程：全新 service 实例（新连接、同 DB 文件）+ 已恢复的上游。
    second = make_service(
        db_path,
        [doc("i1", "keep one"), doc("i2", "keep two"), doc("i3", "new arrival")],
    )
    run(second.maybe_sync())

    async def _assert_healed():
        await second._db.migrate()
        flag = await second._store.meta_get("rebuild_incomplete")
        assert flag == "0", "接管后 running 标志必须清零"
        orphan = await second._db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'search_rebuild_stage'"
        )
        assert orphan is None, "孤儿暂存表必须被下一次重建丢弃"
        leaked = await second._db.fetch_one(
            "SELECT COUNT(*) AS n FROM search_entries WHERE item_id = 'orphan-1'"
        )
        assert int(leaked["n"]) == 0, "孤儿暂存行绝不泄漏进活投影"
        hit = await second._store.query(
            terms=["arrival"], feed_url=None, category_id=None,
            unread_only=False, starred_only=False,
            published_from=None, published_to=None, keyset=None, limit=5,
        )
        assert len(hit) == 1, "投影以健康上游完整重建"

    run(_assert_healed())
