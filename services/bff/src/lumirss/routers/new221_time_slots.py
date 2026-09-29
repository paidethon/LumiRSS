"""NEW-221 分时段阅读队列路由（r3 阅读队列家族延伸）。

- 时段是命名的生活时段（通勤/午休/晚间…）；文章按 ItemRef 归属；
- 打开时段（POST open）= 接续视图 + last_opened_at 记账；GET 恒无副作用；
- 顺延（carry-over）是显式用户决策：必须指定目标时段；服务端没有
  任何自动顺延/自动完成路径；
- 稳定错误信封：invalid_queue_slot / queue_slot_not_found /
  queue_slot_item_not_found / queue_slot_item_conflict。
"""

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.new221_time_slots import (
    SlotInvalid,
    SlotItemConflict,
    SlotItemNotFound,
    SlotNotFound,
    TimeSlotStore,
)

router = APIRouter()


def _store(request: Request) -> TimeSlotStore:
    return TimeSlotStore(request.app.state.db)


# ---- 请求/响应模型（OpenAPI 契约真源） ----


class SlotCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=60)
    """时段名（通勤/午休/晚间…）。"""


class SlotItemView(BaseModel):
    id: str
    slotId: str
    slotName: str | None = None
    itemRef: str
    addedAt: str
    position: int
    status: str
    doneAt: str | None = None
    carriedAt: str | None = None
    carriedToSlot: str | None = None
    title: str | None = None


class SlotView(BaseModel):
    id: str
    name: str
    position: int
    createdAt: str
    lastOpenedAt: str | None = None
    pendingCount: int = 0
    doneCount: int = 0


class SlotListResponse(BaseModel):
    slots: list[SlotView]


class SlotCreateResponse(SlotView):
    pass


class SlotDetailResponse(SlotView):
    items: list[SlotItemView]


class SlotOpenResponse(SlotDetailResponse):
    resume: dict[str, Any]
    """接续视图：{pendingCount, nextItemRef, nextTitle}（空时段 next 为 null）。"""


class SlotAddItemRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str


class SlotAddItemResponse(SlotItemView):
    outcome: str = "created"
    """created | duplicate。"""


class SlotItemDoneRequest(BaseModel):
    model_config = {"extra": "forbid"}

    done: bool


class SlotCarryOverRequest(BaseModel):
    model_config = {"extra": "forbid"}

    targetSlotId: str
    """顺延目标时段（用户显式选择；绝不自动）。"""


class SlotCarryOverResponse(BaseModel):
    moved: int
    fromSlotId: str
    toSlotId: str
    carriedAt: str


@router.get("/api/v1/queue/slots", response_model=SlotListResponse)
async def list_queue_slots(request: Request) -> SlotListResponse:
    """时段列表（含 pending/done 计数）。"""
    return SlotListResponse(**await _store(request).list_slots())


@router.post("/api/v1/queue/slots", response_model=SlotCreateResponse, status_code=201)
async def create_queue_slot(
    payload: SlotCreateRequest, request: Request
) -> SlotCreateResponse:
    """创建时段（201；同名不禁止——时段以 id 为锚）。"""
    return SlotCreateResponse(**await _store(request).create_slot(payload.name))


@router.get("/api/v1/queue/slots/{slot_id}", response_model=SlotDetailResponse)
async def get_queue_slot(slot_id: str, request: Request) -> SlotDetailResponse:
    """时段详情（无副作用：含全部 pending/done/carried 成员）。"""
    return SlotDetailResponse(**await _store(request).get_slot_detail(slot_id))


@router.post("/api/v1/queue/slots/{slot_id}/open", response_model=SlotOpenResponse)
async def open_queue_slot(slot_id: str, request: Request) -> SlotOpenResponse:
    """打开时段接续：pending 成员按序返回 + last_opened_at 记账。"""
    return SlotOpenResponse(**await _store(request).open_slot(slot_id))


@router.delete("/api/v1/queue/slots/{slot_id}", status_code=204)
async def delete_queue_slot(slot_id: str, request: Request) -> Response:
    """删除空时段（仍有 pending 成员 → 422，先处理再删）。"""
    await _store(request).delete_slot(slot_id)
    return Response(status_code=204)


@router.post(
    "/api/v1/queue/slots/{slot_id}/items",
    response_model=SlotAddItemResponse,
    responses={200: {"model": SlotAddItemResponse}, 201: {"model": SlotAddItemResponse}},
)
async def add_queue_slot_item(
    slot_id: str, payload: SlotAddItemRequest, request: Request, response: Response
) -> SlotAddItemResponse:
    """加入文章到时段（新 201 / 本时段重复 200 / 其他时段已有归属
    409 queue_slot_item_conflict——一篇文章同时只有一个待读时段）。"""
    row, outcome = await _store(request).add_item(slot_id, payload.itemRef)
    response.status_code = 201 if outcome == "created" else 200
    return SlotAddItemResponse(**row, outcome=outcome)


@router.post(
    "/api/v1/queue/slot-items/{item_id}/done", response_model=SlotItemView
)
async def set_queue_slot_item_done(
    item_id: str, payload: SlotItemDoneRequest, request: Request
) -> SlotItemView:
    """时段成员完成状态（set 语义；绝不隐式改写上游已读）。"""
    row = await _store(request).set_item_done(item_id, payload.done)
    return SlotItemView(**row)


@router.delete("/api/v1/queue/slot-items/{item_id}", response_model=SlotItemView)
async def remove_queue_slot_item(item_id: str, request: Request) -> SlotItemView:
    """从时段移出（返回被移出行视图；pending 唯一约束随之释放）。"""
    row = await _store(request).remove_item(item_id)
    return SlotItemView(**row)


@router.post(
    "/api/v1/queue/slots/{slot_id}/carry-over", response_model=SlotCarryOverResponse
)
async def carry_over_queue_slot(
    slot_id: str, payload: SlotCarryOverRequest, request: Request
) -> SlotCarryOverResponse:
    """顺延：该时段全部未完成文章移到目标时段（用户显式决策；
    原行转 carried 保留轨迹，绝不自动发生）。"""
    result = await _store(request).carry_over(slot_id, payload.targetSlotId)
    return SlotCarryOverResponse(**result)


__all__ = [
    "router",
    "SlotInvalid",
    "SlotItemConflict",
    "SlotItemNotFound",
    "SlotNotFound",
]
