"""FIX-355 — 长读事务阻碍 WAL 回收而无限涨盘（读取快照必须短命）。

判定：BASELINE_OK（连接生命周期审计 + WAL 检查点探测器双向校准）。

架构事实（storage.py docstring 与实现一致）：
- Database 的每条语句都是「一连接一操作」：``with closing(
  self._connect())``——读连接在语句结束后立即关闭，WAL 里不可能有
  跨语句存活的读取快照；
- db_tx.transaction 也是一连接一事务：commit/rollback 后 close，
  异常路径同样回滚并关闭；
- 导出面（lumi_data_export / lumi_data_wizard.collect_export_components）
  是有限次分组件查询后整体物化——不存在「游标横跨整个流式传输」的
  长读事务（FIX-364 已证响应体是物化 bytes，无流式游标）；
- RAG 语料读取为 keyset 分页（_corpus_page，每页新快照）；写索引为
  有界 BEGIN/COMMIT 分片。

本文件的两个探测器：
1. 连接泄漏审计：导出全路径打开的每一条连接在导出结束后必须全部
   处于关闭态（对关闭连接 execute 必抛 ProgrammingError）——没有
   连接就不可能有跨流存活的读取快照；
2. WAL TRUNCATE 检查点：导出完成后 ``PRAGMA wal_checkpoint(
   TRUNCATE)`` 必须 busy=0 且 WAL 文件归零（无读取快照阻挡回收）；
   并以「故意持有快照 → busy=1、释放 → busy=0」双向校准探测器，
   证明该判定真能抓住缺陷类。无真实秘密。
"""

import asyncio
import os
import sqlite3

import pytest

import lumirss.storage as storage
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


class _ConnectionAudit:
    """记录 Database 打开的每条连接，供生命周期断言。"""

    def __init__(self) -> None:
        self.connections: list[sqlite3.Connection] = []
        self._original = storage.Database._connect

    def __enter__(self):
        def traced(database):
            connection = self._original(database)
            self.connections.append(connection)
            return connection

        storage.Database._connect = traced
        return self

    def __exit__(self, *_exc):
        storage.Database._connect = self._original

    def assert_all_closed(self) -> int:
        opened = len(self.connections)
        assert opened > 0, "audit captured no connections — instrumentation broken"
        for connection in self.connections:
            with pytest.raises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
        return opened


def _seed_wal_frames(db_path: str, rows: int, prefix: str) -> sqlite3.Connection:
    """持久写连接批量提交——WAL 落帧且写连接保持打开（不触发
    close-checkpoint），让检查点探测有真实帧可回收。"""
    writer = sqlite3.connect(db_path)
    writer.execute("PRAGMA busy_timeout=5000")
    for index in range(rows):
        writer.execute(
            "INSERT INTO library_items (uuid, kind, created_at)"
            " VALUES (?, 'api_item', '2026-01-01T00:00:00Z')",
            (f"{prefix}-{index}",),
        )
    writer.commit()
    return writer


def test_export_closes_every_connection_it_opens(tmp_path):
    """导出全路径零连接泄漏：没有泄漏连接就不可能持有跨流读快照。"""
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    run(
        db.execute(
            "INSERT INTO library_items (uuid, kind, created_at)"
            " VALUES ('seed-1', 'api_item', '2026-01-01T00:00:00Z')"
        )
    )

    from lumirss.lumi_data_export import build_lumi_data_export
    from lumirss.lumi_data_wizard import collect_export_components

    async def scenario():
        with _ConnectionAudit() as audit:
            await build_lumi_data_export(db)
            await collect_export_components(db, control_adapter=None, read_adapter=None)
            # 并发读批量：同一审计窗内的 per-operation 连接同样必须全关。
            await asyncio.gather(
                *[
                    db.fetch_all(
                        "SELECT uuid FROM library_items WHERE uuid LIKE ?",
                        (f"%{i}%",),
                    )
                    for i in range(20)
                ]
            )
        return audit

    audit = run(scenario())
    opened = audit.assert_all_closed()
    assert opened >= 22  # 导出 + 组件收集 + 20 并发读——审计确实覆盖了热路径


def test_db_tx_failure_closes_connection_rollback_included(tmp_path):
    """db_tx.transaction 异常路径：连接回滚并关闭（快照/写锁即时释放）。"""
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())

    from lumirss.db_tx import transaction

    async def scenario():
        with _ConnectionAudit() as audit:
            with pytest.raises(RuntimeError):

                def _failing(connection):
                    connection.execute(
                        "INSERT INTO library_items (uuid, kind, created_at)"
                        " VALUES ('tx-orphan', 'api_item', '2026-01-01T00:00:00Z')"
                    )
                    raise RuntimeError("boom")

                await transaction(db, _failing)
        return audit

    audit = run(scenario())
    audit.assert_all_closed()
    # 回滚语义：失败事务的中间写入绝不落库。
    count = run(
        db.fetch_one("SELECT COUNT(*) AS n FROM library_items WHERE uuid = 'tx-orphan'")
    )
    assert count["n"] == 0


def test_wal_truncates_after_export_and_detector_detects_lingering_snapshot(tmp_path):
    """导出后 WAL 检查点必须成功；探测器以「故意持快照」双向校准。"""
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    writer = _seed_wal_frames(str(db.path), rows=200, prefix="fix355")

    from lumirss.lumi_data_export import build_lumi_data_export

    run(build_lumi_data_export(db))

    checker = sqlite3.connect(str(db.path))
    try:
        wal_path = f"{db.path}-wal"
        # 导出完成后：无读取快照阻挡 → TRUNCATE 成功且 WAL 文件归零。
        busy, _log, _checkpointed = checker.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        assert busy == 0
        assert os.path.getsize(wal_path) == 0

        # —— 校准 1：故意持有读取快照 → busy=1（探测器真能抓住缺陷）——
        writer.execute(
            "INSERT INTO library_items (uuid, kind, created_at)"
            " VALUES ('calibration-1', 'api_item', '2026-01-01T00:00:00Z')"
        )
        writer.commit()
        lingering = sqlite3.connect(str(db.path))
        lingering.execute("BEGIN")
        lingering.execute("SELECT COUNT(*) FROM library_items").fetchone()
        busy, log, _checkpointed = checker.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        assert busy == 1
        assert log > 0  # 快照阻挡下帧无法回收
        lingering.rollback()
        lingering.close()
        busy, _log, _checkpointed = checker.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        assert busy == 0
        assert os.path.getsize(wal_path) == 0
    finally:
        checker.close()
        writer.close()
