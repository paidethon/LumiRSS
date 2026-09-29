"""NEW-340 空间归档流程 —— 归档前列出未完成任务并由管理者处理；归档
后只读（一切写动作 409 space_archived，读取保留）；恢复时管理者必须
逐成员重新确认权限（未列入 keep 清单的成员被撤销空间权限——绝不触碰
其个人账户）。

流程：

1. GET preview：列出未完成任务（待审投稿 / 进行中会议 / 未解决讨论 /
   未闭合分歧）——零写入；
2. POST archive：存在未完成任务且未显式 force → 409（任务清单随响应
   返回，由管理者处理）；force=true 表示管理者确认跳过（快照入档）；
3. POST restore：管理者提交 keepMemberIds（要保留的成员行 id 清单）；
   未列入者撤销（revoked_at 落库）；归档解除；动作与快照入
   space_archive_log。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.space_core import SpaceStore
from lumirss.storage import Database
from lumirss.util import utc_now


class ArchiveBlocked(Exception):
    """存在未完成任务且未显式 force——409 archive_blocked（附任务清单）。"""

    def __init__(self, tasks: list[dict[str, Any]]) -> None:
        super().__init__("存在未完成任务，需先处理或显式确认跳过。")
        self.tasks = tasks


class RestoreInvalid(ValueError):
    """恢复载荷非法（keepMemberIds 缺失/含未知成员）——422。"""


class SpaceArchiveStore:
    def __init__(self, control_db: Database, spaces: SpaceStore) -> None:
        self._db = control_db
        self._spaces = spaces

    # -- 任务盘点（零写入） ------------------------------------------------------

    async def open_tasks(self, space_id: str) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        pending = await self._db.fetch_all(
            "SELECT id, title, submitted_by_username FROM space_contributions "
            "WHERE space_id = ? AND status = 'pending' ORDER BY created_at ASC LIMIT 200",
            (space_id,),
        )
        for row in pending:
            tasks.append(
                {
                    "kind": "contribution_pending",
                    "id": str(row["id"]),
                    "title": str(row["title"]),
                    "actor": str(row["submitted_by_username"]),
                }
            )
        meetings = await self._db.fetch_all(
            "SELECT id, title FROM space_meetings WHERE space_id = ? AND status = 'open' ORDER BY created_at ASC LIMIT 200",
            (space_id,),
        )
        for row in meetings:
            tasks.append(
                {"kind": "meeting_open", "id": str(row["id"]), "title": str(row["title"])}
            )
        discussions = await self._db.fetch_all(
            "SELECT id, title FROM space_discussions WHERE space_id = ? AND status = 'open' ORDER BY created_at ASC LIMIT 200",
            (space_id,),
        )
        for row in discussions:
            tasks.append(
                {"kind": "discussion_open", "id": str(row["id"]), "title": str(row["title"])}
            )
        disagreements = await self._db.fetch_all(
            "SELECT id, title FROM space_disagreements WHERE space_id = ? AND status = 'open' ORDER BY created_at ASC LIMIT 200",
            (space_id,),
        )
        for row in disagreements:
            tasks.append(
                {"kind": "disagreement_open", "id": str(row["id"]), "title": str(row["title"])}
            )
        return tasks

    async def preview(self, space_id: str, *, actor_user_id: str) -> dict[str, Any]:
        await self._spaces.require_manager(space_id, actor_user_id, write=False)
        tasks = await self.open_tasks(space_id)
        return {
            "spaceId": space_id,
            "openTasks": tasks,
            "openTaskCount": len(tasks),
            "note": "归档后空间只读；先处理未完成任务，或以 force 显式确认跳过。",
        }

    # -- 归档 / 恢复 ------------------------------------------------------------

    async def _log(
        self,
        space_id: str,
        *,
        action: str,
        actor_user_id: str,
        tasks: list[dict[str, Any]],
        kept_members: list[str],
    ) -> None:
        await self._db.execute(
            "INSERT INTO space_archive_log (id, space_id, action, actor_user_id, tasks_json, kept_members_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(_uuid.uuid4()),
                space_id,
                action,
                actor_user_id,
                json.dumps(tasks, ensure_ascii=False),
                json.dumps(kept_members, ensure_ascii=False),
                utc_now(),
            ),
        )

    async def archive(
        self, space_id: str, *, actor_user_id: str, force: Any
    ) -> dict[str, Any]:
        await self._spaces.require_manager(space_id, actor_user_id, write=False)
        space = await self._spaces.row(space_id)
        if space["archived_at"] is not None:
            return await self._result(space_id, "archived")
        if not isinstance(force, bool):
            raise RestoreInvalid("force 必须是布尔值。")
        tasks = await self.open_tasks(space_id)
        if tasks and not force:
            raise ArchiveBlocked(tasks)
        await self._db.execute(
            "UPDATE space_spaces SET archived_at = ?, updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), space_id),
        )
        await self._log(
            space_id, action="archived", actor_user_id=actor_user_id, tasks=tasks, kept_members=[]
        )
        return await self._result(space_id, "archived", tasks=tasks, forced=bool(tasks and force))

    async def restore(
        self, space_id: str, *, actor_user_id: str, keep_member_ids: Any
    ) -> dict[str, Any]:
        """恢复只读空间：管理者逐成员重新确认权限。keepMemberIds 必须
        是显式清单（可以是空数组 = 只保留管理者）；未列入的非管理者
        成员被撤销空间权限（行保留、账户不动）。"""
        await self._spaces.require_manager(space_id, actor_user_id, write=False)
        space = await self._spaces.row(space_id)
        if space["archived_at"] is None:
            raise RestoreInvalid("空间未处于归档状态。")
        if not isinstance(keep_member_ids, list) or any(
            not isinstance(item, str) for item in keep_member_ids
        ):
            raise RestoreInvalid("keepMemberIds 必须是成员行 id 的字符串数组。")
        known = await self._spaces.list_members(space_id)
        known_ids = {
            str(member["id"])
            for member in known
            if member["role"] != "manager" and member["revokedAt"] is None
        }
        unknown = [item for item in keep_member_ids if item not in known_ids]
        if unknown:
            raise RestoreInvalid(f"keepMemberIds 含未知成员行：{unknown}")
        now = utc_now()
        kept: list[str] = []
        for member in known:
            if member["role"] == "manager" or member["revokedAt"] is not None:
                continue
            if str(member["id"]) in set(keep_member_ids):
                kept.append(str(member["userId"]))
            else:
                await self._db.execute(
                    "UPDATE space_members SET revoked_at = ? WHERE id = ?",
                    (now, str(member["id"])),
                )
        await self._db.execute(
            "UPDATE space_spaces SET archived_at = NULL, updated_at = ? WHERE id = ?",
            (now, space_id),
        )
        await self._log(
            space_id,
            action="restored",
            actor_user_id=actor_user_id,
            tasks=[],
            kept_members=kept,
        )
        return await self._result(space_id, "restored", kept=kept)

    async def history(self, space_id: str, *, actor_user_id: str) -> list[dict[str, Any]]:
        await self._spaces.require_member(space_id, actor_user_id)
        rows = await self._db.fetch_all(
            "SELECT * FROM space_archive_log WHERE space_id = ? ORDER BY created_at DESC, rowid DESC",
            (space_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "spaceId": str(row["space_id"]),
                "action": str(row["action"]),
                "actorUserId": str(row["actor_user_id"]),
                "tasks": json.loads(str(row["tasks_json"] or "[]")),
                "keptMembers": json.loads(str(row["kept_members_json"] or "[]")),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def _result(
        self,
        space_id: str,
        action: str,
        *,
        tasks: list[dict[str, Any]] | None = None,
        forced: bool = False,
        kept: list[str] | None = None,
    ) -> dict[str, Any]:
        space = await self._spaces.row(space_id)
        return {
            "spaceId": space_id,
            "action": action,
            "archivedAt": space["archived_at"],
            "tasks": tasks or [],
            "forced": forced,
            "keptMembers": kept or [],
        }
