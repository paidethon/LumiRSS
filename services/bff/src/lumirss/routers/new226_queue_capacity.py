"""NEW-226 队列容量上限路由（容量设置 + 待确认区裁决）。

稳定错误信封：invalid_queue_capacity /
queue_capacity_candidate_not_found。既有队列错误
（invalid_queue / queue_item_not_found / queue_item_done）原样透传。
"""

from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.new226_queue_capacity import (
    CapacityCandidateNotFound,
    CapacityInvalid,
    QueueCapacityStore,
)

router = APIRouter()


def _store(request: Request) -> QueueCapacityStore:
    return QueueCapacityStore(request.app.state.db)


class CapacitySettingsView(BaseModel):
    capacity: int | None = None
    enabled: bool = False
    updatedAt: str | None = None
    note: str | None = None


class CapacitySettingsRequest(BaseModel):
    model_config = {"extra": "forbid"}

    capacity: int = Field(ge=1, le=100)
    enabled: bool


class CapacityOfferRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str
    segment: str | None = None


class CapacityOfferResponse(BaseModel):
    id: str | None = None
    itemRef: str
    outcome: str
    """added 系（created/duplicate/resurrected）| overflow | already_pending。"""
    title: str | None = None
    queueDate: str | None = None
    status: str | None = None
    capacity: int | None = None
    note: str | None = None


class CapacityCandidateView(BaseModel):
    id: str
    itemRef: str
    queueDate: str
    createdAt: str
    status: str
    title: str | None = None


class CapacityPendingResponse(BaseModel):
    capacity: int | None
    enabled: bool
    queueCount: int
    items: list[CapacityCandidateView]


class CapacityReplaceRequest(BaseModel):
    model_config = {"extra": "forbid"}

    replacedItemId: str
    """被替换出去的既有队列行 id（用户显式指定）。"""


class CapacityReplaceResponse(BaseModel):
    candidate: dict[str, Any]
    addedItem: dict[str, Any]
    addedOutcome: str
    removedItemId: str


class CapacityDismissResponse(BaseModel):
    id: str
    itemRef: str
    status: Literal["dismissed"]


@router.get("/api/v1/queue/capacity", response_model=CapacitySettingsView)
async def get_queue_capacity(request: Request) -> CapacitySettingsView:
    """容量设置（未设置时明示）。"""
    return CapacitySettingsView(**await _store(request).get_settings())


@router.put("/api/v1/queue/capacity", response_model=CapacitySettingsView)
async def set_queue_capacity(
    payload: CapacitySettingsRequest, request: Request
) -> CapacitySettingsView:
    """设置/更新容量（1..100）与启用开关。"""
    return CapacitySettingsView(
        **await _store(request).set_settings(payload.capacity, payload.enabled)
    )


@router.post(
    "/api/v1/queue/capacity/offer",
    response_model=CapacityOfferResponse,
    responses={200: {"model": CapacityOfferResponse}, 201: {"model": CapacityOfferResponse}},
)
async def offer_queue_item(
    payload: CapacityOfferRequest, request: Request, response: Response
) -> CapacityOfferResponse:
    """想加入今日队列：未满 → 正常加入；已满 → 候选进待确认区
    （绝不自动顶掉任何行）。"""
    result = await _store(request).offer(payload.itemRef, payload.segment)
    if result.get("outcome") == "created":
        response.status_code = 201
    return CapacityOfferResponse(**result)


@router.get("/api/v1/queue/capacity/pending", response_model=CapacityPendingResponse)
async def list_capacity_pending(request: Request) -> CapacityPendingResponse:
    """待确认区（pending_choice 候选 + 当前队列计数）。"""
    return CapacityPendingResponse(**await _store(request).list_pending())


@router.post(
    "/api/v1/queue/capacity/pending/{candidate_id}/replace",
    response_model=CapacityReplaceResponse,
)
async def replace_with_candidate(
    candidate_id: str, payload: CapacityReplaceRequest, request: Request
) -> CapacityReplaceResponse:
    """裁决「替换」：移除指定队列行 + 加入候选（显式用户动作）。"""
    result = await _store(request).resolve_replace(candidate_id, payload.replacedItemId)
    return CapacityReplaceResponse(**result)


@router.post(
    "/api/v1/queue/capacity/pending/{candidate_id}/dismiss",
    response_model=CapacityDismissResponse,
)
async def dismiss_candidate(
    candidate_id: str, request: Request
) -> CapacityDismissResponse:
    """裁决「暂不加入」（幂等；已裁决 → 404）。"""
    result = await _store(request).resolve_dismiss(candidate_id)
    return CapacityDismissResponse(id=result["id"], itemRef=result["itemRef"], status="dismissed")


__all__ = ["router", "CapacityCandidateNotFound", "CapacityInvalid"]
