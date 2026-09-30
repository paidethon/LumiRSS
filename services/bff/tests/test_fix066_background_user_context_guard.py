"""FIX-066 守卫：脱离请求的后台任务不丢用户上下文、不落 owner 库。

机制基线（user_scope.py）：
- ``user_context(uid)`` 是 ContextVar 绑定；``asyncio.create_task`` 在
  创建时复制当前上下文——所以请求内 spawn 的 fire-and-forget 任务
  （agent turn、backup _run_full、TTS 合成、gpt_digest rotated_at 戳）
  在请求结束后仍解析到该用户的 per-user 库；
- 没有身份的后台代码触碰 RoutingDatabase 是硬错误（NoUserContextError，
  O145）——绝不静默落到默认/owner 库。

钉两条（A/B 库文件级断言）：
1. 请求式上下文退出后仍运行的 task 写入 → 落在 A 的库文件；
2. 无上下文 task 触碰路由库 → NoUserContextError（fail-closed）。
"""

import asyncio
import sqlite3

import pytest

from lumirss.storage import Database
from lumirss.user_scope import (
    NoUserContextError,
    RoutingDatabase,
    user_context,
)


def _uid_rows(db_file, table: str) -> int:
    connection = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        return int(
            connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()[0]
        )
    finally:
        connection.close()


def test_fix066_detached_task_keeps_user_binding(tmp_path):
    """上下文退出后仍在跑的 task：写入落在原用户的库，owner 库无痕。"""
    users_root = tmp_path / "users"
    db = RoutingDatabase(tmp_path / "control.sqlite", users_root)
    alice_file = users_root / "alice123" / "lumi.sqlite"

    async def scenario():
        with user_context("bootstrap"):
            await db.migrate()  # 建表落在 bootstrap 库，与断言无关
        detached: asyncio.Task = None  # type: ignore[assignment]

        with user_context("alice123"):
            async def _late_write():
                await asyncio.sleep(0.01)  # 让外层 user_context 先退出
                await db.migrate()
                await db.execute(
                    "INSERT INTO lumi_settings (key, value, updated_at)"
                    " VALUES ('fix066', 'detached', 1)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                )

            detached = asyncio.create_task(_late_write())
        # 此处请求式上下文已退出（模拟响应已返回）。
        assert detached is not None
        await detached

    asyncio.run(scenario())

    assert alice_file.is_file(), "detached 任务应落在 alice 的 per-user 库"
    assert _uid_rows(alice_file, "lumi_settings") >= 1
    assert (users_root / "bootstrap" / "lumi.sqlite").is_file()
    for stranger in ("bootstrap", "owner000"):
        stranger_file = users_root / stranger / "lumi.sqlite"
        if stranger_file.is_file():
            rows = sqlite3.connect(stranger_file).execute(
                "SELECT COUNT(*) FROM lumi_settings WHERE key = 'fix066'"
            ).fetchone()[0]
            sqlite3.connect(stranger_file).close()
            assert rows == 0, f"{stranger} 库不得出现 alice 的写入"


def test_fix066_no_context_fails_closed_never_owner(tmp_path):
    """无用户上下文触碰路由库 → NoUserContextError；owner 库零写入。"""
    users_root = tmp_path / "users"
    db = RoutingDatabase(tmp_path / "control.sqlite", users_root)
    owner_file = users_root / "owner000" / "lumi.sqlite"

    async def scenario():
        with user_context("bootstrap"):
            await db.migrate()
        with pytest.raises(NoUserContextError):

            async def _background_touch():
                # 真实后台循环外的裸任务：没有 user_context。
                await db.execute(
                    "INSERT INTO lumi_settings (key, value, updated_at)"
                    " VALUES ('fix066leak', 'x', 1)"
                )

            await asyncio.create_task(_background_touch())

    asyncio.run(scenario())
    if owner_file.is_file():
        rows = sqlite3.connect(owner_file).execute(
            "SELECT COUNT(*) FROM lumi_settings WHERE key = 'fix066leak'"
        ).fetchone()[0]
        sqlite3.connect(owner_file).close()
        assert rows == 0


def test_fix066_plain_database_unaffected_by_contextvars(tmp_path):
    """对照：普通 Database（控制库/测试直连）不受 ContextVar 影响——
    路由语义只属于 RoutingDatabase，无回归外溢。"""
    control = Database(tmp_path / "plain.sqlite")

    async def scenario():
        await control.migrate()
        with user_context("someone999"):
            await control.execute(
                "INSERT INTO lumi_settings (key, value, updated_at)"
                " VALUES ('fix066plain', 'y', 1)"
            )

    asyncio.run(scenario())
    assert (tmp_path / "plain.sqlite").is_file()
