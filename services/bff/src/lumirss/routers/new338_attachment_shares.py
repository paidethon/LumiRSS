"""NEW-338 共享附件访问清单路由。

- POST   /api/v1/spaces/{sid}/attachment-shares                所有者显式共享附件元数据
- GET    /api/v1/spaces/{sid}/attachment-shares                清单（成员可见；?includeRevoked=）
- DELETE /api/v1/spaces/{sid}/attachment-shares/{id}           管理者/所有者逐项撤销

边界：只承载元数据台账；附件字节留在所有者 per-user 库里，撤销授权
绝不删除所有者的私人文件。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.accounts_store import AccountsStore
from lumirss.new338_attachment_shares import (
    AttachmentShareNotFound,
    AttachmentShareStore,
)
from lumirss.space_core import SpaceArchived, SpaceInvalid, SpaceNotFound, SpaceStore
from lumirss.user_scope import require_user_id

router = APIRouter()


class AttachmentShareCreate(BaseModel):
    model_config = {"extra": "forbid"}

    attachmentRef: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    mimeType: str = Field(default="", max_length=120)
    sizeBytes: int | None = Field(default=None, ge=0)


def _store(request: Request) -> AttachmentShareStore:
    return AttachmentShareStore(
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
    if isinstance(exc, AttachmentShareNotFound):
        return _error(404, "attachment_share_not_found", "附件共享行不存在。")
    if isinstance(exc, SpaceInvalid):
        return _error(422, "invalid_space", str(exc))
    return None


@router.post("/api/v1/spaces/{space_id}/attachment-shares", status_code=201)
async def share_attachment(
    space_id: str, payload: AttachmentShareCreate, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).share(
            space_id,
            actor_user_id=user_id,
            actor_username=username,
            attachment_ref=payload.attachmentRef,
            name=payload.name,
            mime_type=payload.mimeType,
            size_bytes=payload.sizeBytes,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)


@router.get("/api/v1/spaces/{space_id}/attachment-shares")
async def list_attachment_shares(
    space_id: str, request: Request, includeRevoked: bool = False
) -> Response:
    user_id = require_user_id()
    try:
        items = await _store(request).list_for_space(
            space_id, actor_user_id=user_id, include_revoked=includeRevoked
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse({"items": items})


@router.delete(
    "/api/v1/spaces/{space_id}/attachment-shares/{share_id}", status_code=200
)
async def revoke_attachment_share(
    space_id: str, share_id: str, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).revoke(
            space_id, share_id, actor_user_id=user_id, actor_username=username
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)
