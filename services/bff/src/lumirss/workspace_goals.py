"""F086 工作区阅读目标 —— 每工作区一个目标（数量 + 可选截止）。

进度不在本模块计算：由 WorkspaceBoardStore.done_count（看板 done
去重条目数，真实事件驱动）提供。目标删除 → 卡片隐藏。

本文件直接写站点 3 处（goal INSERT / UPDATE / DELETE）。
"""

import sqlite3
from datetime import date, datetime
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now


class GoalInvalid(ValueError):
    """目标载荷非法（数量/日期），映射 422。"""


class WorkspaceGoalStore:
    def __init__(self, db: Database, workspace_store: Any) -> None:
        self._db = db
        self._workspaces = workspace_store

    async def get_goal(self, workspace_id: str) -> dict[str, Any] | None:
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise KeyError(workspace_id)
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT workspace_id, target_count, deadline, created_at FROM workspace_goals WHERE workspace_id = ?",
            (workspace_id,),
        )
        if row is None:
            return None
        return {
            "workspaceId": str(row["workspace_id"]),
            "targetCount": int(row["target_count"]),
            "deadline": row["deadline"],
            "createdAt": str(row["created_at"]),
        }

    async def put_goal(
        self, workspace_id: str, target_count: int, deadline: str | None
    ) -> dict[str, Any]:
        if not isinstance(target_count, int) or target_count < 1:
            raise GoalInvalid("target_count 必须是 ≥1 的整数。")
        clean_deadline: str | None = None
        if deadline is not None:
            try:
                parsed = date.fromisoformat(str(deadline))
            except ValueError as exc:
                raise GoalInvalid("deadline 必须是 YYYY-MM-DD。") from exc
            clean_deadline = parsed.isoformat()
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise KeyError(workspace_id)
        await self._db.migrate()
        existing = await self.get_goal(workspace_id)
        created = existing["createdAt"] if existing else utc_now()
        row = await self._db.fetch_one(
            "SELECT workspace_id FROM workspace_goals WHERE workspace_id = ?",
            (workspace_id,),
        )

        def _insert(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO workspace_goals (workspace_id, target_count, deadline, created_at) VALUES (?, ?, ?, ?)",
                (workspace_id, target_count, clean_deadline, created),
            )
            return cursor.rowcount

        def _update(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE workspace_goals SET target_count = ?, deadline = ? WHERE workspace_id = ?",
                (target_count, clean_deadline, workspace_id),
            )
            return cursor.rowcount

        if row is None:
            await transaction(self._db, _insert)
        else:
            await transaction(self._db, _update)
        return {
            "workspaceId": workspace_id,
            "targetCount": target_count,
            "deadline": clean_deadline,
            "createdAt": created,
        }

    async def delete_goal(self, workspace_id: str) -> bool:
        await self._db.migrate()

        def _tx(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "DELETE FROM workspace_goals WHERE workspace_id = ?",
                (workspace_id,),
            )
            return cursor.rowcount

        return bool(await transaction(self._db, _tx))


def goal_expired(deadline: str | None, *, today: date | None = None) -> bool:
    """截止过期显示「已到期」（None = 无截止，永不过期）。"""
    if not deadline:
        return False
    reference = today or date.fromisoformat(
        datetime.fromisoformat(utc_now()).date().isoformat()
    )
    try:
        return date.fromisoformat(deadline) < reference
    except ValueError:
        return False
