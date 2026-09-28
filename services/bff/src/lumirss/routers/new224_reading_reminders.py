"""NEW-224 阅读预约清单路由（一次性、应用内、可改期/取消）。

稳定错误信封：invalid_reading_reminder / reading_reminder_not_found。
"""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.new224_reading_reminders import (
    ReminderInvalid,
    ReminderNotFound,
    ReminderStore,
)

router = APIRouter()


def _store(request: Request) -> ReminderStore:
    return ReminderStore(request.app.state.db)


class ReminderCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str
    remindAt: str
    """一次性预约时间（ISO 时间戳）。"""
    note: str | None = Field(default=None, max_length=200)


class ReminderView(BaseModel):
    id: str
    itemRef: str
    remindAt: str
    note: str | None = None
    status: str
    createdAt: str
    remindedAt: str | None = None
    updatedAt: str
    title: str | None = None
    due: bool | None = None


class ReminderListResponse(BaseModel):
    items: list[ReminderView]
    serverNow: str
    channel: str
    note: str


class ReminderDueResponse(BaseModel):
    serverNow: str
    items: list[ReminderView]
    channel: str
    note: str


class ReminderRescheduleRequest(BaseModel):
    model_config = {"extra": "forbid"}

    remindAt: str


@router.post(
    "/api/v1/reading/reminders", response_model=ReminderView, status_code=201
)
async def create_reading_reminder(
    payload: ReminderCreateRequest, request: Request
) -> ReminderView:
    """创建一次性阅读预约（201；活跃预约上限 100）。"""
    row = await _store(request).create(payload.itemRef, payload.remindAt, payload.note)
    return ReminderView(**row)


@router.get("/api/v1/reading/reminders", response_model=ReminderListResponse)
async def list_reading_reminders(
    request: Request, includeCancelled: bool = False
) -> ReminderListResponse:
    """预约清单（默认 active+done；cancelled 需显式包含）。"""
    return ReminderListResponse(
        **await _store(request).list_reminders(include_cancelled=includeCancelled)
    )


@router.get("/api/v1/reading/reminders/due", response_model=ReminderDueResponse)
async def due_reading_reminders(request: Request) -> ReminderDueResponse:
    """到期面（应用内轮询）：active 且到时；首次被读到记 reminded_at。"""
    return ReminderDueResponse(**await _store(request).due())


@router.post(
    "/api/v1/reading/reminders/{reminder_id}/reschedule", response_model=ReminderView
)
async def reschedule_reading_reminder(
    reminder_id: str, payload: ReminderRescheduleRequest, request: Request
) -> ReminderView:
    """改期（仅 active）。"""
    row = await _store(request).reschedule(reminder_id, payload.remindAt)
    return ReminderView(**row)


@router.post("/api/v1/reading/reminders/{reminder_id}/cancel", response_model=ReminderView)
async def cancel_reading_reminder(reminder_id: str, request: Request) -> ReminderView:
    """取消（幂等；done → 422）。"""
    row = await _store(request).cancel(reminder_id)
    return ReminderView(**row)


@router.post("/api/v1/reading/reminders/{reminder_id}/complete", response_model=ReminderView)
async def complete_reading_reminder(reminder_id: str, request: Request) -> ReminderView:
    """用户显式完成（读到点了；cancelled → 422）。"""
    row = await _store(request).complete(reminder_id)
    return ReminderView(**row)


@router.delete("/api/v1/reading/reminders/{reminder_id}", status_code=204)
async def delete_reading_reminder(reminder_id: str, request: Request) -> Response:
    """物理删除一条预约（housekeeping；取消用 cancel）。"""
    await _store(request).delete(reminder_id)
    return Response(status_code=204)


__all__ = ["router", "ReminderInvalid", "ReminderNotFound"]
