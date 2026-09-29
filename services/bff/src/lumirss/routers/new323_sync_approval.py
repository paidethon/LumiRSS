"""NEW-323 笔记增量同步审批路由 — 预览 / 确认应用 / 台账。

- POST /api/v1/obsidian/sync/preview            零写入差异清单（pending 审批）
- POST /api/v1/obsidian/sync/apply              {approvalId} → 确认后更新镜像
- GET  /api/v1/obsidian/sync/approvals          审批台账（预览 vs 实际报告）

镜像（投影）只在用户确认后被更新；源 Vault 保持只读。owner 门槛
（O168）：成员既不能预览/应用，也看不到审批台账。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.deps import _get_obsidian_service
from lumirss.new323_sync_approval import (
    SyncApprovalNotFound,
    SyncApprovalNotPending,
    SyncApprovalStore,
)
from lumirss.routers.obsidian import _require_owner

router = APIRouter()


def _store(request: Request) -> SyncApprovalStore:
    return SyncApprovalStore(
        request.app.state.db, _get_obsidian_service(request)
    )


@router.post("/api/v1/obsidian/sync/preview")
async def preview_sync(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse(await _store(request).preview())


@router.post("/api/v1/obsidian/sync/apply")
async def apply_sync(payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    approval_id = str(payload.get("approvalId") or "").strip()
    if not approval_id:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "type": "invalid_request",
                    "message": "approvalId 不能为空。",
                }
            },
        )
    try:
        return JSONResponse(await _store(request).apply(approval_id))
    except SyncApprovalNotFound:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "approval_not_found", "message": "审批不存在。"}
            },
        )
    except SyncApprovalNotPending as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "approval_not_pending",
                    "message": f"审批当前状态为 {exc.status}，不能重复应用。",
                }
            },
        )


@router.get("/api/v1/obsidian/sync/approvals")
async def list_sync_approvals(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse({"approvals": await _store(request).list_approvals()})
