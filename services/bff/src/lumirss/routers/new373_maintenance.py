"""NEW-373 维护通知路由。

- POST /api/v1/admin/maintenance/drill          演练（admin guard；无副作用）；
- GET  /api/v1/admin/maintenance/drills         演练历史；
- POST /api/v1/admin/maintenance/windows        排程（step-up maintenance_schedule，
      target=操作管理员本人）；
- GET  /api/v1/admin/maintenance/windows        窗口台账；
- POST /api/v1/admin/maintenance/windows/{id}/settle  收尾（completed/cancelled）；
- GET  /api/v1/maintenance/notice               全体用户的真实消费点（登录与否均可）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new373_maintenance import (
    MaintenanceInvalid,
    WindowAlreadySettled,
    WindowNotFound,
    active_window,
    clean_window_fields,
    create_drill,
    list_drills,
    list_windows,
    schedule_window,
    settle_window,
)
from lumirss.routers.admin import _NO_STORE, _require_admin
from lumirss.step_up import require_step_up

router = APIRouter()

STEP_UP_OPERATION = "maintenance_schedule"


class WindowBody(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(min_length=1, max_length=120)
    notice: str = Field(min_length=1, max_length=1000)
    startsAt: str = Field(min_length=1, max_length=40)
    endsAt: str = Field(min_length=1, max_length=40)


class SettleBody(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(pattern="^(completed|cancelled)$")


def _invalid(exc: MaintenanceInvalid) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_maintenance_payload", "message": str(exc)}},
        headers=_NO_STORE,
    )


async def _admin_or_error(request: Request) -> JSONResponse | dict[str, str]:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    return principal


@router.post("/api/v1/admin/maintenance/drill", response_model=None)
async def post_drill(payload: WindowBody, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        fields = clean_window_fields(
            payload.title, payload.notice, payload.startsAt, payload.endsAt
        )
    except MaintenanceInvalid as exc:
        return _invalid(exc)
    result = await create_drill(
        request.app.state.control_db, fields=fields, by=principal["user_id"]
    )
    return JSONResponse(result, headers=_NO_STORE)


@router.get("/api/v1/admin/maintenance/drills", response_model=None)
async def get_drills(request: Request, limit: int = 20) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    return JSONResponse(
        {"items": await list_drills(request.app.state.control_db, limit)},
        headers=_NO_STORE,
    )


@router.post("/api/v1/admin/maintenance/windows", response_model=None)
async def post_window(payload: WindowBody, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    denial = await require_step_up(request, principal, STEP_UP_OPERATION, principal["user_id"])
    if denial is not None:
        return denial
    try:
        fields = clean_window_fields(
            payload.title, payload.notice, payload.startsAt, payload.endsAt
        )
    except MaintenanceInvalid as exc:
        return _invalid(exc)
    result = await schedule_window(
        request.app.state.control_db, fields=fields, by=principal["user_id"]
    )
    from lumirss.accounts_store import AccountsStore

    await AccountsStore(request.app.state.control_db).audit(
        actor=principal["user_id"],
        action="maintenance_window_scheduled",
        object_type="maintenance_window",
        object_id=result["id"],
    )
    return JSONResponse(result, headers=_NO_STORE)


@router.get("/api/v1/admin/maintenance/windows", response_model=None)
async def get_windows(request: Request, limit: int = 20) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    return JSONResponse(
        {"items": await list_windows(request.app.state.control_db, limit)},
        headers=_NO_STORE,
    )


@router.post("/api/v1/admin/maintenance/windows/{window_id}/settle", response_model=None)
async def post_settle(window_id: str, payload: SettleBody, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        result = await settle_window(
            request.app.state.control_db,
            window_id=window_id,
            status=payload.status,
            by=principal["user_id"],
        )
    except WindowNotFound:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "window_not_found", "message": "窗口不存在。"}},
            headers=_NO_STORE,
        )
    except WindowAlreadySettled:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "window_already_settled", "message": "窗口已收尾。"}},
            headers=_NO_STORE,
        )
    from lumirss.accounts_store import AccountsStore

    await AccountsStore(request.app.state.control_db).audit(
        actor=principal["user_id"],
        action=f"maintenance_window_{payload.status}",
        object_type="maintenance_window",
        object_id=window_id,
    )
    return JSONResponse(result, headers=_NO_STORE)


@router.get("/api/v1/maintenance/notice", response_model=None)
async def get_notice(request: Request) -> JSONResponse:
    """全体用户（含未登录访客）的真实维护提示消费点。"""
    payload = await active_window(request.app.state.control_db)
    return JSONResponse(payload, headers=_NO_STORE)
