"""NEW-275 批量 AI 任务审批单路由 — 清单/审批/执行/取消。

- POST /api/v1/ai/batch-approvals {kind, entryRefs, budgetCalls} → 草稿
- GET  /api/v1/ai/batch-approvals                       → 列表
- GET  /api/v1/ai/batch-approvals/{id}                  → 单（含明细）
- POST /api/v1/ai/batch-approvals/{id}/approve          → 确认（draft→approved）
- POST /api/v1/ai/batch-approvals/{id}/execute          → 按序执行（预算内）
- POST /api/v1/ai/batch-approvals/{id}/cancel {itemId?} → 取消整单/未开始项
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.entryref import decode_entry_ref
from lumirss.new275_batch_approvals import (
    ApprovalInvalid,
    ApprovalNotFound,
    ApprovalStateError,
    BatchApprovalStore,
)

router = APIRouter()


class ApprovalCreateBody(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str
    entryRefs: list[str] = Field(min_length=1, max_length=20)
    budgetCalls: int = Field(ge=1, le=20)


class ApprovalCancelBody(BaseModel):
    model_config = {"extra": "forbid"}

    itemId: str | None = None


def _store(request: Request) -> BatchApprovalStore:
    return BatchApprovalStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _guard(exc: Exception) -> JSONResponse | None:
    if isinstance(exc, ApprovalInvalid):
        return _error(422, "invalid_approval_request", str(exc))
    if isinstance(exc, ApprovalNotFound):
        return _error(404, "approval_not_found", "审批单不存在。")
    if isinstance(exc, ApprovalStateError):
        return JSONResponse(
            status_code=409,
            content={
                "error": {"type": exc.reason, "message": str(exc)},
            },
        )
    return None


async def _run_summary_item(request: Request, entry_ref: str) -> tuple[str, str | None]:
    """单项执行 = 与单篇摘要完全同一费用/守卫路径（quota → 服务）。"""
    from lumirss.ai_quota import quota_denial
    from lumirss.deps import _get_summary_service
    from lumirss.routers.entry_ai import _ai_disabled_denial, _record_ai_task

    decode_entry_ref(entry_ref)
    disabled = await _ai_disabled_denial(request, entry_ref)
    if disabled is not None:
        return "ai_disabled", None
    denial = await quota_denial(request, purpose="summary")
    if denial is not None:
        return "quota_exceeded", None
    try:
        state = await _get_summary_service(request).generate_summary(entry_ref)
    except Exception as exc:  # noqa: BLE001 — 单项失败如实记账
        await _record_ai_task(
            request,
            kind="summary",
            entry_ref=entry_ref,
            status="failed",
            error_type=type(exc).__name__,
        )
        return "failed", type(exc).__name__
    status = "done" if state.status == "success" else "failed"
    await _record_ai_task(
        request,
        kind="summary",
        entry_ref=entry_ref,
        status=status,
        error_type=state.failure_type if status == "failed" else None,
    )
    return status, state.failure_type if status == "failed" else None


@router.post("/api/v1/ai/batch-approvals")
async def create_batch_approval(
    payload: ApprovalCreateBody, request: Request
) -> Response:
    for ref in payload.entryRefs:
        decode_entry_ref(ref)
    try:
        approval = await _store(request).create(
            payload.kind, payload.entryRefs, payload.budgetCalls
        )
    except Exception as exc:  # noqa: BLE001
        denial = _guard(exc)
        if denial is not None:
            return denial
        raise
    return JSONResponse(approval, status_code=201)


@router.get("/api/v1/ai/batch-approvals")
async def list_batch_approvals(request: Request) -> Response:
    approvals = await _store(request).list_approvals()
    return JSONResponse({"items": approvals, "total": len(approvals)})


@router.get("/api/v1/ai/batch-approvals/{approval_id}")
async def get_batch_approval(approval_id: str, request: Request) -> Response:
    try:
        approval = await _store(request).get_approval(approval_id)
    except ApprovalNotFound:
        return _error(404, "approval_not_found", "审批单不存在。")
    return JSONResponse(approval)


@router.post("/api/v1/ai/batch-approvals/{approval_id}/approve")
async def approve_batch_approval(approval_id: str, request: Request) -> Response:
    try:
        approval = await _store(request).approve(approval_id)
    except Exception as exc:  # noqa: BLE001
        denial = _guard(exc)
        if denial is not None:
            return denial
        raise
    return JSONResponse(approval)


@router.post("/api/v1/ai/batch-approvals/{approval_id}/execute")
async def execute_batch_approval(approval_id: str, request: Request) -> Response:
    """确认后执行：逐项走与单篇摘要同一守卫路径；预算用尽即停。"""

    async def run_item(entry_ref: str, _kind: str) -> tuple[str, str | None]:
        return await _run_summary_item(request, entry_ref)

    try:
        approval = await _store(request).execute(approval_id, run_item)
    except Exception as exc:  # noqa: BLE001
        denial = _guard(exc)
        if denial is not None:
            return denial
        raise
    return JSONResponse(approval)


@router.post("/api/v1/ai/batch-approvals/{approval_id}/cancel")
async def cancel_batch_approval(
    approval_id: str, payload: ApprovalCancelBody, request: Request
) -> Response:
    try:
        approval = await _store(request).cancel(approval_id, payload.itemId)
    except Exception as exc:  # noqa: BLE001
        denial = _guard(exc)
        if denial is not None:
            return denial
        raise
    return JSONResponse(approval)
