"""FIX-351 — 外键约束必须在每一条连接路径上开启。

回归探针：library_inbox.source_uuid REFERENCES inbox_sources(uuid)
（0021_inbox.sql）。探针先落一个合法的 library_items 父行，使插入的
唯一缺失父行是 inbox_sources——这样 IntegrityError 只能归因于
source_uuid 这条外键。外键开启时该插入必须抛 IntegrityError；若任一
连接路径漏掉 PRAGMA foreign_keys=ON，同样的插入会静默成功 —— 这正是
本修复要防的孤儿关联。

覆盖三条真实连接路径：
- Database._connect（控制库 + 迁移连接都由它派生）；
- RoutingDatabase._connect（每个用户库）；
- 迁移事务内的连接（apply_migrations 经 database._connect）——用
  注入的临时迁移文件做行为级证明：第二条语句插入孤儿子行必须让整个
  迁移回滚（连同第一条 DDL）。

经核对的其余裸 sqlite3.connect（不涉及应用写路径，无需统一）：
backup.py/_sqlite_backup 与 restore.py 的在线 backup API（页级复制，
不执行 SQL）与 integrity_check 只读探测；owner_migration.py 两处只读
探测 + 只 SELECT 的 token 索引；backup_scope.py 在离线快照副本上显式
foreign_keys=OFF（按组件整表清除的设计决策）；rag.py vec 连接只写
rag_meta/lumi_settings/rag_jobs/rag_chunks/rag_vec —— 全库带
REFERENCES 的表只有 workspaces 族/agent 族/library 族/obsidian 族/
inbox/mail/tags/ai_conversations 族（见各迁移），上述表无任何
REFERENCES，vec 连接写不进外键关系。
"""

import asyncio
import sqlite3

import pytest

from lumirss.migrations import DatabaseError, list_migrations, schema_version
from lumirss.storage import Database
from lumirss.user_scope import RoutingDatabase, user_context

# 先落合法 library_items 父行（api_item 是 0021 注释钦定的 kind），
# 使孤儿子行的唯一缺失父行是 inbox_sources。
_PLANT_VALID_ITEM_PARENT = (
    "INSERT INTO library_items (uuid, kind, created_at)"
    " VALUES ('item-with-parent', 'api_item', '2026-01-01T00:00:00Z')"
)

_ORPHAN_INSERT = (
    "INSERT INTO library_inbox (item_uuid, source_uuid, guid, title, created_at)"
    " VALUES ('item-with-parent', 'no-such-source', 'g1', '孤儿行',"
    " '2026-01-01T00:00:00Z')"
)


def run(coroutine):
    return asyncio.run(coroutine)


def _pragma_foreign_keys(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA foreign_keys").fetchone()
    return int(row[0])


def test_database_connect_enforces_foreign_keys(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())

    connection = db._connect()  # noqa: SLF001 — the seam under test
    try:
        assert _pragma_foreign_keys(connection) == 1
    finally:
        connection.close()

    # 行为探针：item 父行合法、source 父行缺失 → 外键拒绝（而非静默落库）。
    run(db.execute(_PLANT_VALID_ITEM_PARENT))
    with pytest.raises(sqlite3.IntegrityError):
        run(db.execute(_ORPHAN_INSERT))
    assert run(db.fetch_one("SELECT COUNT(*) AS n FROM library_inbox"))["n"] == 0


def test_routing_database_connect_enforces_foreign_keys(tmp_path):
    db = RoutingDatabase(tmp_path / "control.sqlite", tmp_path / "users")
    with user_context("fix351"):
        run(db.migrate())

        connection = db._connect()  # noqa: SLF001 — the seam under test
        try:
            assert _pragma_foreign_keys(connection) == 1
        finally:
            connection.close()

        run(db.execute(_PLANT_VALID_ITEM_PARENT))
        with pytest.raises(sqlite3.IntegrityError):
            run(db.execute(_ORPHAN_INSERT))
        assert run(db.fetch_one("SELECT COUNT(*) AS n FROM library_inbox"))["n"] == 0


def test_migration_connection_enforces_foreign_keys(tmp_path, monkeypatch):
    """迁移事务内的连接同样开着外键：孤儿子行插入让整条迁移回滚
    （连第一条 DDL 一起）——这同时是 FIX-352 提交边界的行为级证明。"""
    import lumirss.migrations as migrations

    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    before = schema_version(db)
    assert before == list_migrations()[-1][0]

    migrations_dir = tmp_path / "probe-migrations"
    migrations_dir.mkdir()
    (migrations_dir / "9901_baseline.sql").write_text(
        "CREATE TABLE fk351_baseline (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    # 第一条语句成功建表；第二条语句插入 source 父行缺失的孤儿（item
    # 父行合法）→ 外键拒绝，必须连第一条建表一起回滚。
    (migrations_dir / "9902_fk_probe.sql").write_text(
        "CREATE TABLE fk351_probe (id TEXT PRIMARY KEY);\n"
        + _PLANT_VALID_ITEM_PARENT
        + "\n"
        + _ORPHAN_INSERT
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", migrations_dir)

    reopened = Database(tmp_path / "lumi.sqlite")
    with pytest.raises(DatabaseError, match="9902_fk_probe"):
        run(reopened.migrate())

    # 基线迁移正常落账；9902 版本未记录 + 前两条语句的效果已回滚
    # （外键在迁移连接上是开启的，且回滚覆盖整个迁移文件）。
    assert schema_version(db) == 9901
    connection = sqlite3.connect(str(db.path))
    try:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        orphans = connection.execute("SELECT COUNT(*) FROM library_inbox").fetchone()
        planted = connection.execute(
            "SELECT COUNT(*) FROM library_items WHERE uuid = 'item-with-parent'"
        ).fetchone()
    finally:
        connection.close()
    assert "fk351_probe" not in names
    assert "fk351_baseline" in names
    assert int(orphans[0]) == 0  # 9902 的孤儿插入已回滚
    assert int(planted[0]) == 0  # 9902 的父行插入（同迁移）也已回滚


def test_migration_connection_accepts_valid_child(tmp_path, monkeypatch):
    """对照组：两个父行先落库时，同一迁移连接上的子行插入正常提交——
    证明上面的失败来自外键约束本身，而不是迁移连接的写路径坏了。"""
    import lumirss.migrations as migrations

    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())

    migrations_dir = tmp_path / "probe-migrations-ok"
    migrations_dir.mkdir()
    (migrations_dir / "9901_inbox_source.sql").write_text(
        "INSERT INTO library_items (uuid, kind, created_at)"
        " VALUES ('item-1', 'api_item', '2026-01-01T00:00:00Z');\n"
        "INSERT INTO inbox_sources (uuid, name, secret, created_at)"
        " VALUES ('src-1', '探针源', 's', '2026-01-01T00:00:00Z');\n"
        "INSERT INTO library_inbox (item_uuid, source_uuid, guid, title, created_at)"
        " VALUES ('item-1', 'src-1', 'g1', '合法子行', '2026-01-01T00:00:00Z');\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", migrations_dir)

    reopened = Database(tmp_path / "lumi.sqlite")
    applied = run(reopened.migrate())
    assert applied == [9901]
    row = run(
        reopened.fetch_one(
            "SELECT COUNT(*) AS n FROM library_inbox WHERE source_uuid = 'src-1'"
        )
    )
    assert row["n"] == 1
