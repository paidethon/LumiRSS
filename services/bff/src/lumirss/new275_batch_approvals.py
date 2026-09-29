"""NEW-275 批量 AI 任务审批单 —— 执行前清单与预算。

- 审批单 = 准备处理的文章清单 + 任务类型（kind）+ 预算（本次最多
  消耗的 AI 调用数）。status: draft → approved → completed/cancelled；
- 执行是显式动作：approve 之后才允许 execute；执行逐项原子预占预算
  名额，预算用尽 → 该项 over_budget 且执行停止（剩余项保持 pending，
  可再次 execute 续跑或先调整预算——绝不静默超额）；
- 全局配额（F064/N191）在同一循环内预占：配额拒绝 → 该项
  quota_exceeded 且执行停止；
- 可取消尚未开始的项（pending → cancelled）；已开始的项不动；
  整单取消在 completed 之后拒绝。

per-user：审批单与明细在 per-user 库，A 的审批单对 B 不可见。
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

BUDGET_KINDS = ("summary",)

_MAX_ITEMS = 20
_MAX_BUDGET = 20

_APPROVAL_COLUMNS = (
    "id, kind, budget_calls, used_calls, status, created_at, approved_at, closed_at"
)
_ITEM_COLUMNS = "id, approval_id, entry_ref, status, error_type, finished_at, ord"


class ApprovalInvalid(ValueError):
    """审批单负载非法（映射 422）。"""


class ApprovalNotFound(Exception):
    """审批单不存在（映射 404）。"""


class ApprovalStateError(Exception):
    """状态机不允许该操作（映射 409），携带机器可读原因。"""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class BatchApprovalStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 创建 / 审批 ------------------------------------------------------

    async def create(
        self, kind: str, entry_refs: Any, budget_calls: Any
    ) -> dict[str, Any]:
        if kind not in BUDGET_KINDS:
            raise ApprovalInvalid(
                f"kind 必须是 {'、'.join(BUDGET_KINDS)} 之一。"
            )
        if not isinstance(entry_refs, list) or not (
            1 <= len(entry_refs) <= _MAX_ITEMS
        ):
            raise ApprovalInvalid(f"entryRefs 必须是 1..{_MAX_ITEMS} 条。")
        clean_refs: list[str] = []
        for ref in entry_refs:
            if not isinstance(ref, str) or not ref.strip():
                raise ApprovalInvalid("entryRefs 必须是非空字符串。")
            if ref in clean_refs:
                raise ApprovalInvalid("entryRefs 不能重复。")
            clean_refs.append(ref.strip())
        if isinstance(budget_calls, bool) or not isinstance(budget_calls, int):
            raise ApprovalInvalid("budgetCalls 必须是整数。")
        if not 1 <= budget_calls <= _MAX_BUDGET:
            raise ApprovalInvalid(
                f"budgetCalls 必须在 1..{_MAX_BUDGET} 之间。"
            )
        await self._db.migrate()
        approval_id = uuid.uuid4().hex[:20]
        now = utc_now()
        await self._db.execute(
            "INSERT INTO ai_batch_approvals (id, kind, budget_calls, used_calls, "
            "status, created_at, approved_at, closed_at) "
            "VALUES (?, ?, ?, 0, 'draft', ?, NULL, NULL)",
            (approval_id, kind, budget_calls, now),
        )
        for ord_index, ref in enumerate(clean_refs):
            await self._db.execute(
                "INSERT INTO ai_batch_approval_items (id, approval_id, entry_ref, "
                "status, error_type, finished_at, ord) "
                "VALUES (?, ?, ?, 'pending', NULL, NULL, ?)",
                (uuid.uuid4().hex[:20], approval_id, ref, ord_index),
            )
        return await self.get_approval(approval_id)

    async def approve(self, approval_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._fetch_approval(approval_id)
        if row is None:
            raise ApprovalNotFound(approval_id)
        if row["status"] != "draft":
            raise ApprovalStateError(
                "already_approved", "审批单只能从草稿审批一次。"
            )
        await self._db.execute(
            "UPDATE ai_batch_approvals SET status = 'approved', approved_at = ? "
            "WHERE id = ?",
            (utc_now(), approval_id),
        )
        return await self.get_approval(approval_id)

    # -- 取消 ---------------------------------------------------------------

    async def cancel(
        self, approval_id: str, item_id: str | None = None
    ) -> dict[str, Any]:
        """取消整单或单个尚未开始的项；已开始的项不动。"""
        approval = await self.get_approval(approval_id)
        if approval["status"] == "completed":
            raise ApprovalStateError(
                "already_completed", "审批单已完成，不能取消。"
            )
        if item_id is not None:
            item = next(
                (i for i in approval["items"] if i["id"] == item_id), None
            )
            if item is None:
                raise ApprovalNotFound(item_id)
            if item["status"] != "pending":
                raise ApprovalStateError(
                    "item_not_pending", "只有尚未开始的项可以取消。"
                )
            await self._db.execute(
                "UPDATE ai_batch_approval_items SET status = 'cancelled', "
                "finished_at = ? WHERE id = ?",
                (utc_now(), item_id),
            )
        else:
            await self._db.execute(
                "UPDATE ai_batch_approval_items SET status = 'cancelled', "
                "finished_at = ? WHERE approval_id = ? AND status = 'pending'",
                (utc_now(), approval_id),
            )
            await self._db.execute(
                "UPDATE ai_batch_approvals SET status = 'cancelled', closed_at = ? "
                "WHERE id = ? AND status != 'completed'",
                (utc_now(), approval_id),
            )
        return await self.get_approval(approval_id)

    # -- 执行 ---------------------------------------------------------------

    async def execute(
        self,
        approval_id: str,
        run_item: Callable[[str, str], Awaitable[tuple[str, str | None]]],
    ) -> dict[str, Any]:
        """按序执行 pending 项；run_item(entry_ref, kind) → (status, error)。

        预算名额在审批单行上原子递增（used_calls < budget_calls 才尝试）：
        名额用尽 → 停止并如实上报 stoppedReason="over_budget"，剩余项
        保持 pending（可调整后再次 execute 续跑）——绝不静默超额。
        执行循环串行（单进程 BFF）；全局配额/费用由 run_item 内的既有
        配额守卫负责，quota_exceeded 同样停止整单。"""
        approval = await self.get_approval(approval_id)
        if approval["status"] == "draft":
            raise ApprovalStateError("not_approved", "审批单未经确认，不能执行。")
        if approval["status"] in ("cancelled", "completed"):
            raise ApprovalStateError(
                "closed", "审批单已关闭（取消/完成），不能执行。"
            )
        budget = int(approval["budgetCalls"])
        used = int(approval["usedCalls"])
        summary = {"done": 0, "failed": 0}
        stopped_reason: str | None = None
        for item in approval["items"]:
            if item["status"] != "pending":
                continue
            if used >= budget:
                stopped_reason = "over_budget"
                break
            status, error_type = await run_item(item["entryRef"], approval["kind"])
            used += 1
            await self._db.execute(
                "UPDATE ai_batch_approvals SET used_calls = used_calls + 1 "
                "WHERE id = ?",
                (approval_id,),
            )
            await self._db.execute(
                "UPDATE ai_batch_approval_items SET status = ?, error_type = ?, "
                "finished_at = ? WHERE id = ?",
                (status, error_type, utc_now(), item["id"]),
            )
            if status == "done":
                summary["done"] += 1
            else:
                summary["failed"] += 1
            if status == "quota_exceeded":
                stopped_reason = "quota_exceeded"
                break
        remaining = await self._count_pending(approval_id)
        if remaining == 0:
            await self._db.execute(
                "UPDATE ai_batch_approvals SET status = 'completed', closed_at = ? "
                "WHERE id = ?",
                (utc_now(), approval_id),
            )
        result = await self.get_approval(approval_id)
        result["execution"] = {
            "usedCalls": used,
            "budgetCalls": budget,
            "remainingPending": remaining,
            "stoppedReason": stopped_reason,
            **summary,
        }
        return result

    # -- 读取 ---------------------------------------------------------------

    async def get_approval(self, approval_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._fetch_approval(approval_id)
        if row is None:
            raise ApprovalNotFound(approval_id)
        item_rows = await self._db.fetch_all(
            f"SELECT {_ITEM_COLUMNS} FROM ai_batch_approval_items "
            "WHERE approval_id = ? ORDER BY ord ASC, rowid ASC",
            (approval_id,),
        )
        return {
            "id": str(row["id"]),
            "kind": str(row["kind"]),
            "budgetCalls": int(row["budget_calls"]),
            "usedCalls": int(row["used_calls"] or 0),
            "status": str(row["status"]),
            "createdAt": str(row["created_at"]),
            "approvedAt": row["approved_at"],
            "closedAt": row["closed_at"],
            "items": [
                {
                    "id": str(item_row["id"]),
                    "entryRef": str(item_row["entry_ref"]),
                    "status": str(item_row["status"]),
                    "errorType": item_row["error_type"],
                    "finishedAt": item_row["finished_at"],
                    "ord": int(item_row["ord"]),
                }
                for item_row in item_rows
            ],
        }

    async def list_approvals(self, limit: int = 20) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT {_APPROVAL_COLUMNS} FROM ai_batch_approvals "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        )
        return [
            {
                "id": str(row["id"]),
                "kind": str(row["kind"]),
                "budgetCalls": int(row["budget_calls"]),
                "usedCalls": int(row["used_calls"] or 0),
                "status": str(row["status"]),
                "createdAt": str(row["created_at"]),
                "approvedAt": row["approved_at"],
                "closedAt": row["closed_at"],
            }
            for row in rows
        ]

    # -- 内部 ---------------------------------------------------------------

    async def _fetch_approval(self, approval_id: str):
        return await self._db.fetch_one(
            f"SELECT {_APPROVAL_COLUMNS} FROM ai_batch_approvals WHERE id = ?",
            (approval_id,),
        )

    async def _count_pending(self, approval_id: str) -> int:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM ai_batch_approval_items "
            "WHERE approval_id = ? AND status = 'pending'",
            (approval_id,),
        )
        return int(row["n"]) if row is not None else 0
