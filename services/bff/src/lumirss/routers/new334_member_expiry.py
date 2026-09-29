"""NEW-334 空间成员到期管理路由。

- PUT  /api/v1/spaces/{sid}/members/{mid}/expiry   管理者设定/清除权限到期
- POST /api/v1/spaces/{sid}/members/sweep          管理者触发到期清扫（审计台账）
- GET  /api/v1/spaces/{sid}/member-expiry-log      台账（成员可读）

到期语义：与邀请 expires_at 同型（ISO 即失效）；到期只撤销空间权限
（访问 → 404），不删除其个人账户。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new334_member_expiry import MemberExpiryStore
from lumirss.space_core import (
    MemberNotFound,
    SpaceArchived,
    SpaceForbidden,
    SpaceInvalid,
    SpaceNotFound,
    SpaceStore,
)
from lumirss.user_scope import require_user_id

router = APIRouter()


class ExpirySet(BaseModel):
    model_config = {"extra": "forbid"}

    expiresAt: str | None = None


def _stores(request: Request) -> tuple[MemberExpiryStore, SpaceStore]:
    control = request.app.state.control_db
    spaces = SpaceStore(control)
    return MemberExpiryStore(control, spaces), spaces


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _map(exc: Exception) -> JSONResponse | None:
    if isinstance(exc, SpaceNotFound):
        return _error(404, "space_not_found", "空间不存在。")
    if isinstance(exc, SpaceArchived):
        return _error(409, "space_archived", "空间已归档（只读）。")
    if isinstance(exc, SpaceForbidden):
        return _error(403, "space_forbidden", "只有空间管理者能管理到期。")
    if isinstance(exc, MemberNotFound):
        return _error(404, "space_member_not_found", "成员行不存在。")
    if isinstance(exc, SpaceInvalid):
        return _error(422, "invalid_space", str(exc))
    return None


@router.put("/api/v1/spaces/{space_id}/members/{member_id}/expiry")
async def set_member_expiry(
    space_id: str, member_id: str, payload: ExpirySet, request: Request
) -> Response:
    actor_id = require_user_id()
    expiry_store, _spaces = _stores(request)
    try:
        view = await expiry_store.set_expiry(
            space_id,
            member_id,
            actor_user_id=actor_id,
            expires_at=payload.expiresAt,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.post("/api/v1/spaces/{space_id}/members/sweep")
async def sweep_expired(space_id: str, request: Request) -> Response:
    actor_id = require_user_id()
    expiry_store, _spaces = _stores(request)
    try:
        result = await expiry_store.sweep(space_id, actor_user_id=actor_id)
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(result)


@router.get("/api/v1/spaces/{space_id}/member-expiry-log")
async def expiry_log(space_id: str, request: Request) -> Response:
    user_id = require_user_id()
    expiry_store, _spaces = _stores(request)
    try:
        items = await expiry_store.list_log(space_id, actor_user_id=user_id)
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse({"items": items})
