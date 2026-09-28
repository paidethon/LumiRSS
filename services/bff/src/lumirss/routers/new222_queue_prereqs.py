"""NEW-222 队列依赖关系路由。

- 依赖纯属建议：视图逐条报告 met/unmet（basis 诚实标注：read /
  queue-done / slot-done / unread / unknown），没有任何端点因未满足
  而阻止打开或完成材料；
- 稳定错误信封：invalid_queue_prereq / queue_prereq_not_found。
"""

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.new222_queue_prereqs import (
    PrereqInvalid,
    PrereqNotFound,
    PrereqStore,
)

router = APIRouter()


def _store(request: Request) -> PrereqStore:
    return PrereqStore(request.app.state.db)


class PrereqCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str
    prereqRef: str
    """先读项（读完它再读 itemRef）。"""


class PrereqView(BaseModel):
    id: str
    itemRef: str
    prereqRef: str
    createdAt: str


class PrereqCreateResponse(PrereqView):
    outcome: str = "created"
    """created | duplicate。"""


class PrereqEntryView(BaseModel):
    id: str
    prereqRef: str
    title: str | None = None
    met: bool
    basis: str
    createdAt: str


class PrereqItemViewResponse(BaseModel):
    itemRef: str
    prereqs: list[PrereqEntryView]
    unmetCount: int
    advisory: bool
    note: str


class PrereqTodaySummaryResponse(BaseModel):
    queueDate: str
    itemsWithUnmet: list[dict[str, Any]]


@router.post(
    "/api/v1/queue/prereqs",
    response_model=PrereqCreateResponse,
    responses={200: {"model": PrereqCreateResponse}, 201: {"model": PrereqCreateResponse}},
)
async def create_queue_prereq(
    payload: PrereqCreateRequest, request: Request, response: Response
) -> PrereqCreateResponse:
    """为材料设置先读项（新 201 / 重复幂等 200 / 自指或成环 422）。"""
    row, outcome = await _store(request).add_prereq(payload.itemRef, payload.prereqRef)
    response.status_code = 201 if outcome == "created" else 200
    return PrereqCreateResponse(**row, outcome=outcome)


@router.get("/api/v1/queue/prereqs/today", response_model=PrereqTodaySummaryResponse)
async def prereq_today_summary(request: Request) -> PrereqTodaySummaryResponse:
    """今日队列中带未满足前置的成员汇总（整理一览；纯读取）。"""
    return PrereqTodaySummaryResponse(**await _store(request).list_for_today_queue())


@router.get("/api/v1/queue/prereqs", response_model=PrereqItemViewResponse)
async def view_item_prereqs(
    request: Request, itemRef: str
) -> PrereqItemViewResponse:
    """材料的先读项视图（met/unmet 逐条 + basis；advisory only）。"""
    return PrereqItemViewResponse(**await _store(request).view_item(itemRef))


@router.delete("/api/v1/queue/prereqs/{prereq_id}", status_code=204)
async def delete_queue_prereq(prereq_id: str, request: Request) -> Response:
    """删除一条依赖关系（不存在 → 404）。"""
    await _store(request).remove_prereq(prereq_id)
    return Response(status_code=204)


__all__ = ["router", "PrereqInvalid", "PrereqNotFound"]
