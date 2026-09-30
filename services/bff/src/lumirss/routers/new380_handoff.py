"""NEW-380 运维交接摘要路由（管理员；确认/导出需 step-up）。

- POST /api/v1/admin/handoff-summaries            生成（存档，未确认）；
- GET  /api/v1/admin/handoff-summaries            列表；
- GET  /api/v1/admin/handoff-summaries/{id}       详情；
- POST /api/v1/admin/handoff-summaries/{id}/confirm   确认（step-up
      handoff_export，target=操作管理员本人）；
- GET  /api/v1/admin/handoff-summaries/{id}/export    导出（仅 confirmed；
      未确认 409）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new380_handoff import (
    HandoffNotConfirmed,
    HandoffNotFound,
    HandoffStateInvalid,
    confirm_summary,
    create_summary,
    export_summary,
    get_summary,
    list_summaries,
)
from lumirss.routers.admin import _NO_STORE, _require_admin
from lumirss.step_up import require_step_up

router = APIRouter(prefix="/api/v1/admin/handoff-summaries")

STEP_UP_OPERATION = "handoff_export"


async def _admin_or_error(request: Request) -> JSONResponse | dict[str, str]:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    return principal


@router.post("", response_model=None)
async def post_summary(request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    result = await create_summary(request.app.state, by=principal["user_id"])
    return JSONResponse(result, status_code=201, headers=_NO_STORE)


@router.get("", response_model=None)
async def get_summaries(request: Request, limit: int = 20) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    return JSONResponse(
        {"items": await list_summaries(request.app.state.control_db, limit)},
        headers=_NO_STORE,
    )


@router.get("/{summary_id}", response_model=None)
async def get_summary_detail(summary_id: str, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    summary = await get_summary(request.app.state.control_db, summary_id)
    if summary is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "handoff_not_found", "message": "交接摘要不存在。"}},
            headers=_NO_STORE,
        )
    return JSONResponse(summary, headers=_NO_STORE)


@router.post("/{summary_id}/confirm", response_model=None)
async def post_confirm(summary_id: str, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    denial = await require_step_up(request, principal, STEP_UP_OPERATION, principal["user_id"])
    if denial is not None:
        return denial
    try:
        result = await confirm_summary(
            request.app.state.control_db, summary_id=summary_id, by=principal["user_id"]
        )
    except HandoffNotFound:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "handoff_not_found", "message": "交接摘要不存在。"}},
            headers=_NO_STORE,
        )
    except HandoffStateInvalid:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "handoff_state", "message": "摘要已导出，不能再次确认。"}},
            headers=_NO_STORE,
        )
    from lumirss.accounts_store import AccountsStore

    await AccountsStore(request.app.state.control_db).audit(
        actor=principal["user_id"],
        action="handoff_confirmed",
        object_type="handoff_summary",
        object_id=summary_id,
    )
    return JSONResponse(result, headers=_NO_STORE)


@router.get("/{summary_id}/export", response_model=None)
async def get_export(summary_id: str, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        result = await export_summary(request.app.state.control_db, summary_id)
    except HandoffNotFound:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "handoff_not_found", "message": "交接摘要不存在。"}},
            headers=_NO_STORE,
        )
    except HandoffNotConfirmed:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "handoff_not_confirmed",
                    "message": "交接摘要未确认——管理员须先 confirm（对内容负责），再导出。",
                }
            },
            headers=_NO_STORE,
        )
    return JSONResponse(result, headers=_NO_STORE)
