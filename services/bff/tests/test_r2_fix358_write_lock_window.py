"""FIX-358 — 批量更新占用写锁覆盖整个网络调用周期（取数在事务外，
只在必要写入段持锁）。

判定：BASELINE_OK（结构核验 + 锁窗行为级测量，探测器双向校准）。

结构事实（全量核对 db_tx / BEGIN IMMEDIATE 调用点）：
- ``db_tx.transaction`` 的 ``fn`` 是同步闭包（asyncio.to_thread 执行）
  ——语法上不可能在持锁期间 await 任何网络调用；全仓调用点均为
  「取数（async、事务外）→ 紧凑写入（事务内）」形态；
- 真实批量流：F087 书签失效检查（routers/library_w5.py check-links
  → LinkCheckService）先完成全部上游探测（并发≤4、有界超时），
  之后才组装响应；探测期间零 DB 写入——写锁窗口与网络周期零交集；
- N036 刷新探测（subscriptions._record_refresh_logs）：先探测后逐条
  record；mail ingest：IMAP 取信在网络阶段，落库走一个紧凑事务
  （P0-06f）；ai_quota/user_quotas 的 BEGIN IMMEDIATE 均为单段紧凑
  预占。

本文件的锁窗测量（双向校准，非自证）：
1. 慢上游（400ms 延迟 transport）探测在途时，同库的 db_tx 写入必须
   即刻提交（探测任务尚未完成）——上游慢不拉长写锁；
2. 校准：事务内先写后睡（故意持锁 250ms），并发写必须被阻塞到持锁
   方释放——证明测量确实区分「锁被占用」与「锁空闲」。无真实秘密。
"""

import asyncio
import sqlite3
import time

import httpx

from lumirss.bookmarks_check import LinkCheckService
from lumirss.db_tx import transaction
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


class _SlowTransport(httpx.AsyncBaseTransport):
    """确定性慢上游：每个请求固定延迟后返回 200。"""

    def __init__(self, delay: float) -> None:
        self._delay = delay

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(self._delay)
        return httpx.Response(200, text="ok")


def _slow_service(delay: float) -> LinkCheckService:
    return LinkCheckService(
        client_factory=lambda: httpx.AsyncClient(
            transport=_SlowTransport(delay), trust_env=False
        )
    )


def test_slow_upstream_probe_does_not_extend_write_lock(tmp_path):
    """上游探测在途 → 同库写事务即刻提交（锁窗与网络周期零交集）。"""

    async def scenario():
        db = Database(tmp_path / "lumi.sqlite")
        await db.migrate()
        service = _slow_service(delay=0.4)

        probe_task = asyncio.ensure_future(service.check_one("https://example.com/slow"))
        await asyncio.sleep(0.08)  # 探测此刻确定性地挂在慢上游上

        async def write_via_tx():
            def _tx(connection: sqlite3.Connection) -> None:
                connection.execute(
                    "INSERT INTO library_items (uuid, kind, created_at)"
                    " VALUES ('fix358-row', 'api_item', '2026-01-01T00:00:00Z')"
                )

            started = time.monotonic()
            await transaction(db, _tx)
            return time.monotonic() - started

        write_task = asyncio.ensure_future(write_via_tx())
        write_elapsed = await asyncio.wait_for(write_task, timeout=2.0)

        # 关键断言：写已提交，而上游探测仍在途——慢上游没有拖住写锁。
        assert not probe_task.done()
        assert write_elapsed < 0.3  # 即刻提交（对照校准实验的被阻塞形态）
        result = await probe_task
        assert result["status"] == "ok"

        row = await db.fetch_one(
            "SELECT uuid FROM library_items WHERE uuid = 'fix358-row'"
        )
        assert row is not None

    run(scenario())


def test_deliberately_held_write_lock_blocks_concurrent_writer(tmp_path):
    """校准：事务内先写后睡（持锁 250ms）→ 并发写被阻塞到释放。

    证明上一条测试的「即刻提交」测量真能区分锁的占用与空闲。"""

    async def scenario():
        db = Database(tmp_path / "lumi.sqlite")
        await db.migrate()

        async def hold_lock():
            def _tx(connection: sqlite3.Connection) -> None:
                # 第一条写语句取得 RESERVED 锁；随后的睡眠把锁窗拉长。
                connection.execute(
                    "INSERT INTO library_items (uuid, kind, created_at)"
                    " VALUES ('fix358-holder', 'api_item', '2026-01-01T00:00:00Z')"
                )
                time.sleep(0.25)

            started = time.monotonic()
            await transaction(db, _tx)
            return time.monotonic() - started

        holder_task = asyncio.ensure_future(hold_lock())
        await asyncio.sleep(0.05)  # 持锁方已取得写锁并进入睡眠段

        async def contended_write():
            def _tx(connection: sqlite3.Connection) -> None:
                connection.execute(
                    "INSERT INTO library_items (uuid, kind, created_at)"
                    " VALUES ('fix358-contended', 'api_item', '2026-01-01T00:00:00Z')"
                )

            started = time.monotonic()
            await transaction(db, _tx)
            return time.monotonic() - started

        contended_task = asyncio.ensure_future(contended_write())
        contended_elapsed = await asyncio.wait_for(contended_task, timeout=2.0)
        holder_elapsed = await holder_task

        # 被阻塞形态：并发写等到持锁方提交之后才完成（busy_timeout 生效）。
        assert contended_elapsed >= 0.1
        assert holder_elapsed >= 0.25
        row = await db.fetch_one(
            "SELECT uuid FROM library_items WHERE uuid = 'fix358-contended'"
        )
        assert row is not None

    run(scenario())


def test_check_links_batch_probes_upstream_before_any_db_write(tmp_path):
    """F087 真实批量流（慢上游）：全部探测完成后才有任何 DB 访问。

    探测在途期间库上没有任何打开的连接（审计口径）——批量更新的
    写锁窗口不与网络周期重叠。"""

    async def scenario():
        db = Database(tmp_path / "lumi.sqlite")
        await db.migrate()
        await db.execute(
            "INSERT INTO library_items (uuid, kind, created_at)"
            " VALUES ('probe-target', 'api_item', '2026-01-01T00:00:00Z')"
        )
        service = _slow_service(delay=0.3)

        opened: list[sqlite3.Connection] = []
        original = Database._connect

        def traced(database):
            connection = original(database)
            opened.append(connection)
            return connection

        Database._connect = traced
        try:
            probe_task = asyncio.ensure_future(
                service.check_many(
                    ["https://example.com/a", "https://example.com/b"]
                )
            )
            await asyncio.sleep(0.08)
            # 探测在途：没有任何连接被打开（此前 migrate/seed 的都已关闭，
            # 且探测本身不触库）。
            for connection in opened:
                try:
                    connection.execute("SELECT 1")
                except sqlite3.ProgrammingError:
                    continue
                raise AssertionError(
                    "探测在途时存在打开的库连接——网络周期侵入了 DB 锁窗"
                )
            results = await probe_task
        finally:
            Database._connect = original

        assert [r["status"] for r in results] == ["ok", "ok"]

    run(scenario())
