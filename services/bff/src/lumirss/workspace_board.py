"""F085 工作区看板 —— 三列（todo/reading/done）状态持久化。

- 状态是 Lumi 自有元数据：绝不触碰 FreshRSS 的 read/star（负向断言
  依赖这一点）；
- 同一条目在不同工作区的状态独立（PK 为 (workspace_id, item_ref)）；
- GET 返回三列各前 50 条 + 真实总数（分页提示由 UI 呈现）；
- PUT 幂等（重复写同状态无副作用）；非法状态 → BoardInvalid（422）；
- 条目必须已是工作区成员（否则 not_found）。

本文件直接写站点 2 处（status INSERT / UPDATE）。
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

BOARD_STATUSES = ("todo", "reading", "done")
_COLUMN_PAGE = 50


class BoardInvalid(ValueError):
    """看板载荷非法（状态枚举/条目引用），映射 422。"""


class BoardItemNotFound(Exception):
    """条目不是该工作区成员，映射 404。"""


class WorkspaceBoardStore:
    def __init__(self, db: Database, workspace_store: Any) -> None:
        self._db = db
        self._workspaces = workspace_store

    async def get_board(self, workspace_id: str) -> dict[str, Any]:
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise KeyError(workspace_id)
        columns: list[dict[str, Any]] = []
        for status in BOARD_STATUSES:
            rows = await self._db.fetch_all(
                "SELECT item_ref, status, updated_at FROM workspace_item_status WHERE workspace_id = ? AND status = ? ORDER BY updated_at DESC, item_ref ASC LIMIT ?",
                (workspace_id, status, _COLUMN_PAGE),
            )
            count_row = await self._db.fetch_one(
                "SELECT COUNT(*) AS n FROM workspace_item_status WHERE workspace_id = ? AND status = ?",
                (workspace_id, status),
            )
            columns.append(
                {
                    "status": status,
                    "items": [
                        {
                            "itemRef": str(r["item_ref"]),
                            "status": str(r["status"]),
                            "updatedAt": str(r["updated_at"]),
                        }
                        for r in rows
                    ],
                    "total": int(count_row["n"]) if count_row is not None else 0,
                }
            )
        return {"workspaceId": workspace_id, "columns": columns}

    async def set_status(
        self, workspace_id: str, item_ref: str, status: str
    ) -> dict[str, Any]:
        if status not in BOARD_STATUSES:
            raise BoardInvalid("status 必须是 todo|reading|done。")
        try:
            clean_ref = parse_item_ref(item_ref).format()
        except ValueError as exc:
            raise BoardInvalid(str(exc)) from exc
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise KeyError(workspace_id)
        member = await self._db.fetch_one(
            "SELECT 1 FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, clean_ref),
        )
        if member is None:
            raise BoardItemNotFound(clean_ref)
        # P15：状态真实变化才 bump workspaces.revision（重复写同状态仍是
        # 幂等重放——不制造跨设备 409 噪声）。写法保持既有 INSERT/UPDATE
        # 两段式（无 UPSERT 语法）。
        current = await self._db.fetch_one(
            "SELECT status FROM workspace_item_status WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, clean_ref),
        )
        status_changed = current is None or str(current["status"]) != status
        now = utc_now()

        def _insert(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO workspace_item_status (workspace_id, item_ref, status, updated_at) VALUES (?, ?, ?, ?)",
                (workspace_id, clean_ref, status, now),
            )
            if status_changed:
                conn.execute(
                    "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                    (workspace_id,),
                )
            return cursor.rowcount

        def _update(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE workspace_item_status SET status = ?, updated_at = ? WHERE workspace_id = ? AND item_ref = ?",
                (status, now, workspace_id, clean_ref),
            )
            if status_changed:
                conn.execute(
                    "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                    (workspace_id,),
                )
            return cursor.rowcount

        try:
            await transaction(self._db, _insert)
        except sqlite3.IntegrityError:
            await transaction(self._db, _update)
        return {"itemRef": clean_ref, "status": status, "updatedAt": now}

    async def done_count(self, workspace_id: str) -> int:
        """F086 进度口径：看板 done 去重条目数，且只统计仍在工作区内的
        成员（条目被移出工作区后进度诚实下降；PK 保证天然去重）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM workspace_item_status s WHERE s.workspace_id = ? AND s.status = 'done' AND EXISTS (SELECT 1 FROM workspace_items w WHERE w.workspace_id = s.workspace_id AND w.item_ref = s.item_ref)",
            (workspace_id,),
        )
        return int(row["n"]) if row is not None else 0
