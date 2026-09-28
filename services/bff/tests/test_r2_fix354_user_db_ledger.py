"""FIX-354 — 用户库 schema 版本独立核验，不与控制库版本混用。

契约（0067 多账户隔离）：
- 每个用户库 <users_root>/<uid>/lumi.sqlite 拥有自己的
  schema_migrations 台账（apply_migrations 在该文件的连接上建表、
  记账），控制库台账永远不代言用户库；
- RoutingDatabase 的跳过条件只有两个：实例内 per-uid 缓存 +
  用户文件自身的台账——控制库再新也不会把落后（stale）的用户库
  跳过，用户库按自己的版本补齐它缺的迁移。

全部经公共 seam（RoutingDatabase.migrate / Database.migrate）+
TEST 内 monkeypatch MIGRATIONS_DIR 注入临时迁移目录验证。
"""

import asyncio
import sqlite3

from lumirss.migrations import list_migrations, schema_version
from lumirss.storage import Database
from lumirss.user_scope import RoutingDatabase, user_context


def run(coroutine):
    return asyncio.run(coroutine)


def _user_ledger(user_db_path):
    connection = sqlite3.connect(str(user_db_path))
    try:
        rows = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        return [int(row[0]) for row in rows]
    finally:
        connection.close()


def test_fresh_user_db_migrates_per_its_own_ledger_while_control_is_current(
    tmp_path,
):
    """控制库完全迁移后，全新用户库仍按自己的空台账应用全部迁移。"""
    control = Database(tmp_path / "control.sqlite")
    run(control.migrate())
    latest = list_migrations()[-1][0]
    assert schema_version(control) == latest

    router = RoutingDatabase(tmp_path / "control.sqlite", tmp_path / "users")
    with user_context("fresh354"):
        applied = run(router.migrate())

    # 用户库自己从头应用到最新（绝不是因「控制库已最新」而跳过）。
    assert applied == [version for version, _ in list_migrations()]
    assert _user_ledger(router.user_db_path("fresh354"))[-1] == latest

    # 第二个用户同样拿到自己的独立台账——账本在各自文件里。
    with user_context("fresh354b"):
        applied_b = run(router.migrate())
    assert applied_b == [version for version, _ in list_migrations()]
    assert _user_ledger(router.user_db_path("fresh354b"))[-1] == latest
    # 两个用户文件是两个不同的文件。
    assert router.user_db_path("fresh354") != router.user_db_path("fresh354b")


def test_stale_user_db_gets_its_own_pending_migrations(tmp_path, monkeypatch):
    """用户库落后时按自身版本补齐，即使控制库此时已完全迁移。"""
    import lumirss.migrations as migrations

    directory = tmp_path / "probe-354"
    directory.mkdir()
    (directory / "9901_fix354_a.sql").write_text(
        "CREATE TABLE fix354_a (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", directory)

    control_path = tmp_path / "control.sqlite"
    router = RoutingDatabase(control_path, tmp_path / "users")

    with user_context("stale354"):
        first = run(router.migrate())
    assert first == [9901]
    assert _user_ledger(router.user_db_path("stale354")) == [9901]

    # 新迁移只对后续打开者可见；控制库先完成升级（控制库台账 = 最新）。
    (directory / "9902_fix354_b.sql").write_text(
        "CREATE TABLE fix354_b (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    control = Database(control_path)
    run(control.migrate())
    assert schema_version(control) == 9902

    # 同实例：缓存失效后，用户库按自身台账补上 9902（不被控制库跳过）。
    router.invalidate_user_migration("stale354")
    with user_context("stale354"):
        second = run(router.migrate())
    assert second == [9902]
    assert _user_ledger(router.user_db_path("stale354")) == [9901, 9902]

    # 跨实例（模拟进程重启）：实例缓存为空，用户文件台账已最新 → 幂等跳过。
    restarted = RoutingDatabase(control_path, tmp_path / "users")
    with user_context("stale354"):
        third = run(restarted.migrate())
    assert third == []
    assert _user_ledger(router.user_db_path("stale354")) == [9901, 9902]
