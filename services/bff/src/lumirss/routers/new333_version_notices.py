"""NEW-333 共读内容版本通知路由。

- POST /api/v1/spaces/{sid}/version-notices              显式报告新版本（通知讨论参与者）
- GET  /api/v1/spaces/{sid}/version-notices?scope=all|pending
- POST /api/v1/spaces/{sid}/version-notices/{id}/ack     参与者标记「已重新核对」

诚实边界：新版本正文不跨用户库复制；通知只携带 ref/版本标签/报告人摘要。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.accounts_store import AccountsStore
from lumirss.new333_version_notices import VersionNoticeNotFound, VersionNoticeStore
from lumirss.space_core import (
    SpaceArchived,
    SpaceForbidden,
    SpaceInvalid,
    SpaceNotFound,
    SpaceStore,
)
from lumirss.user_scope import require_user_id

router = APIRouter()


class VersionNoticeCreate(BaseModel):
    model_config = {"extra": "forbid"}

    entryRef: str = Field(min_length=1, max_length=200)
    versionLabel: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=1000)


def _store(request: Request) -> VersionNoticeStore:
    return VersionNoticeStore(
        request.app.state.control_db, SpaceStore(request.app.state.control_db)
    )


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


async def _username_of(request: Request, user_id: str) -> str:
    user = await AccountsStore(request.app.state.control_db).get_user(user_id)
    return str(user["username"]) if user else user_id


def _map(exc: Exception) -> JSONResponse | None:
    if isinstance(exc, SpaceNotFound):
        return _error(404, "space_not_found", "空间不存在。")
    if isinstance(exc, SpaceArchived):
        return _error(409, "space_archived", "空间已归档（只读）。")
    if isinstance(exc, SpaceForbidden):
        return _error(403, "space_forbidden", "无权执行该动作。")
    if isinstance(exc, VersionNoticeNotFound):
        return _error(404, "version_notice_not_found", "版本通知不存在。")
    if isinstance(exc, SpaceInvalid):
        return _error(422, "invalid_space", str(exc))
    return None


@router.post("/api/v1/spaces/{space_id}/version-notices", status_code=201)
async def report_version(
    space_id: str, payload: VersionNoticeCreate, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).report(
            space_id,
            actor_user_id=user_id,
            actor_username=username,
            entry_ref=payload.entryRef,
            version_label=payload.versionLabel,
            summary=payload.summary,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)


@router.get("/api/v1/spaces/{space_id}/version-notices")
async def list_version_notices(space_id: str, request: Request, scope: str = "all") -> Response:
    user_id = require_user_id()
    if scope not in ("all", "pending"):
        return _error(422, "invalid_space", "scope 只能是 all / pending。")
    try:
        items = await _store(request).list_for_space(
            space_id, actor_user_id=user_id, scope=scope
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse({"items": items})


@router.post("/api/v1/spaces/{space_id}/version-notices/{notice_id}/ack")
async def acknowledge_notice(space_id: str, notice_id: str, request: Request) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).acknowledge(
            space_id, notice_id, actor_user_id=user_id
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)
