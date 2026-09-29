"""NEW-323 笔记增量同步审批 —— 预览清单 → 用户确认 → 更新镜像。

口径（绝不写原库）：

- 预览 = ``ObsidianService.sync_preview()``：与 rescan 完全相同的差异
  计划（walk + parse + 对比投影），但【零写入】——镜像在用户确认前
  绝不更新；新增/修改/删除清单来自真实文件系统，不是上次缓存；
- 确认 = 唯一的应用路径：对 pending 审批执行真实 rescan（写镜像），
  实际报告与预览各自落台账——两者之间 Vault 又变了时如实并存，
  绝不假装「预览即结果」；
- 新预览落库时旧 pending 行置 superseded（陈旧计划不再是可执行项）；
- 源 Vault 保持只读：应用只更新 Lumi 侧镜像（obsidian_notes 投影）。

per-user：审批台账在 per-user 库；镜像/预览是 owner 的 Vault 面
（路由层 owner 门槛），B 既看不到 A 的审批，也不能触发扫描。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.obsidian import ObsidianService
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_LISTED_APPROVALS = 50


class SyncApprovalNotFound(Exception):
    """审批 id 不存在（404）。"""


class SyncApprovalNotPending(Exception):
    """审批已应用或已被新预览取代（409）。"""

    def __init__(self, status: str) -> None:
        super().__init__(f"approval status is {status}")
        self.status = status


class SyncApprovalStore:
    def __init__(self, db: Database, service: ObsidianService) -> None:
        self._db = db
        self._service = service

    async def preview(self) -> dict[str, Any]:
        """零写入差异预览 + pending 审批落库（旧 pending → superseded）。"""
        await self._db.migrate()
        plan = await self._service.sync_preview()
        approval_id = str(_uuid.uuid4())
        now = utc_now()

        def _tx(conn: Any) -> None:
            conn.execute(
                "UPDATE obsidian_sync_approvals SET status = 'superseded'"
                " WHERE status = 'pending'"
            )
            conn.execute(
                "INSERT INTO obsidian_sync_approvals (id, status, planned_json, applied_report_json, created_at)"
                " VALUES (?, 'pending', ?, '', ?)",
                (approval_id, json.dumps(plan, ensure_ascii=False), now),
            )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        return {"id": approval_id, "status": "pending", **plan}

    async def apply(self, approval_id: str) -> dict[str, Any]:
        """用户确认：执行真实同步（唯一写镜像路径），落实际报告。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, status FROM obsidian_sync_approvals WHERE id = ?",
            (str(approval_id).strip(),),
        )
        if row is None:
            raise SyncApprovalNotFound(approval_id)
        status = str(row["status"])
        if status != "pending":
            raise SyncApprovalNotPending(status)
        report = await self._service.rescan()
        applied_at = utc_now()
        await self._db.execute(
            "UPDATE obsidian_sync_approvals SET status = 'applied',"
            " applied_report_json = ?, applied_at = ? WHERE id = ?",
            (json.dumps(report, ensure_ascii=False), applied_at, str(approval_id)),
        )
        return {
            "id": str(approval_id),
            "status": "applied",
            "appliedAt": applied_at,
            "report": report,
            "honestyNote": "同步只更新了 Lumi 侧镜像；源 Vault 保持只读。",
        }

    async def list_approvals(self, limit: int = _MAX_LISTED_APPROVALS) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, status, planned_json, applied_report_json, created_at, applied_at"
            " FROM obsidian_sync_approvals ORDER BY created_at DESC, id DESC LIMIT ?",
            (max(1, min(limit, _MAX_LISTED_APPROVALS)),),
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                planned = json.loads(str(row["planned_json"] or "{}"))
            except json.JSONDecodeError:
                planned = {}
            try:
                applied = json.loads(str(row["applied_report_json"] or ""))
            except json.JSONDecodeError:
                applied = None
            items.append(
                {
                    "id": str(row["id"]),
                    "status": str(row["status"]),
                    "planned": planned if isinstance(planned, dict) else {},
                    "appliedReport": applied if isinstance(applied, dict) else None,
                    "createdAt": str(row["created_at"]),
                    "appliedAt": row["applied_at"],
                }
            )
        return items
