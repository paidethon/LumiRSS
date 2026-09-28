"""FIX-357 — 事务取消后连接池返回脏事务（生命周期核验）。

连接生命周期事实（BASELINE_OK 的证据基础）：

- storage.py 的 Database 没有连接池：`_fetch_one/_fetch_all/_execute/
  _execute_many` 每次操作 `closing(self._connect())` 开新连接、操作
  结束即关闭——未提交事务随连接消亡（sqlite3 close 隐式回滚），下一
  次借用拿到的是全新连接；
- db_tx.transaction 在 BaseException 上显式 rollback 后 close——
  cancel（BaseException 家族）也走回滚；
- rag.py 的持久 vec 连接（`_vec_connection`，池大小 1）是唯一的
  长寿命连接：两个手写事务块（_mark_stale_sync / 重建写入）都是
  BEGIN → commit / `except BaseException: rollback; raise`。这些同步
  块经 asyncio.to_thread 执行，协程取消无法把块打断在半途——线程把
  事务走到 commit 或 rollback 才落地。

本文件把三种机制各写成一个行为级证据：失败/被弃的事务绝不让下一位
借用人看到脏状态或开放事务。
"""

import asyncio
import sqlite3

import pytest

from lumirss.db_tx import transaction
from lumirss.rag import RagService
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def test_per_operation_connection_dies_with_its_transaction(tmp_path):
    """核心库无池：被弃连接上的未提交事务随 close 消亡，下一位借用者
    拿到干净连接（无开放事务、无半途数据）。"""
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    run(db.execute("CREATE TABLE fix357_t (id TEXT PRIMARY KEY, note TEXT)"))

    # 模拟一次中途被弃的操作：开连接、BEGIN、写入、不提交直接关闭
    # （正是 closing() 在异常路径上的行为——close 隐式回滚）。
    abandoned = db._connect()  # noqa: SLF001 — lifecycle seam under test
    abandoned.execute("BEGIN")
    abandoned.execute(
        "INSERT INTO fix357_t (id, note) VALUES ('dirty', '未提交即弃')"
    )
    assert abandoned.in_transaction is True
    abandoned.close()

    # 下一次借用 = 全新连接：没有开放事务，也没有脏行。
    fresh = db._connect()  # noqa: SLF001
    try:
        assert fresh.in_transaction is False
        assert fresh.execute("SELECT COUNT(*) FROM fix357_t").fetchone()[0] == 0
    finally:
        fresh.close()
    # 正常写路径继续可用。
    run(db.execute("INSERT INTO fix357_t (id, note) VALUES ('clean', '后续操作')"))
    assert run(db.fetch_one("SELECT COUNT(*) AS n FROM fix357_t"))["n"] == 1


def test_transaction_helper_rolls_back_on_base_exception_and_releases(tmp_path):
    """db_tx.transaction：fn 中途抛错（含 cancel 家族）→ 回滚 + 关闭，
    下一次 transaction() 借到的新连接看不到半途状态。"""
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    run(db.execute("CREATE TABLE fix357_tx (id INTEGER PRIMARY KEY, v TEXT)"))

    def _boom(connection):
        connection.execute(
            "INSERT INTO fix357_tx (id, v) VALUES (1, '即将回滚')"
        )
        raise ValueError("操作中途失败（等价于一次取消）")

    with pytest.raises(ValueError):
        run(transaction(db, _boom))

    row = run(db.fetch_one("SELECT COUNT(*) AS n FROM fix357_tx"))
    assert row["n"] == 0, "失败事务的写入必须整体回滚"

    # 下一位借用者：干净开启、正常提交。
    def _append(connection):
        connection.execute("INSERT INTO fix357_tx (id, v) VALUES (2, '后来者')")
        return True

    assert run(transaction(db, _append)) is True
    assert run(db.fetch_one("SELECT COUNT(*) AS n FROM fix357_tx"))["n"] == 1


def test_persistent_vec_connection_left_clean_after_failed_transaction(tmp_path):
    """rag 持久 vec 连接（池大小 1）：事务中途失败 → 连接无开放事务，
    下一位借用人可在同一连接上重建表并完成自己的事务。"""
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    service = RagService(db)
    assert service._ensure_vec_table() is True

    # 制造半途失败：事务 BEGIN 后 vec 虚表已被拆除 → 首个 DELETE 失败 →
    # `except BaseException: rollback` 路径（与协程取消同族）。
    # （只拆 rag_vec——它由 _ensure_vec_table 管辖、可重建；
    #   rag_chunks 是 0013 迁移的常规表，不进该恢复路径。）
    connection = service._vec_connection()
    connection.execute("DROP TABLE rag_vec")
    connection.commit()
    with pytest.raises(sqlite3.OperationalError):
        service._mark_stale_sync(["ref-failed"])

    # 下一位借用者拿到的是干净连接：无开放事务、可继续工作。
    same_connection = service._vec_connection()
    assert same_connection is connection, "vec 连接是池大小 1 的持久连接"
    assert same_connection.in_transaction is False

    service._vec_ready = False  # 让下一位借用人重建 vec 表
    assert service._ensure_vec_table() is True
    assert service._mark_stale_sync(["ref-next"]) == 0
    assert same_connection.in_transaction is False
