"""FIX-352 — 迁移中途失败不得写入已应用版本（提交边界核验）。

contracts（migrations.py，READ-ONLY 本任务）：
- 每条待应用迁移在自己的 BEGIN IMMEDIATE 事务里执行；
- schema_migrations 的版本记录 INSERT 与该迁移的业务 DDL/DML 在
  同一事务内提交——第二条语句失败 → 整条迁移回滚：版本不入账、
  前面语句的效果一并消失；
- 失败不污染台账：先前已应用的版本保持原样。

全部通过公共 seam（Database.migrate → apply_migrations）+ TEST 内
monkeypatch MIGRATIONS_DIR 注入临时迁移目录验证，不改源码。
"""

import asyncio
import sqlite3

import pytest

from lumirss.migrations import DatabaseError, schema_version
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _migrations_dir(tmp_path, name):
    directory = tmp_path / name
    directory.mkdir()
    return directory


def _raw(db_path):
    """裸连接绕开 Database：只读核对落盘事实（自行 close）。"""
    return sqlite3.connect(str(db_path))


def test_second_statement_failure_leaves_version_unrecorded_and_dml_rolled_back(
    tmp_path, monkeypatch
):
    """第一条 DML 已生效、第二条失败 → 版本不入账 + 第一条效果回滚。"""
    import lumirss.migrations as migrations

    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    baseline = schema_version(db)

    directory = _migrations_dir(tmp_path, "probe-352-fail")
    # 语句 1（DML，对既有表）：写入后若未回滚即为泄漏；语句 2：指向
    # 不存在的表，必然失败。
    (directory / "9901_dml_then_fail.sql").write_text(
        "INSERT INTO lumi_settings (key, value, updated_at)"
        " VALUES ('fix352.canary', '1', '2026-01-01T00:00:00Z');\n"
        "INSERT INTO fix352_no_such_table (id) VALUES (1);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", directory)

    reopened = Database(tmp_path / "lumi.sqlite")
    with pytest.raises(DatabaseError, match="9901_dml_then_fail"):
        run(reopened.migrate())

    connection = _raw(tmp_path / "lumi.sqlite")
    try:
        recorded = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 9901"
        ).fetchone()
        canary = connection.execute(
            "SELECT COUNT(*) FROM lumi_settings WHERE key = 'fix352.canary'"
        ).fetchone()
    finally:
        connection.close()
    assert int(recorded[0]) == 0, "失败的迁移版本不得写入 schema_migrations"
    assert int(canary[0]) == 0, "同迁移内已执行语句的效果必须随事务回滚"
    assert schema_version(db) == baseline, "台账最大版本保持失败前状态"


def test_failure_does_not_disturb_previously_applied_versions(tmp_path, monkeypatch):
    """两条新迁移：第一条成功、第二条失败 → 只有第一条入账。"""
    import lumirss.migrations as migrations

    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())

    directory = _migrations_dir(tmp_path, "probe-352-partial")
    (directory / "9901_good.sql").write_text(
        "CREATE TABLE fix352_good (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    (directory / "9902_bad.sql").write_text(
        "CREATE TABLE fix352_bad (id TEXT PRIMARY KEY);\n"
        "INSERT INTO fix352_no_such_table (id) VALUES (1);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", directory)

    reopened = Database(tmp_path / "lumi.sqlite")
    with pytest.raises(DatabaseError, match="9902_bad"):
        run(reopened.migrate())

    assert schema_version(db) == 9901
    connection = _raw(tmp_path / "lumi.sqlite")
    try:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        good_row = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 9901"
        ).fetchone()
        bad_row = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 9902"
        ).fetchone()
    finally:
        connection.close()
    assert "fix352_good" in names
    assert "fix352_bad" not in names  # DDL 也随事务回滚
    assert int(good_row[0]) == 1
    assert int(bad_row[0]) == 0


def test_unrecorded_version_allows_clean_retry_with_fixed_content(
    tmp_path, monkeypatch
):
    """失败后修正文件重试（同一版本号）→ 正常应用并入账——证明失败
    时确实没有留下「已应用」标记（记录与效果同事务，绝无幽灵版本）。"""
    import lumirss.migrations as migrations

    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())

    directory = _migrations_dir(tmp_path, "probe-352-retry")
    (directory / "9901_retry.sql").write_text(
        "INSERT INTO fix352_no_such_table (id) VALUES (1);\n", encoding="utf-8"
    )
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", directory)

    first = Database(tmp_path / "lumi.sqlite")
    with pytest.raises(DatabaseError, match="9901_retry"):
        run(first.migrate())

    # 同目录、同版本号，换成可成功的内容：能再次执行 = 上次未入账。
    (directory / "9901_retry.sql").write_text(
        "CREATE TABLE fix352_retried (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    reopened = Database(tmp_path / "lumi.sqlite")
    applied = run(reopened.migrate())
    assert applied == [9901]

    connection = _raw(tmp_path / "lumi.sqlite")
    try:
        recorded = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 9901"
        ).fetchone()
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()
    assert int(recorded[0]) == 1
    assert "fix352_retried" in names
    assert schema_version(reopened) == 9901
