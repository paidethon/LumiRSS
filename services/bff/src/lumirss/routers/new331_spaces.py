"""NEW-331 共读空间基底路由 —— 空间创建/列表/详情 + 显式成员管理 + 栏目。

- POST   /api/v1/spaces                          创建空间（创建者成为管理者）
- GET    /api/v1/spaces                          我的空间（有效成员资格）
- GET    /api/v1/spaces/{space_id}               详情（含成员与栏目；仅有效成员）
- POST   /api/v1/spaces/{space_id}/members       管理者显式添加成员
- DELETE /api/v1/spaces/{space_id}/members/{mid} 管理者移除 / 成员自行退出
- POST   /api/v1/spaces/{space_id}/sections      管理者添加栏目
- PUT    /api/v1/spaces/{space_id}/settings      管理者改审批开关（NEW-332 面）

隐私：一切共享都从「管理者显式添加成员」开始；非成员一律 404（不泄
露存在性）；成员越权管理者动作 → 403。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.accounts_store import AccountsStore
from lumirss.space_core import (
    MemberExists,
    MemberNotFound,
    SpaceArchived,
    SpaceForbidden,
    SpaceInvalid,
    SpaceNotFound,
    SpaceStore,
)
from lumirss.user_scope import require_user_id

router = APIRouter()


class SpaceCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    requireApproval: bool = False
    discussionTemplates: list[str] | None = None


class MemberAdd(BaseModel):
    model_config = {"extra": "forbid"}

    username: str = Field(min_length=1, max_length=100)


class SectionAdd(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=60)


class SettingsUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    requireApproval: bool


def _spaces(request: Request) -> SpaceStore:
    return SpaceStore(request.app.state.control_db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


async def _username_of(request: Request, user_id: str) -> str:
    user = await AccountsStore(request.app.state.control_db).get_user(user_id)
    return str(user["username"]) if user else user_id


@router.post("/api/v1/spaces", status_code=201)
async def create_space(payload: SpaceCreate, request: Request) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _spaces(request).create(
            owner_user_id=user_id,
            owner_username=username,
            name=payload.name,
            description=payload.description,
            require_approval=payload.requireApproval,
            discussion_templates=payload.discussionTemplates,
        )
    except SpaceInvalid as exc:
        return _error(422, "invalid_space", str(exc))
    return JSONResponse(status_code=201, content=view)


@router.get("/api/v1/spaces")
async def list_spaces(request: Request) -> Response:
    user_id = require_user_id()
    views = await _spaces(request).list_for_user(user_id)
    return JSONResponse({"items": views})


@router.get("/api/v1/spaces/{space_id}")
async def space_detail(space_id: str, request: Request) -> Response:
    user_id = require_user_id()
    try:
        view = await _spaces(request).detail(space_id, user_id)
    except SpaceNotFound:
        return _error(404, "space_not_found", "空间不存在。")
    return JSONResponse(view)


@router.post("/api/v1/spaces/{space_id}/members", status_code=201)
async def add_member(space_id: str, payload: MemberAdd, request: Request) -> Response:
    actor_id = require_user_id()
    accounts = AccountsStore(request.app.state.control_db)
    member = await accounts.get_user_by_username(payload.username.strip())
    if member is None:
        return _error(422, "space_member_unknown", "该用户名不是本实例的成员。")
    member_id = str(member["id"])
    try:
        view = await _spaces(request).add_member(
            space_id,
            actor_user_id=actor_id,
            user_id=member_id,
            username=str(member["username"]),
        )
    except SpaceNotFound:
        return _error(404, "space_not_found", "空间不存在。")
    except SpaceArchived:
        return _error(409, "space_archived", "空间已归档（只读）。")
    except SpaceForbidden:
        return _error(403, "space_forbidden", "只有空间管理者能添加成员。")
    except MemberExists:
        return _error(409, "space_member_exists", "该成员已在空间内。")
    except SpaceInvalid as exc:
        return _error(422, "invalid_space", str(exc))
    return JSONResponse(status_code=201, content=view)


@router.delete("/api/v1/spaces/{space_id}/members/{member_id}", status_code=204)
async def remove_member(space_id: str, member_id: str, request: Request) -> Response:
    actor_id = require_user_id()
    try:
        await _spaces(request).remove_member(
            space_id, actor_user_id=actor_id, member_id=member_id
        )
    except SpaceNotFound:
        return _error(404, "space_not_found", "空间不存在。")
    except SpaceArchived:
        return _error(409, "space_archived", "空间已归档（只读）。")
    except SpaceForbidden:
        return _error(403, "space_forbidden", "管理者行不可移除。")
    except MemberNotFound:
        return _error(404, "space_member_not_found", "成员行不存在。")
    return Response(status_code=204)


@router.post("/api/v1/spaces/{space_id}/sections", status_code=201)
async def add_section(space_id: str, payload: SectionAdd, request: Request) -> Response:
    actor_id = require_user_id()
    try:
        view: dict[str, Any] = await _spaces(request).add_section(
            space_id, actor_user_id=actor_id, name=payload.name
        )
    except SpaceNotFound:
        return _error(404, "space_not_found", "空间不存在。")
    except SpaceArchived:
        return _error(409, "space_archived", "空间已归档（只读）。")
    except SpaceForbidden:
        return _error(403, "space_forbidden", "只有空间管理者能管理栏目。")
    except SpaceInvalid as exc:
        return _error(422, "invalid_space", str(exc))
    return JSONResponse(status_code=201, content=view)


@router.put("/api/v1/spaces/{space_id}/settings")
async def update_settings(space_id: str, payload: SettingsUpdate, request: Request) -> Response:
    actor_id = require_user_id()
    try:
        view = await _spaces(request).set_require_approval(
            space_id, actor_user_id=actor_id, require_approval=payload.requireApproval
        )
    except SpaceNotFound:
        return _error(404, "space_not_found", "空间不存在。")
    except SpaceArchived:
        return _error(409, "space_archived", "空间已归档（只读）。")
    except SpaceForbidden:
        return _error(403, "space_forbidden", "只有空间管理者能改设置。")
    except SpaceInvalid as exc:
        return _error(422, "invalid_space", str(exc))
    return JSONResponse(view)
