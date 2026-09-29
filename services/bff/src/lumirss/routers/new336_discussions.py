"""NEW-336 讨论待答与已解答路由。

- POST /api/v1/spaces/{sid}/discussions                            发起问题（创建即待答）
- GET  /api/v1/spaces/{sid}/discussions?status=open|resolved       列表
- GET  /api/v1/spaces/{sid}/discussions/{id}                       详情（完整讨论）
- POST /api/v1/spaces/{sid}/discussions/{id}/replies               回复
- POST /api/v1/spaces/{sid}/discussions/{id}/replies/{rid}/helpful 发起者选中「有用」
- POST /api/v1/spaces/{sid}/discussions/{id}/resolve               发起者标记解决 / 重新打开
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.accounts_store import AccountsStore
from lumirss.new336_discussions import (
    DiscussionNotFound,
    DiscussionStore,
    ReplyNotFound,
)
from lumirss.space_core import (
    SpaceArchived,
    SpaceForbidden,
    SpaceInvalid,
    SpaceNotFound,
    SpaceStore,
)
from lumirss.user_scope import require_user_id

router = APIRouter()


class DiscussionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=2000)
    entryRef: str | None = Field(default=None, max_length=200)


class ReplyCreate(BaseModel):
    model_config = {"extra": "forbid"}

    body: str = Field(min_length=1, max_length=2000)


class HelpfulSet(BaseModel):
    model_config = {"extra": "forbid"}

    helpful: bool


class ResolveSet(BaseModel):
    model_config = {"extra": "forbid"}

    replyId: str | None = Field(default=None, max_length=64)


def _store(request: Request) -> DiscussionStore:
    return DiscussionStore(
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
    if isinstance(exc, DiscussionNotFound):
        return _error(404, "discussion_not_found", "讨论不存在。")
    if isinstance(exc, ReplyNotFound):
        return _error(404, "reply_not_found", "回复不存在。")
    if isinstance(exc, SpaceInvalid):
        return _error(422, "invalid_space", str(exc))
    return None


@router.post("/api/v1/spaces/{space_id}/discussions", status_code=201)
async def ask_discussion(space_id: str, payload: DiscussionCreate, request: Request) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).ask(
            space_id,
            actor_user_id=user_id,
            actor_username=username,
            title=payload.title,
            question=payload.question,
            entry_ref=payload.entryRef,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)


@router.get("/api/v1/spaces/{space_id}/discussions")
async def list_discussions(space_id: str, request: Request, status: str | None = None) -> Response:
    user_id = require_user_id()
    try:
        items = await _store(request).list_for_space(
            space_id, actor_user_id=user_id, status=status
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse({"items": items})


@router.get("/api/v1/spaces/{space_id}/discussions/{discussion_id}")
async def discussion_detail(space_id: str, discussion_id: str, request: Request) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).get(space_id, discussion_id, actor_user_id=user_id)
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.post("/api/v1/spaces/{space_id}/discussions/{discussion_id}/replies", status_code=201)
async def reply_discussion(
    space_id: str, discussion_id: str, payload: ReplyCreate, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view: dict[str, Any] = await _store(request).reply(
            space_id,
            discussion_id,
            actor_user_id=user_id,
            actor_username=username,
            body=payload.body,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)


@router.post(
    "/api/v1/spaces/{space_id}/discussions/{discussion_id}/replies/{reply_id}/helpful"
)
async def set_helpful(
    space_id: str, discussion_id: str, reply_id: str, payload: HelpfulSet, request: Request
) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).set_helpful(
            space_id,
            discussion_id,
            reply_id,
            actor_user_id=user_id,
            helpful=payload.helpful,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.post("/api/v1/spaces/{space_id}/discussions/{discussion_id}/resolve")
async def resolve_discussion(
    space_id: str, discussion_id: str, payload: ResolveSet, request: Request
) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).resolve(
            space_id, discussion_id, actor_user_id=user_id, reply_id=payload.replyId
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)
