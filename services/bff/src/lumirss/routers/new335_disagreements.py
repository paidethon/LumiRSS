"""NEW-335 共读分歧记录路由。

- POST /api/v1/spaces/{sid}/disagreements                     创建分歧记录
- GET  /api/v1/spaces/{sid}/disagreements                     列表
- GET  /api/v1/spaces/{sid}/disagreements/{id}                详情（并列立场 + 证据）
- PUT  /api/v1/spaces/{sid}/disagreements/{id}/positions/my   保存/改写自己的结论（每人一条）
- POST /api/v1/spaces/{sid}/disagreements/{id}/evidence       补充证据
- POST /api/v1/spaces/{sid}/disagreements/{id}/close          可选闭合（发起者/管理者）

不强制统一结论：无「合并结论」端点，立场永远并列保存。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.accounts_store import AccountsStore
from lumirss.new335_disagreements import DisagreementNotFound, DisagreementStore
from lumirss.space_core import (
    SpaceArchived,
    SpaceForbidden,
    SpaceInvalid,
    SpaceNotFound,
    SpaceStore,
)
from lumirss.user_scope import require_user_id

router = APIRouter()


class DisagreementCreate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(min_length=1, max_length=120)
    entryRef: str | None = Field(default=None, max_length=200)


class PositionUpsert(BaseModel):
    model_config = {"extra": "forbid"}

    conclusion: str = Field(min_length=1, max_length=4000)
    citations: list[dict[str, str]] | None = None


class EvidenceAdd(BaseModel):
    model_config = {"extra": "forbid"}

    note: str = Field(min_length=1, max_length=1000)
    ref: str | None = Field(default=None, max_length=200)
    positionId: str | None = Field(default=None, max_length=64)


class CloseSet(BaseModel):
    model_config = {"extra": "forbid"}

    closed: bool


def _store(request: Request) -> DisagreementStore:
    return DisagreementStore(
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
        return _error(403, "space_forbidden", "只有发起者或管理者能闭合。")
    if isinstance(exc, DisagreementNotFound):
        return _error(404, "disagreement_not_found", "分歧记录不存在。")
    if isinstance(exc, SpaceInvalid):
        return _error(422, "invalid_space", str(exc))
    return None


@router.post("/api/v1/spaces/{space_id}/disagreements", status_code=201)
async def create_disagreement(
    space_id: str, payload: DisagreementCreate, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).create(
            space_id,
            actor_user_id=user_id,
            actor_username=username,
            title=payload.title,
            entry_ref=payload.entryRef,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)


@router.get("/api/v1/spaces/{space_id}/disagreements")
async def list_disagreements(space_id: str, request: Request) -> Response:
    user_id = require_user_id()
    try:
        items = await _store(request).list_for_space(space_id, actor_user_id=user_id)
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse({"items": items})


@router.get("/api/v1/spaces/{space_id}/disagreements/{disagreement_id}")
async def disagreement_detail(
    space_id: str, disagreement_id: str, request: Request
) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).get(
            space_id, disagreement_id, actor_user_id=user_id
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.put("/api/v1/spaces/{space_id}/disagreements/{disagreement_id}/positions/my")
async def upsert_position(
    space_id: str, disagreement_id: str, payload: PositionUpsert, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).upsert_position(
            space_id,
            disagreement_id,
            actor_user_id=user_id,
            actor_username=username,
            conclusion=payload.conclusion,
            citations=payload.citations,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.post("/api/v1/spaces/{space_id}/disagreements/{disagreement_id}/evidence", status_code=201)
async def add_evidence(
    space_id: str, disagreement_id: str, payload: EvidenceAdd, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).add_evidence(
            space_id,
            disagreement_id,
            actor_user_id=user_id,
            actor_username=username,
            note=payload.note,
            ref=payload.ref,
            position_id=payload.positionId,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)


@router.post("/api/v1/spaces/{space_id}/disagreements/{disagreement_id}/close")
async def close_disagreement(
    space_id: str, disagreement_id: str, payload: CloseSet, request: Request
) -> Response:
    user_id = require_user_id()
    try:
        view = await _store(request).close(
            space_id, disagreement_id, actor_user_id=user_id, closed=payload.closed
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)
