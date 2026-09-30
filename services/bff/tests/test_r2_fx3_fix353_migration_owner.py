"""FIX-353 — 并发启动同时运行同一迁移：所有权唯一，失败实例不报 ready。

裁决：BASELINE_OK（等价机制证据；不改 migrations.py 源码）。

跨进程等价机制（storage.py 注释明示 FIX-353 跟踪点）：
- 每条待应用迁移在自己的 ``BEGIN IMMEDIATE`` 事务里执行——两个进程
  同时启动时，SQLite 写锁保证迁移语句级互斥，输家等赢家提交后才拿到
  写锁；
- 输家启动时读到的 ``applied`` 集合是陈旧的（赢家尚未提交），于是会在
  自己的事务里重放迁移语句，最后 ``INSERT INTO schema_migrations`` 撞
  ``version INTEGER PRIMARY KEY`` ——重放要么撞非幂等语句、要么撞主键，
  整体回滚并抛 DatabaseError：版本入账权唯一（恰好一个进程记录）；
- Database.migrate 失败不吞错、_migrated 不置位；lifespan 的
  ``ensure_owner_migration`` 在任何调度器/ready 之前 await 它
  （ARCH-08 顺序，tests/test_arch08_runtime.py 钉死）——输家进程在
  启动第一步即失败，绝不可能继续报 ready。

测试注入与 FIX-352 同口径：monkeypatch MIGRATIONS_DIR 注入临时迁移
目录，不改任何源码；hook ``list_migrations`` 只为确定性重放「输家
读集合在先、赢家提交在后」的窗口，非对抗 hook。
"""

import asyncio
import sqlite3

import pytest

import lumirss.migrations as migrations
from lumirss.migrations import DatabaseError, schema_version
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

MIGRATION_NAME = "9901_owner.sql"
MIGRATION_SQL = (
    "CREATE TABLE fix9901_owner (id INTEGER PRIMARY KEY, tag TEXT NOT NULL);\n"
    "INSERT INTO fix9901_owner (tag) VALUES ('winner');\n"
)


def run(coroutine):
    return asyncio.run(coroutine)


def _seed_dir(tmp_path):
    directory = tmp_path / "probe-353-owner"
    directory.mkdir()
    (directory / MIGRATION_NAME).write_text(MIGRATION_SQL, encoding="utf-8")
    return directory


def _raw(db_path):
    return sqlite3.connect(str(db_path))


def _race_scenario(tmp_path, monkeypatch):
    """构造「输家先读 applied、赢家后提交」的确定性窗口。

    返回 (winner_db, loser_db)；loser 的 migrate() 在 hook 内先让赢家
    完整应用 9901，再带着陈旧集合继续——正是双进程冷启动的交错。"""
    directory = _seed_dir(tmp_path)
    db_path = tmp_path / "lumi.sqlite"
    winner_db = Database(db_path)
    loser_db = Database(db_path)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", directory)
    real_list = migrations.list_migrations
    winner_state = {"ran": False}

    def hooked_list():
        if not winner_state["ran"]:
            winner_state["ran"] = True
            # 赢家 = 直接跑 apply_migrations（绕开同进程 path 锁，等价
            # 另一个进程独立执行）；提交 9901 后输家才继续。
            applied = migrations.apply_migrations(winner_db)
            assert applied == [9901]
        return real_list()

    monkeypatch.setattr(migrations, "list_migrations", hooked_list)
    return winner_db, loser_db, db_path


def test_migration_ownership_unique_loser_fails_loudly(tmp_path, monkeypatch):
    """输家重放迁移 → 撞非幂等语句回滚并抛 DatabaseError；版本恰好被
    赢家记录一次；输家的部分效果随事务消失。"""
    winner_db, loser_db, db_path = _race_scenario(tmp_path, monkeypatch)

    with pytest.raises(DatabaseError, match="9901_owner"):
        run(loser_db.migrate())

    connection = _raw(db_path)
    try:
        owners = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 9901"
        ).fetchone()
        rows = connection.execute(
            "SELECT COUNT(*) FROM fix9901_owner"
        ).fetchone()
    finally:
        connection.close()
    # 所有权唯一：恰好一个入账者（赢家）；输家 INSERT 未发生。
    assert int(owners[0]) == 1
    assert int(rows[0]) == 1  # 只有赢家的 'winner' 行；输家重放已回滚
    assert schema_version(winner_db) == 9901


def test_failed_loser_never_reports_ready_and_converges_on_retry(tmp_path, monkeypatch):
    """启动入口 ensure_owner_migration（lifespan ready 前第一步）原样
    传播 DatabaseError → 失败实例到不了 ready；修后重试幂等收敛（不
    重复应用、不残留半成品）。"""
    from lumirss.owner_migration import ensure_owner_migration

    _winner, loser_db, _db_path = _race_scenario(tmp_path, monkeypatch)
    secrets = SecretsStore(tmp_path / "control-secrets.json")

    with pytest.raises(DatabaseError):
        run(ensure_owner_migration(loser_db, secrets))

    # 失败后 _migrated 未置位：重试读取最新台账 → 9901 已入账 → 干净
    # 跳过（第二实例重启场景的收敛语义）。
    applied = run(loser_db.migrate())
    assert applied == []
    assert schema_version(loser_db) == 9901


def test_same_process_double_init_applies_once(tmp_path, monkeypatch):
    """同进程双 Database 句柄并发首初始化：path_migrate_lock 串行化，
    迁移只应用一次（FIX-211 进程内口径 + FIX-353 跨进程口径互补）。"""

    async def scenario():
        directory = _seed_dir(tmp_path)
        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", directory)
        first = Database(tmp_path / "lumi.sqlite")
        second = Database(tmp_path / "lumi.sqlite")
        first_task = asyncio.ensure_future(first.migrate())
        second_task = asyncio.ensure_future(second.migrate())
        return await first_task, await second_task

    applied_first, applied_second = run(scenario())
    connection = _raw(tmp_path / "lumi.sqlite")
    try:
        owners = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 9901"
        ).fetchone()
    finally:
        connection.close()
    assert int(owners[0]) == 1
    assert schema_version(Database(tmp_path / "lumi.sqlite")) == 9901
    # 两个句柄都成功返回；入账恰好一次（谁先抢到锁谁是 [9901]，
    # 另一个返回 []——进程内绝无双重应用）。
    assert 0 <= len(applied_first) <= 1 and 0 <= len(applied_second) <= 1
    assert len(applied_first) + len(applied_second) == 1
