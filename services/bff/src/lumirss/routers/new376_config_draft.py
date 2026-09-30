"""NEW-376 实例配置草案路由（管理员；应用需 step-up）。

- POST /api/v1/admin/config-drafts           建草案（校验 + 差异 + 生效条件）；
- GET  /api/v1/admin/config-drafts           草案列表；
- GET  /api/v1/admin/config-drafts/{id}      草案详情；
- POST /api/v1/admin/config-drafts/{id}/apply     应用（step-up
      config_draft_apply，target=操作管理员本人）；
- POST /api/v1/admin/config-drafts/{id}/discard   废弃。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new376_config_draft import (
    DRAFTABLE_KEYS,
    ConfigDraftInvalid,
    ConfigDraftNotFound,
    ConfigDraftStateInvalid,
    apply_draft,
    create_draft,
    discard_draft,
    get_draft,
    list_drafts,
)
from lumirss.routers.admin import _NO_STORE, _require_admin
from lumirss.step_up import require_step_up

router = APIRouter(prefix="/api/v1/admin/config-drafts")

STEP_UP_OPERATION = "config_draft_apply"


class DraftBody(BaseModel):
    model_config = {"extra": "forbid"}

    key: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=200)


@router.get("/schema", response_model=None)
async def get_schema(request: Request) -> JSONResponse:
    """可草案键清单（前端选择器；无秘密，仅键/类型/标签）。"""
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    return JSONResponse(
        {
            "keys": [
                {"key": key, "type": spec["type"], "label": spec["label"]}
                for key, spec in DRAFTABLE_KEYS.items()
            ]
        },
        headers=_NO_STORE,
    )


@router.post("", response_model=None)
async def post_draft(payload: DraftBody, request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    try:
        result = await create_draft(
            request.app.state.control_db, key=payload.key, value=payload.value, by=principal["user_id"]
        )
    except ConfigDraftInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_config_draft", "message": str(exc)}},
            headers=_NO_STORE,
        )
    return JSONResponse(result, headers=_NO_STORE)


@router.get("", response_model=None)
async def get_drafts(request: Request, limit: int = 20) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    return JSONResponse(
        {"items": await list_drafts(request.app.state.control_db, limit)},
        headers=_NO_STORE,
    )


@router.get("/{draft_id}", response_model=None)
async def get_draft_detail(draft_id: str, request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    draft = await get_draft(request.app.state.control_db, draft_id)
    if draft is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "config_draft_not_found", "message": "草案不存在。"}},
            headers=_NO_STORE,
        )
    return JSONResponse(draft, headers=_NO_STORE)


@router.post("/{draft_id}/apply", response_model=None)
async def post_apply(draft_id: str, request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    denial = await require_step_up(request, principal, STEP_UP_OPERATION, principal["user_id"])
    if denial is not None:
        return denial
    try:
        result = await apply_draft(
            request.app.state.control_db, draft_id=draft_id, by=principal["user_id"]
        )
    except ConfigDraftNotFound:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "config_draft_not_found", "message": "草案不存在。"}},
            headers=_NO_STORE,
        )
    except ConfigDraftStateInvalid:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "config_draft_state", "message": "草案已收尾，不能应用。"}},
            headers=_NO_STORE,
        )
    from lumirss.accounts_store import AccountsStore

    await AccountsStore(request.app.state.control_db).audit(
        actor=principal["user_id"],
        action="config_draft_applied",
        object_type="config_draft",
        object_id=draft_id,
        detail=f"{result['key']}={result['value']}",
    )
    return JSONResponse(result, headers=_NO_STORE)


@router.post("/{draft_id}/discard", response_model=None)
async def post_discard(draft_id: str, request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    try:
        result = await discard_draft(
            request.app.state.control_db, draft_id=draft_id, by=principal["user_id"]
        )
    except ConfigDraftNotFound:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "config_draft_not_found", "message": "草案不存在。"}},
            headers=_NO_STORE,
        )
    except ConfigDraftStateInvalid:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "config_draft_state", "message": "草案已收尾，不能废弃。"}},
            headers=_NO_STORE,
        )
    return JSONResponse(result, headers=_NO_STORE)
