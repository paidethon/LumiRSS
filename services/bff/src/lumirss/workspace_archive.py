"""F084 工作区归档 —— archive / restore（workspaces.archived_at）。

- 归档：默认导航/侧栏/规则目标选择隐藏（list_workspaces 默认过滤）；
  深链接 get_workspace 仍可打开（archived=True 如实返回）；
- 保留工作区（read-later）archive → ProtectedWorkspace（409）；
- 归档工作区的 research-pack / 看板 / 目标写入入口由调用方诚实禁用
  （本模块提供 is_archived 判定）；
- 恢复：archived_at 清空，顺序设置（position）原样保留。

本文件直接写站点 2 处（archive / restore 各一 UPDATE）。
"""

from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now
from lumirss.workspaces import RESERVED_WORKSPACE_ID


class ProtectedWorkspace(Exception):
    """保留工作区不允许归档，映射 409 protected_workspace。"""


class ArchivedWorkspace(Exception):
    """归档工作区的写入口被诚实禁用，映射 409 archived_workspace。"""


class WorkspaceArchiveStore:
    def __init__(self, db: Database, workspace_store: Any) -> None:
        self._db = db
        self._workspaces = workspace_store

    async def is_archived(self, workspace_id: str) -> bool:
        summary = await self._workspaces.get_workspace(workspace_id)
        return bool(summary and summary.archived)

    async def archive(self, workspace_id: str) -> dict[str, Any]:
        if workspace_id == RESERVED_WORKSPACE_ID:
            raise ProtectedWorkspace(RESERVED_WORKSPACE_ID)
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise KeyError(workspace_id)
        if summary.archived:
            return {"archived": True, "archivedAt": summary.archived_at}
        now = utc_now()

        def _tx(conn: Any) -> int:
            cursor = conn.execute(
                "UPDATE workspaces SET archived_at = ? WHERE id = ? AND archived_at IS NULL",
                (now, workspace_id),
            )
            return cursor.rowcount

        updated = await transaction(self._db, _tx)
        if not updated:  # pragma: no cover — 并发归档收敛
            return {"archived": True, "archivedAt": summary.archived_at}
        return {"archived": True, "archivedAt": now}

    async def restore(self, workspace_id: str) -> dict[str, Any]:
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise KeyError(workspace_id)
        if not summary.archived:
            return {"archived": False, "archivedAt": None}

        def _tx(conn: Any) -> int:
            cursor = conn.execute(
                "UPDATE workspaces SET archived_at = NULL WHERE id = ?",
                (workspace_id,),
            )
            return cursor.rowcount

        await transaction(self._db, _tx)
        return {"archived": False, "archivedAt": None}
