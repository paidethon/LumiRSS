"""NEW-372 任务优先级路由。

- GET  /api/v1/admin/task-priorities            管理员看全部登记行；
- PUT  /api/v1/admin/task-priorities/{user_id}  管理员改某账户（404 未知）；
- DEL  /api/v1/admin/task-priorities/{user_id}  恢复默认；
- GET/PUT /api/v1/tasks/priority                普通用户只能操作自己的行。

不设 step-up：变更只影响下一轮清扫顺序、完全可逆、不触碰数据与
秘密——但它仍在审计里（admin 变更记 audit）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new372_task_priority import (
    PriorityInvalid,
    clear_priority,
    get_priority,
    list_priorities,
    set_priority,
)
from lumirss.routers.admin import _NO_STORE, _require_admin

router = APIRouter()


class PriorityBody(BaseModel):
    model_config = {"extra": "forbid"}

    priority: str | int = Field(description="low/normal/high 或 1..3")


def _invalid(exc: PriorityInvalid) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_priority", "message": str(exc)}},
        headers=_NO_STORE,
    )


async def _current_user_id(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id as _session_user

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _session_user(request)


@router.get("/api/v1/admin/task-priorities", response_model=None)
async def admin_list_priorities(request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    items = await list_priorities(request.app.state.control_db)
    return JSONResponse(
        {"items": items, "preemption": False, "appliesAt": "next_sweep"},
        headers=_NO_STORE,
    )


async def _admin_target_or_error(
    user_id: str, request: Request
) -> JSONResponse | dict[str, str]:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    user = await request.app.state.accounts.get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    return principal


@router.put("/api/v1/admin/task-priorities/{user_id}", response_model=None)
async def admin_set_priority(user_id: str, payload: PriorityBody, request: Request) -> JSONResponse:
    principal = await _admin_target_or_error(user_id, request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        result = await set_priority(
            request.app.state.control_db,
            user_id=user_id,
            level=payload.priority,
            updated_by=principal["user_id"],
        )
    except PriorityInvalid as exc:
        return _invalid(exc)
    from lumirss.accounts_store import AccountsStore

    await AccountsStore(request.app.state.control_db).audit(
        actor=principal["user_id"],
        action="task_priority_set",
        object_type="user",
        object_id=user_id,
        detail=f"priority={result['priority']}",
    )
    return JSONResponse(result, headers=_NO_STORE)


@router.delete("/api/v1/admin/task-priorities/{user_id}", response_model=None)
async def admin_clear_priority(user_id: str, request: Request) -> JSONResponse:
    principal = await _admin_target_or_error(user_id, request)
    if isinstance(principal, JSONResponse):
        return principal
    cleared = await clear_priority(
        request.app.state.control_db, user_id=user_id, updated_by=principal["user_id"]
    )
    if cleared:
        from lumirss.accounts_store import AccountsStore

        await AccountsStore(request.app.state.control_db).audit(
            actor=principal["user_id"],
            action="task_priority_cleared",
            object_type="user",
            object_id=user_id,
        )
    return JSONResponse({"cleared": cleared}, headers=_NO_STORE)


@router.get("/api/v1/tasks/priority", response_model=None)
async def get_own_priority(request: Request) -> JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={"error": {"type": "session_required", "message": "Login required."}},
            headers=_NO_STORE,
        )
    result = await get_priority(request.app.state.control_db, user_id)
    return JSONResponse(result, headers=_NO_STORE)


@router.put("/api/v1/tasks/priority", response_model=None)
async def put_own_priority(payload: PriorityBody, request: Request) -> JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={"error": {"type": "session_required", "message": "Login required."}},
            headers=_NO_STORE,
        )
    try:
        result = await set_priority(
            request.app.state.control_db,
            user_id=user_id,
            level=payload.priority,
            updated_by=user_id,
        )
    except PriorityInvalid as exc:
        return _invalid(exc)
    return JSONResponse(result, headers=_NO_STORE)
