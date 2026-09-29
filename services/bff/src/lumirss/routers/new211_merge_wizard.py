"""NEW-211 标签合并向导路由 —— 多源→单目标原子合并（预览/应用/撤销/台账）。

全部端点只触 per-user 库本地表（无 AI / 无上游网络）。错误走本文件
稳定信封（与 routers/quick_actions.py 同一本地映射模式）：
422 invalid_merge_wizard / 404 merge_log_not_found / 409 merge_undo_conflict。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new211_tag_merge_wizard import (
    MergeLogNotFound,
    MergeUndoConflict,
    MergeWizardInvalid,
    TagMergeWizardStore,
)

router = APIRouter()


class MergeWizardPreviewRequest(BaseModel):
    model_config = {"extra": "forbid"}

    sourceIds: list[int] = Field(min_length=1, max_length=20)
    targetId: int


class MergeWizardApplyRequest(BaseModel):
    model_config = {"extra": "forbid"}

    sourceIds: list[int] = Field(min_length=1, max_length=20)
    targetId: int


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> TagMergeWizardStore:
    return TagMergeWizardStore(request.app.state.db)


@router.post("/api/v1/tags/merge-wizard/preview")
async def merge_wizard_preview(payload: MergeWizardPreviewRequest, request: Request) -> Response:
    """只读预览：逐源绑定/重复、受影响文章数、会被同步的引用数。"""
    try:
        result = await _store(request).preview(payload.sourceIds, payload.targetId)
    except MergeWizardInvalid as exc:
        return _error(422, "invalid_merge_wizard", str(exc))
    return JSONResponse(result)


@router.post("/api/v1/tags/merge-wizard/apply")
async def merge_wizard_apply(payload: MergeWizardApplyRequest, request: Request) -> Response:
    """原子合并：单事务完成快照/折叠/改指/删源/引用同步/落台账。"""
    try:
        result = await _store(request).apply_merge(payload.sourceIds, payload.targetId)
    except MergeWizardInvalid as exc:
        return _error(422, "invalid_merge_wizard", str(exc))
    return JSONResponse(status_code=200, content=result)


@router.get("/api/v1/tags/merge-wizard/logs")
async def merge_wizard_logs(request: Request) -> JSONResponse:
    """可撤销的映射记录（最近 10 条，新→旧）。"""
    return JSONResponse({"items": await _store(request).list_logs()})


@router.post("/api/v1/tags/merge-wizard/logs/{log_id}/undo")
async def merge_wizard_undo(log_id: str, request: Request) -> Response:
    """按记录撤销（24h 窗口）：原子重建全部源标签并原样恢复绑定。"""
    try:
        result = await _store(request).undo(log_id)
    except MergeLogNotFound as exc:
        return _error(404, "merge_log_not_found", str(exc))
    except MergeUndoConflict as exc:
        return _error(
            409,
            "merge_undo_conflict",
            f"源标签「{exc.name}」已被重新占用，无法撤销这次合并。",
        )
    return JSONResponse(result)
