"""NEW-371 后台任务日历路由（管理员）。

- GET  /api/v1/admin/task-calendar           计划 × 槽位实况 × 暂停 × 最近结果；
- POST /api/v1/admin/task-calendar/{kind}/pause   step-up（task_kind_pause，
      实例级操作 → target=操作管理员本人，同 NEW-304 口径）；
- POST /api/v1/admin/task-calendar/{kind}/resume  同上。

本面无任何 shell / 信号 / 进程控制入口；「暂停」是治理注册表事实。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new371_task_calendar import (
    PauseAlreadyActive,
    PauseNotActive,
    TaskKindUnknown,
    calendar_snapshot,
    kind_exists,
    pause_kind,
    resume_kind,
)
from lumirss.routers.admin import _NO_STORE, _require_admin
from lumirss.step_up import require_step_up

router = APIRouter(prefix="/api/v1/admin/task-calendar")

STEP_UP_OPERATION = "task_kind_pause"


class PauseBody(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(min_length=1, max_length=200)
    impact: str = Field(min_length=1, max_length=500)


def _kind_error(exc: TaskKindUnknown) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "unknown_task_kind", "message": str(exc)}},
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


@router.get("", response_model=None, response_model_exclude_none=True)
async def get_task_calendar(request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    snapshot = await calendar_snapshot(
        request.app.state, request.app.state.control_db, request.app.state.db
    )
    return JSONResponse(snapshot, headers=_NO_STORE)


@router.post("/{kind}/pause", response_model=None, response_model_exclude_none=True)
async def pause_task_kind(kind: str, payload: PauseBody, request: Request) -> JSONResponse:
    if not kind_exists(kind):
        return _kind_error(TaskKindUnknown(f"unknown task kind: {kind}."))
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    denial = await require_step_up(request, principal, STEP_UP_OPERATION, principal["user_id"])
    if denial is not None:
        return denial
    control_db = request.app.state.control_db
    try:
        result = await pause_kind(
            control_db,
            kind=kind,
            reason=payload.reason,
            impact=payload.impact,
            by=principal["user_id"],
        )
    except PauseAlreadyActive:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "pause_already_active", "message": "该任务档已有生效中的暂停。"}},
            headers=_NO_STORE,
        )
    except TaskKindUnknown as exc:
        return _kind_error(exc)
    from lumirss.accounts_store import AccountsStore

    await AccountsStore(control_db).audit(
        actor=principal["user_id"],
        action="task_kind_paused",
        object_type="task_kind",
        object_id=kind,
        detail=f"impact={payload.impact[:80]}",
    )
    return JSONResponse(result, headers=_NO_STORE)


@router.post("/{kind}/resume", response_model=None, response_model_exclude_none=True)
async def resume_task_kind(kind: str, request: Request) -> JSONResponse:
    if not kind_exists(kind):
        return _kind_error(TaskKindUnknown(f"unknown task kind: {kind}."))
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    denial = await require_step_up(request, principal, STEP_UP_OPERATION, principal["user_id"])
    if denial is not None:
        return denial
    control_db = request.app.state.control_db
    try:
        result = await resume_kind(control_db, kind=kind, by=principal["user_id"])
    except PauseNotActive:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "pause_not_active", "message": "该任务档没有生效中的暂停。"}},
            headers=_NO_STORE,
        )
    except TaskKindUnknown as exc:
        return _kind_error(exc)
    from lumirss.accounts_store import AccountsStore

    await AccountsStore(control_db).audit(
        actor=principal["user_id"], action="task_kind_resumed", object_type="task_kind", object_id=kind
    )
    return JSONResponse(result, headers=_NO_STORE)
