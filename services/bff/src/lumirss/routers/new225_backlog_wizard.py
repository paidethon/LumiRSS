"""NEW-225 积压处理向导路由（预览 → keep / archive / stage 显式处置）。

- 预览按来源抽样（真实 COUNT + ≤3 标题样本），已「审过保留」的来源
  排除并如实标注；
- 归档两段式：preview 出 token（30s），apply 必带同一 token——
  **绝不默认全标已读**；实际置读走 N049 同一管线（可撤销台账）；
- 分批阅读：候选加入用户指定时段（未指定 → 422，服务端不替用户挑）；
- 稳定错误信封：invalid_backlog_wizard / backlog_wizard_conflict。
"""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from lumirss.deps import _get_adapter, _get_search_service
from lumirss.entryref import decode_entry_ref
from lumirss.new225_backlog_wizard import (
    BacklogWizardStore,
    WizardConflict,
    WizardInvalid,
)

router = APIRouter()


def _store(request: Request) -> BacklogWizardStore:
    return BacklogWizardStore(request.app.state.db)


class WizardRangeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    olderThanDays: int = Field(ge=7, le=365)


class WizardPreviewGroup(BaseModel):
    feedUrl: str
    feedTitle: str | None = None
    unreadCount: int
    sample: list[dict[str, Any]]
    oldest: str | None = None


class WizardPreviewResponse(BaseModel):
    olderThanDays: int
    cutoff: str
    groups: list[WizardPreviewGroup]
    truncated: bool
    keptDecisionsExcluded: int
    effectiveExclusions: list[str]


class WizardKeepRequest(BaseModel):
    model_config = {"extra": "forbid"}

    feedUrl: str
    olderThanDays: int = Field(ge=7, le=365)
    note: str | None = Field(default=None, max_length=200)


class WizardKeepResponse(BaseModel):
    feedUrl: str
    olderThanDays: int
    note: str | None = None
    decidedAt: str
    outcome: str


class WizardKeepListResponse(BaseModel):
    items: list[dict[str, Any]]


class WizardArchivePreviewRequest(WizardRangeRequest):
    model_config = {"extra": "forbid"}

    feedUrl: str


class WizardArchivePreviewResponse(BaseModel):
    feedUrl: str
    olderThanDays: int
    count: int
    sample: list[dict[str, Any]]
    effectiveExclusions: list[str]
    confirmToken: str
    note: str


class WizardArchiveApplyRequest(WizardArchivePreviewRequest):
    model_config = {"extra": "forbid"}

    confirmToken: str
    """archive-preview 返回的一次性 token（30s；缺失/漂移 → 409）。"""


class WizardArchiveApplyResponse(BaseModel):
    feedUrl: str
    olderThanDays: int
    applied: int
    failed: int
    batchLogId: str | None = None
    undoAvailable: bool


class WizardStageRequest(WizardArchivePreviewRequest):
    model_config = {"extra": "forbid"}

    targetSlotId: str
    """分批阅读的目标时段（用户显式选择）。"""


class WizardStageResponse(BaseModel):
    feedUrl: str
    olderThanDays: int
    slotId: str
    staged: list[str]
    stagedCount: int
    skippedAlreadyInSlot: int
    note: str


@router.post("/api/v1/backlog/wizard/preview", response_model=WizardPreviewResponse)
async def backlog_wizard_preview(
    payload: WizardRangeRequest, request: Request
) -> WizardPreviewResponse:
    """长积压按来源抽样预览（真实 COUNT；纯读取，无任何写副作用）。"""
    return WizardPreviewResponse(**await _store(request).preview(payload.olderThanDays))


@router.post("/api/v1/backlog/wizard/keep", response_model=WizardKeepResponse)
async def backlog_wizard_keep(
    payload: WizardKeepRequest, request: Request
) -> WizardKeepResponse:
    """「审过、决定保留未读」台账（幂等；后续同范围预览排除该来源）。"""
    return WizardKeepResponse(
        **await _store(request).keep(payload.feedUrl, payload.olderThanDays, payload.note)
    )


@router.get("/api/v1/backlog/wizard/keep", response_model=WizardKeepListResponse)
async def backlog_wizard_keep_list(request: Request) -> WizardKeepListResponse:
    """保留决策台账列表。"""
    return WizardKeepListResponse(**await _store(request).list_keep_decisions())


@router.post(
    "/api/v1/backlog/wizard/archive-preview",
    response_model=WizardArchivePreviewResponse,
)
async def backlog_wizard_archive_preview(
    payload: WizardArchivePreviewRequest, request: Request
) -> WizardArchivePreviewResponse:
    """归档预演：真实 COUNT + 30s 一次性 token（不写任何状态）。"""
    return WizardArchivePreviewResponse(
        **await _store(request).archive_preview(payload.feedUrl, payload.olderThanDays)
    )


@router.post(
    "/api/v1/backlog/wizard/archive-apply",
    response_model=WizardArchiveApplyResponse,
)
async def backlog_wizard_archive_apply(
    payload: WizardArchiveApplyRequest, request: Request
) -> WizardArchiveApplyResponse:
    """归档执行（token 缺失/过期/条件漂移 → 409）。

    逐条走既有 set-read 管线（FreshRSS set_entry_state + 投影镜像，
    set 语义）；实际成功的 refs 写入 N049 撤销台账。单条失败不中断。"""

    async def mark_read(entry_ref: str) -> bool:
        adapter = _get_adapter(request)
        search = _get_search_service(request)
        try:
            await adapter.set_entry_state(decode_entry_ref(entry_ref), read=True, starred=None)
            await search.set_entry_read(entry_ref, True)
            return True
        except Exception:  # noqa: BLE001 — 单条失败不中断整批
            return False

    result = await _store(request).archive_apply(
        payload.feedUrl, payload.olderThanDays, payload.confirmToken, mark_read
    )
    return WizardArchiveApplyResponse(**result)


@router.post("/api/v1/backlog/wizard/stage", response_model=WizardStageResponse)
async def backlog_wizard_stage(
    payload: WizardStageRequest, request: Request
) -> WizardStageResponse:
    """分批阅读：来源未读样本（≤10）加入用户指定时段。"""
    return WizardStageResponse(
        **await _store(request).stage_batches(
            payload.feedUrl, payload.olderThanDays, payload.targetSlotId
        )
    )


__all__ = ["router", "WizardConflict", "WizardInvalid"]
