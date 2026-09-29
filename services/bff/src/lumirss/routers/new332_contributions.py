"""NEW-332 共享内容审批队列路由。

- POST /api/v1/spaces/{sid}/contributions                投稿（开审批→pending）
- GET  /api/v1/spaces/{sid}/contributions?scope=visible|mine
- GET  /api/v1/spaces/{sid}/contributions/{id}           单条（可见性与列表同口径）
- POST /api/v1/spaces/{sid}/contributions/{id}/review    管理者批准/退回（退回须写原因）

不变量：pending 只对投稿者本人与管理者可见；未审批内容不公开给全体。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.accounts_store import AccountsStore
from lumirss.new332_contributions import ContributionNotFound, ContributionStore
from lumirss.space_core import (
    SpaceArchived,
    SpaceForbidden,
    SpaceInvalid,
    SpaceNotFound,
    SpaceStore,
)
from lumirss.user_scope import require_user_id

router = APIRouter()


class ContributionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    entryRef: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=120)
    excerpt: str = Field(default="", max_length=4000)
    note: str | None = Field(default=None, max_length=1000)
    sectionId: str | None = Field(default=None, max_length=64)


class ContributionReview(BaseModel):
    model_config = {"extra": "forbid"}

    approve: bool
    reviewNote: str | None = Field(default=None, max_length=1000)


def _store(request: Request) -> ContributionStore:
    return ContributionStore(
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
        return _error(403, "space_forbidden", "只有空间管理者能审批。")
    if isinstance(exc, ContributionNotFound):
        return _error(404, "contribution_not_found", "投稿不存在。")
    if isinstance(exc, SpaceInvalid):
        return _error(422, "invalid_space", str(exc))
    return None


@router.post("/api/v1/spaces/{space_id}/contributions", status_code=201)
async def submit_contribution(
    space_id: str, payload: ContributionCreate, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).submit(
            space_id,
            actor_user_id=user_id,
            actor_username=username,
            entry_ref=payload.entryRef,
            title=payload.title,
            excerpt=payload.excerpt,
            note=payload.note,
            section_id=payload.sectionId,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)


@router.get("/api/v1/spaces/{space_id}/contributions")
async def list_contributions(space_id: str, request: Request, scope: str = "visible") -> Response:
    user_id = require_user_id()
    if scope not in ("visible", "mine"):
        return _error(422, "invalid_space", "scope 只能是 visible / mine。")
    try:
        items = await _store(request).list_for_space(
            space_id, actor_user_id=user_id, scope=scope
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse({"items": items})


@router.get("/api/v1/spaces/{space_id}/contributions/{contribution_id}")
async def contribution_detail(
    space_id: str, contribution_id: str, request: Request
) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).get_visible(
            space_id, contribution_id, actor_user_id=user_id
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.post("/api/v1/spaces/{space_id}/contributions/{contribution_id}/review")
async def review_contribution(
    space_id: str, contribution_id: str, payload: ContributionReview, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).review(
            space_id,
            contribution_id,
            actor_user_id=user_id,
            actor_username=username,
            approve=payload.approve,
            review_note=payload.reviewNote,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)
