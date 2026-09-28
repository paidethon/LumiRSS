"""FIX-356 — 删除共享资源的级联范围跨到私人收藏（约束按资源所有权设计）。

判定：BASELINE_OK（所有权边界按物理隔离设计 + ON DELETE 逐条枚举
+ A/B 行为级验证）。

1. 物理边界（0067 邀请制多账户的隔离缝隙）：每个账户的业务数据在
   自己的 SQLite 文件（<data_dir>/users/<uid>/lumi.sqlite）里，
   RoutingDatabase 按 ContextVar 解析当前用户库。A 的 DELETE 语句
   物理上不可能触到 B 的库文件——「删共享资源级联进他人私人收藏」
   跨账户维度按构造不可能。RSS 域的 read/star 状态根本不在 Lumi
   库里（FreshRSS 是 RSS 域唯一事实源，Lumi 不影子拷贝）。
2. 库内 ON DELETE 逐条枚举（migrations/ 全量，外键全部显式）：
   - library_items 为根：library_bookmarks / library_clips /
     library_assets / library_inbox / obsidian_notes / search_library
     均 ON DELETE CASCADE——删除的是「同一个用户对同一资源的副本」，
     级联范围= 该用户自己的派生行（所有权边界正确）；
   - workspaces 为根：workspace_items / workspace_goals / workspace_
     sections / workspace_snapshots / collect_rules / resume 等
     REFERENCES workspaces ON DELETE CASCADE；workspace_items.item_ref
     是逻辑引用（非 FK，0008 注释「Content is never copied」）——
     删 workspace 永不级联进 library_items 本体；
   - agent 族 REFERENCES agent_threads、mail REFERENCES mail_bridge_
     lists、tags REFERENCES tags——各自只级联自己的从属行。

测试即证据：A/B 两用户各存同 uuid 的「同一篇内容」副本（各自的
私人书签笔记 + clip）；A 删除自己的副本 → A 的级联按所有权正确
发生（书签/clip 消失、workspace 存活）；B 的全部私人行原样存活。
两条用户库 physical 隔离也在断言中固定。无真实秘密。
"""

import asyncio

from lumirss.user_scope import RoutingDatabase, user_context

SHARED_UUID = "shared-story-0001"


def run(coroutine):
    return asyncio.run(coroutine)


def _seed_user_copy(db, *, note: str, workspace_id: str):
    """同一 uuid 的用户私有副本：identity 行 + 书签（私人笔记）+
    clip + 一个引用它的 workspace。"""
    run(
        db.execute(
            "INSERT INTO library_items (uuid, kind, created_at)"
            " VALUES (?, 'bookmark', '2026-01-01T00:00:00Z')",
            (SHARED_UUID,),
        )
    )
    run(
        db.execute(
            "INSERT INTO library_bookmarks (item_uuid, item_type, url, title,"
            " note, created_at) VALUES (?, 'url', ?, '共享的内容', ?,"
            " '2026-01-01T00:00:00Z')",
            (SHARED_UUID, f"https://example.com/{SHARED_UUID}", note),
        )
    )
    run(
        db.execute(
            "INSERT INTO library_clips (item_uuid, url, title, content_html,"
            " content_text, fetched_at, created_at) VALUES (?, ?, '共享的内容',"
            " '<p>正文</p>', '正文', '2026-01-01T00:00:00Z',"
            " '2026-01-01T00:00:00Z')",
            (SHARED_UUID, f"https://example.com/{SHARED_UUID}"),
        )
    )
    run(
        db.execute(
            "INSERT INTO workspaces (id, name, position, created_at) VALUES (?,"
            " ?, 1, '2026-01-01T00:00:00Z')",
            (workspace_id, f"工作区-{workspace_id}"),
        )
    )
    run(
        db.execute(
            "INSERT INTO workspace_items (workspace_id, item_ref, position,"
            " added_at) VALUES (?, ?, 0, '2026-01-01T00:00:00Z')",
            (workspace_id, f"library:{SHARED_UUID}"),
        )
    )


def _bookmark_note(db) -> str:
    row = run(
        db.fetch_one(
            "SELECT note FROM library_bookmarks WHERE item_uuid = ?",
            (SHARED_UUID,),
        )
    )
    return None if row is None else str(row["note"])


def test_a_deleting_shared_copy_leaves_b_private_rows_intact(tmp_path):
    db = RoutingDatabase(tmp_path / "control.sqlite", tmp_path / "users")

    with user_context("usera"):
        run(db.migrate())
        _seed_user_copy(db, note="A 的私人批注", workspace_id="ws-a")
        # 外键在 A 的用户库连接上显式开启（FIX-351 同口径的现场复核）。
        connection = db._connect()  # noqa: SLF001 — 所有权边界现场取证
        try:
            assert int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        finally:
            connection.close()

    with user_context("userb"):
        run(db.migrate())
        _seed_user_copy(db, note="B 的私人批注", workspace_id="ws-b")

    # —— A 删除「自己那份」共享资源 ——
    with user_context("usera"):
        run(db.execute("DELETE FROM library_items WHERE uuid = ?", (SHARED_UUID,)))
        # A 的级联按所有权正确发生：identity 行连带自己的书签与 clip。
        assert run(db.fetch_one("SELECT COUNT(*) AS n FROM library_items"))["n"] == 0
        assert _bookmark_note(db) is None
        assert run(db.fetch_one("SELECT COUNT(*) AS n FROM library_clips"))["n"] == 0
        # 删内容副本绝不连带 workspace（item_ref 是逻辑引用，非 FK）。
        assert (
            run(db.fetch_one("SELECT COUNT(*) AS n FROM workspaces"))["n"] >= 1
        )

    # —— B 的私人行原样存活（物理隔离：A 的 DELETE 只落在 A 的文件）——
    with user_context("userb"):
        assert _bookmark_note(db) == "B 的私人批注"
        assert (
            run(db.fetch_one("SELECT COUNT(*) AS n FROM library_items"))["n"] == 1
        )
        assert (
            run(db.fetch_one("SELECT COUNT(*) AS n FROM library_clips"))["n"] == 1
        )
        assert (
            run(db.fetch_one("SELECT COUNT(*) AS n FROM workspaces"))["n"] >= 1
        )

    # 物理证据：两个用户各自独立的库文件。
    assert (tmp_path / "users" / "usera" / "lumi.sqlite").exists()
    assert (tmp_path / "users" / "userb" / "lumi.sqlite").exists()


def test_a_deleting_workspace_spares_b_and_keeps_library_content(tmp_path):
    """删共享工作区：级联止于工作区从属行；内容本体与 B 均不受牵连。"""
    db = RoutingDatabase(tmp_path / "control.sqlite", tmp_path / "users")

    with user_context("usera"):
        run(db.migrate())
        _seed_user_copy(db, note="A 的私人批注", workspace_id="ws-a2")
    with user_context("userb"):
        run(db.migrate())
        _seed_user_copy(db, note="B 的私人批注", workspace_id="ws-b2")

    with user_context("usera"):
        run(db.execute("DELETE FROM workspaces WHERE id = 'ws-a2'"))
        # 工作区从属行级联消失（ws 行本身）……
        assert (
            run(
                db.fetch_one("SELECT COUNT(*) AS n FROM workspaces WHERE id = 'ws-a2'")
            )["n"]
            == 0
        )
        # ……但内容本体（书签/笔记/clip）绝不级联。
        assert _bookmark_note(db) == "A 的私人批注"
        assert (
            run(db.fetch_one("SELECT COUNT(*) AS n FROM library_clips"))["n"] == 1
        )

    with user_context("userb"):
        assert _bookmark_note(db) == "B 的私人批注"
        # B 的工作区与内容副本完整。
        assert (
            run(
                db.fetch_one("SELECT COUNT(*) AS n FROM workspaces WHERE id = 'ws-b2'")
            )["n"]
            == 1
        )
        assert (
            run(
                db.fetch_one(
                    "SELECT COUNT(*) AS n FROM workspace_items WHERE workspace_id = 'ws-b2'"
                )
            )["n"]
            == 1
        )
