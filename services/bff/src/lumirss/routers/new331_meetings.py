"""NEW-331 共读会议资料单路由。

- POST   /api/v1/spaces/{sid}/meetings                     创建会议资料单
- GET    /api/v1/spaces/{sid}/meetings                     列表（成员）
- GET    /api/v1/spaces/{sid}/meetings/{id}                详情（资料项 + 结论）
- POST   /api/v1/spaces/{sid}/meetings/{id}/items          显式添加资料项（快照）
- DELETE /api/v1/spaces/{sid}/meetings/{id}/items/{item}   移除自己添加的资料项
- POST   /api/v1/spaces/{sid}/meetings/{id}/close          结束会议（发起者/管理者）
- POST   /api/v1/spaces/{sid}/meetings/{id}/outcomes       结束后保存结论与出处
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.accounts_store import AccountsStore
from lumirss.new331_meetings import MeetingNotFound, MeetingStore
from lumirss.space_core import (
    SpaceArchived,
    SpaceForbidden,
    SpaceInvalid,
    SpaceNotFound,
    SpaceStore,
)
from lumirss.user_scope import require_user_id

router = APIRouter()


class MeetingCreate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(min_length=1, max_length=120)


class ItemAdd(BaseModel):
    model_config = {"extra": "forbid"}

    entryRef: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=120)
    excerpt: str = Field(default="", max_length=4000)
    question: str | None = Field(default=None, max_length=2000)


class OutcomeAdd(BaseModel):
    model_config = {"extra": "forbid"}

    summary: str = Field(min_length=1, max_length=4000)
    entryRef: str | None = Field(default=None, max_length=200)


def _store(request: Request) -> MeetingStore:
    return MeetingStore(request.app.state.control_db, SpaceStore(request.app.state.control_db))


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


async def _username_of(request: Request, user_id: str) -> str:
    user = await AccountsStore(request.app.state.control_db).get_user(user_id)
    return str(user["username"]) if user else user_id


def _map_space_errors(exc: Exception) -> JSONResponse | None:
    if isinstance(exc, SpaceNotFound):
        return _error(404, "space_not_found", "空间不存在。")
    if isinstance(exc, SpaceArchived):
        return _error(409, "space_archived", "空间已归档（只读）。")
    if isinstance(exc, SpaceForbidden):
        return _error(403, "space_forbidden", "无权执行该动作。")
    if isinstance(exc, MeetingNotFound):
        return _error(404, "meeting_not_found", "会议不存在。")
    if isinstance(exc, SpaceInvalid):
        return _error(422, "invalid_space", str(exc))
    return None


@router.post("/api/v1/spaces/{space_id}/meetings", status_code=201)
async def create_meeting(space_id: str, payload: MeetingCreate, request: Request) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).create(
            space_id, actor_user_id=user_id, actor_username=username, title=payload.title
        )
    except Exception as exc:
        if mapped := _map_space_errors(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)


@router.get("/api/v1/spaces/{space_id}/meetings")
async def list_meetings(space_id: str, request: Request) -> Response:
    user_id = require_user_id()
    try:
        items = await _store(request).list_for_space(space_id, actor_user_id=user_id)
    except Exception as exc:
        if mapped := _map_space_errors(exc):
            return mapped
        raise
    return JSONResponse({"items": items})


@router.get("/api/v1/spaces/{space_id}/meetings/{meeting_id}")
async def meeting_detail(space_id: str, meeting_id: str, request: Request) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).get(space_id, meeting_id, actor_user_id=user_id)
    except Exception as exc:
        if mapped := _map_space_errors(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.post("/api/v1/spaces/{space_id}/meetings/{meeting_id}/items", status_code=201)
async def add_meeting_item(
    space_id: str, meeting_id: str, payload: ItemAdd, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).add_item(
            space_id,
            meeting_id,
            actor_user_id=user_id,
            actor_username=username,
            entry_ref=payload.entryRef,
            title=payload.title,
            excerpt=payload.excerpt,
            question=payload.question,
        )
    except Exception as exc:
        if mapped := _map_space_errors(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)


@router.delete(
    "/api/v1/spaces/{space_id}/meetings/{meeting_id}/items/{item_id}", status_code=204
)
async def remove_meeting_item(
    space_id: str, meeting_id: str, item_id: str, request: Request
) -> Response:
    user_id = require_user_id()
    try:
        await _store(request).remove_item(
            space_id, meeting_id, item_id, actor_user_id=user_id
        )
    except Exception as exc:
        if mapped := _map_space_errors(exc):
            return mapped
        raise
    return Response(status_code=204)


@router.post("/api/v1/spaces/{space_id}/meetings/{meeting_id}/close")
async def close_meeting(space_id: str, meeting_id: str, request: Request) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).close(space_id, meeting_id, actor_user_id=user_id)
    except Exception as exc:
        if mapped := _map_space_errors(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.post("/api/v1/spaces/{space_id}/meetings/{meeting_id}/outcomes", status_code=201)
async def add_outcome(
    space_id: str, meeting_id: str, payload: OutcomeAdd, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).add_outcome(
            space_id,
            meeting_id,
            actor_user_id=user_id,
            actor_username=username,
            summary=payload.summary,
            entry_ref=payload.entryRef,
        )
    except Exception as exc:
        if mapped := _map_space_errors(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)
