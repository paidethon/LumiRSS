"""NEW-340 空间归档流程路由。

- GET  /api/v1/spaces/{sid}/archive/preview        归档前任务盘点（零写入；管理者）
- POST /api/v1/spaces/{sid}/archive                归档（有未完成任务须显式 force）
- POST /api/v1/spaces/{sid}/restore                恢复（keepMemberIds 逐成员重新确认）
- GET  /api/v1/spaces/{sid}/archive-log            归档/恢复台账（成员可读）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new340_space_archive import (
    ArchiveBlocked,
    RestoreInvalid,
    SpaceArchiveStore,
)
from lumirss.space_core import SpaceForbidden, SpaceNotFound, SpaceStore
from lumirss.user_scope import require_user_id

router = APIRouter()


class ArchiveSet(BaseModel):
    model_config = {"extra": "forbid"}

    force: bool = False


class RestoreSet(BaseModel):
    model_config = {"extra": "forbid"}

    keepMemberIds: list[str] = Field(default_factory=list)


def _store(request: Request) -> SpaceArchiveStore:
    return SpaceArchiveStore(
        request.app.state.control_db, SpaceStore(request.app.state.control_db)
    )


def _error(status: int, error_type: str, message: str, extra: dict | None = None) -> JSONResponse:
    content: dict = {"error": {"type": error_type, "message": message}}
    if extra:
        content["error"].update(extra)
    return JSONResponse(status_code=status, content=content)


def _map(exc: Exception) -> JSONResponse | None:
    if isinstance(exc, SpaceNotFound):
        return _error(404, "space_not_found", "空间不存在。")
    if isinstance(exc, SpaceForbidden):
        return _error(403, "space_forbidden", "只有空间管理者能归档/恢复。")
    if isinstance(exc, ArchiveBlocked):
        return _error(
            409,
            "archive_blocked",
            str(exc),
            extra={"openTasks": exc.tasks, "openTaskCount": len(exc.tasks)},
        )
    if isinstance(exc, RestoreInvalid):
        return _error(422, "restore_invalid", str(exc))
    return None


@router.get("/api/v1/spaces/{space_id}/archive/preview")
async def archive_preview(space_id: str, request: Request) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).preview(space_id, actor_user_id=user_id)
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.post("/api/v1/spaces/{space_id}/archive")
async def archive_space(space_id: str, payload: ArchiveSet, request: Request) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).archive(
            space_id, actor_user_id=user_id, force=payload.force
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.post("/api/v1/spaces/{space_id}/restore")
async def restore_space(space_id: str, payload: RestoreSet, request: Request) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).restore(
            space_id, actor_user_id=user_id, keep_member_ids=payload.keepMemberIds
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.get("/api/v1/spaces/{space_id}/archive-log")
async def archive_log(space_id: str, request: Request) -> Response:
    user_id = require_user_id()
    try:
        items = await _store(request).history(space_id, actor_user_id=user_id)
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse({"items": items})
