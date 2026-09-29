"""NEW-375 配额变更批次路由（管理员；执行需 step-up）。

- POST /api/v1/admin/quota-batches/preview  预览（存 draft，不改任何账户）；
- GET  /api/v1/admin/quota-batches          批次列表；
- GET  /api/v1/admin/quota-batches/{id}     批次 + 逐账户结果；
- POST /api/v1/admin/quota-batches/{id}/execute  执行（step-up
      quota_batch_execute，target=操作管理员本人）；
- POST /api/v1/admin/quota-batches/{id}/cancel   取消 draft。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new375_quota_batch import (
    QuotaBatchInvalid,
    QuotaBatchNotFound,
    QuotaBatchStateInvalid,
    cancel_batch,
    clean_changes,
    create_draft,
    execute_batch,
    get_batch,
    list_batches,
    preview_change,
)
from lumirss.routers.admin import _NO_STORE, _require_admin
from lumirss.step_up import require_step_up

router = APIRouter(prefix="/api/v1/admin/quota-batches")

STEP_UP_OPERATION = "quota_batch_execute"


class ChangeItem(BaseModel):
    userId: str = Field(min_length=1, max_length=64)
    caps: dict[str, int] | None = None
    clear: bool = False


class PreviewBody(BaseModel):
    model_config = {"extra": "forbid"}

    changes: list[ChangeItem] = Field(min_length=1, max_length=50)


def _invalid(exc: QuotaBatchInvalid) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_quota_batch", "message": str(exc)}},
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


@router.post("/preview", response_model=None)
async def post_preview(payload: PreviewBody, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        changes = clean_changes([item.model_dump() for item in payload.changes])
    except QuotaBatchInvalid as exc:
        return _invalid(exc)
    previews = [
        await preview_change(request.app.state, request.app.state.control_db, change)
        for change in changes
    ]
    draft = await create_draft(
        request.app.state.control_db, changes=changes, by=principal["user_id"]
    )
    return JSONResponse({**draft, "preview": previews}, headers=_NO_STORE)


@router.get("", response_model=None)
async def get_batches(request: Request, limit: int = 20) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    return JSONResponse(
        {"items": await list_batches(request.app.state.control_db, limit)},
        headers=_NO_STORE,
    )


@router.get("/{batch_id}", response_model=None)
async def get_batch_detail(batch_id: str, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    batch = await get_batch(request.app.state.control_db, batch_id)
    if batch is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "quota_batch_not_found", "message": "批次不存在。"}},
            headers=_NO_STORE,
        )
    return JSONResponse(batch, headers=_NO_STORE)


@router.post("/{batch_id}/execute", response_model=None)
async def post_execute(batch_id: str, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    denial = await require_step_up(request, principal, STEP_UP_OPERATION, principal["user_id"])
    if denial is not None:
        return denial
    try:
        result = await execute_batch(
            request.app.state,
            request.app.state.control_db,
            batch_id=batch_id,
            by=principal["user_id"],
        )
    except QuotaBatchNotFound:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "quota_batch_not_found", "message": "批次不存在。"}},
            headers=_NO_STORE,
        )
    except QuotaBatchStateInvalid:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "quota_batch_state", "message": "批次不是 draft 状态，不能执行。"}},
            headers=_NO_STORE,
        )
    from lumirss.accounts_store import AccountsStore

    ok = sum(1 for item in result["results"] if item["outcome"] == "ok")
    await AccountsStore(request.app.state.control_db).audit(
        actor=principal["user_id"],
        action="quota_batch_executed",
        object_type="quota_batch",
        object_id=batch_id,
        detail=f"ok={ok}",
    )
    return JSONResponse(result, headers=_NO_STORE)


@router.post("/{batch_id}/cancel", response_model=None)
async def post_cancel(batch_id: str, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        result = await cancel_batch(request.app.state.control_db, batch_id)
    except QuotaBatchNotFound:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "quota_batch_not_found", "message": "批次不存在。"}},
            headers=_NO_STORE,
        )
    except QuotaBatchStateInvalid:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "quota_batch_state", "message": "批次不是 draft 状态，不能取消。"}},
            headers=_NO_STORE,
        )
    return JSONResponse(result, headers=_NO_STORE)
