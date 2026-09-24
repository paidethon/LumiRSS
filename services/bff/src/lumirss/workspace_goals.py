"""F086 工作区阅读目标 —— 每工作区一个目标（数量 + 可选截止）。

进度不在本模块计算：由 WorkspaceBoardStore.done_count（看板 done
去重条目数，真实事件驱动）提供。目标删除 → 卡片隐藏。

N111 目标卡扩展：数值目标之外并存自由文本目标陈述（goal_text）与
完成条件清单（conditions，≤20 条、每条 ≤200 字，存 conditions_json）。
条件的勾选状态是设备本机呈现态（Web localStorage），服务端只存文本、
绝不存勾选状态——多设备各勾各的，互不同步。

本文件直接写站点 3 处（goal INSERT / UPDATE / DELETE）。
"""

import json
import sqlite3
from datetime import date, datetime
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_GOAL_TEXT_LENGTH = 2000
_MAX_CONDITIONS = 20
_MAX_CONDITION_LENGTH = 200


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
            "SELECT workspace_id, target_count, deadline, goal_text, conditions_json, created_at FROM workspace_goals WHERE workspace_id = ?",
            (workspace_id,),
        )
        if row is None:
            return None
        return {
            "workspaceId": str(row["workspace_id"]),
            "targetCount": int(row["target_count"]),
            "deadline": row["deadline"],
            "goalText": row["goal_text"],
            "conditions": _decode_conditions(row["conditions_json"]),
            "createdAt": str(row["created_at"]),
        }

    async def put_goal(
        self,
        workspace_id: str,
        target_count: int,
        deadline: str | None,
        goal_text: str | None = None,
        conditions: list[str] | None = None,
        *,
        goal_text_set: bool = False,
        conditions_set: bool = False,
    ) -> dict[str, Any]:
        """写入目标（PUT 全量替换 target_count/deadline）。

        N111：``goal_text`` / ``conditions`` 可选——调用方未携带（None 且
        未置 ``*_set``）= 保留既有值（旧调用方绝不无意清空 N111 数据）；
        显式携带空串 / 空列表 = 清除。"""
        if not isinstance(target_count, int) or target_count < 1:
            raise GoalInvalid("target_count 必须是 ≥1 的整数。")
        clean_deadline: str | None = None
        if deadline is not None:
            try:
                parsed = date.fromisoformat(str(deadline))
            except ValueError as exc:
                raise GoalInvalid("deadline 必须是 YYYY-MM-DD。") from exc
            clean_deadline = parsed.isoformat()
        clean_text = _validate_goal_text(goal_text) if goal_text_set else _UNSET
        clean_conditions = (
            _validate_conditions(conditions) if conditions_set else _UNSET
        )
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise KeyError(workspace_id)
        await self._db.migrate()
        existing = await self.get_goal(workspace_id)
        created = existing["createdAt"] if existing else utc_now()
        if not goal_text_set:
            clean_text = existing["goalText"] if existing else None
        if not conditions_set:
            clean_conditions = existing["conditions"] if existing else []
        row = await self._db.fetch_one(
            "SELECT workspace_id FROM workspace_goals WHERE workspace_id = ?",
            (workspace_id,),
        )

        def _insert(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO workspace_goals (workspace_id, target_count, deadline, goal_text, conditions_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    workspace_id,
                    target_count,
                    clean_deadline,
                    clean_text,
                    json.dumps(clean_conditions, ensure_ascii=False),
                    created,
                ),
            )
            return cursor.rowcount

        def _update(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE workspace_goals SET target_count = ?, deadline = ?, goal_text = ?, conditions_json = ? WHERE workspace_id = ?",
                (
                    target_count,
                    clean_deadline,
                    clean_text,
                    json.dumps(clean_conditions, ensure_ascii=False),
                    workspace_id,
                ),
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
            "goalText": clean_text,
            "conditions": clean_conditions,
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


# N111：「未携带」哨兵（None 是合法值 = 显式清除文本，需区分）。
_UNSET = object()


def _validate_goal_text(goal_text: Any) -> str | None:
    """目标陈述校验：None = 清除；空白串归一为 None；上限 2000 字。"""
    if goal_text is None:
        return None
    if not isinstance(goal_text, str):
        raise GoalInvalid("goal_text 必须是字符串或 null。")
    clean = goal_text.strip()
    if not clean:
        return None
    if len(clean) > _MAX_GOAL_TEXT_LENGTH:
        raise GoalInvalid(
            f"goal_text is too long (max {_MAX_GOAL_TEXT_LENGTH} chars)."
        )
    return clean


def _validate_conditions(conditions: Any) -> list[str]:
    """完成条件校验：None = 清除；≤20 条、每条非空 ≤200 字、去重保序。"""
    if conditions is None:
        return []
    if not isinstance(conditions, list) or not all(
        isinstance(c, str) for c in conditions
    ):
        raise GoalInvalid("conditions 必须是字符串数组或 null。")
    cleaned: list[str] = []
    for condition in conditions:
        text = condition.strip()
        if not text:
            continue
        if len(text) > _MAX_CONDITION_LENGTH:
            raise GoalInvalid(
                f"Each condition is too long (max {_MAX_CONDITION_LENGTH} chars)."
            )
        if text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > _MAX_CONDITIONS:
        raise GoalInvalid(f"Too many conditions (max {_MAX_CONDITIONS}).")
    return cleaned


def _decode_conditions(raw: Any) -> list[str]:
    """conditions_json 容错解析（损坏/异形 → []，绝不 500）。"""
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(c) for c in parsed if isinstance(c, str)]
