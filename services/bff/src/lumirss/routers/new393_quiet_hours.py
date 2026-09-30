"""NEW-393 提醒静默时段路由。

- GET /api/v1/notifications/quiet-hours          当前设置（未设置 = 关闭）
- PUT /api/v1/notifications/quiet-hours          设置窗口/时区/启停
- GET /api/v1/notifications/quiet-summary        静默状态 + 窗口内未读汇总
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new393_quiet_hours import (
    QuietHoursInvalid,
    get_quiet_hours,
    quiet_summary,
    set_quiet_hours,
)
from lumirss.user_scope import require_user_id

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
        headers=_NO_STORE,
    )


class QuietHoursBody(BaseModel):
    model_config = {"extra": "forbid"}

    startHHMM: str = Field(min_length=5, max_length=5)
    endHHMM: str = Field(min_length=5, max_length=5)
    timeZone: str = Field(min_length=1, max_length=64)
    enabled: bool = True


@router.get("/api/v1/notifications/quiet-hours", response_model=None)
async def get_quiet_hours_route(request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(
        await get_quiet_hours(request.app.state.control_db, user_id),
        headers=_NO_STORE,
    )


@router.put("/api/v1/notifications/quiet-hours", response_model=None)
async def put_quiet_hours(payload: QuietHoursBody, request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        result = await set_quiet_hours(
            request.app.state.control_db,
            user_id,
            start_hhmm=payload.startHHMM,
            end_hhmm=payload.endHHMM,
            time_zone=payload.timeZone,
            enabled=payload.enabled,
        )
    except QuietHoursInvalid as exc:
        return _error(422, "invalid_quiet_hours", str(exc))
    return JSONResponse(result, headers=_NO_STORE)


@router.get("/api/v1/notifications/quiet-summary", response_model=None)
async def get_quiet_summary(request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(
        await quiet_summary(request.app.state.control_db, user_id),
        headers=_NO_STORE,
    )
