"""NEW-339 共读模板路由。

- POST /api/v1/spaces/{sid}/template            从空间生成模板（管理者；不含成员与内容）
- GET  /api/v1/space-templates                  模板列表（构造上无成员/内容）
- GET  /api/v1/space-templates/{id}/preview     创建新空间预览（零写入）
- POST /api/v1/space-templates/{id}/create-space 应用模板创建新空间
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.accounts_store import AccountsStore
from lumirss.new339_space_templates import (
    SpaceTemplateNotFound,
    SpaceTemplateStore,
    TemplateExists,
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


class TemplateCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    discussionTemplates: list[str] | None = None


class SpaceFromTemplate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


def _store(request: Request) -> SpaceTemplateStore:
    return SpaceTemplateStore(
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
        return _error(403, "space_forbidden", "只有空间管理者能生成模板。")
    if isinstance(exc, SpaceTemplateNotFound):
        return _error(404, "template_not_found", "模板不存在。")
    if isinstance(exc, TemplateExists):
        return _error(409, "template_exists", "同名模板已存在。")
    if isinstance(exc, SpaceInvalid):
        return _error(422, "invalid_space", str(exc))
    return None


@router.post("/api/v1/spaces/{space_id}/template", status_code=201)
async def create_template(
    space_id: str, payload: TemplateCreate, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).create_from_space(
            space_id,
            actor_user_id=user_id,
            actor_username=username,
            name=payload.name,
            description=payload.description,
            discussion_templates=payload.discussionTemplates,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)


@router.get("/api/v1/space-templates")
async def list_templates(request: Request) -> Response:
    require_user_id()
    items = await _store(request).list_templates()
    return JSONResponse({"items": items})


@router.get("/api/v1/space-templates/{template_id}/preview")
async def preview_template(template_id: str, request: Request) -> Response:
    require_user_id()
    try:
        view = await _store(request).preview(template_id, actor_user_id=require_user_id())
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(view)


@router.post("/api/v1/space-templates/{template_id}/create-space", status_code=201)
async def create_space_from_template(
    template_id: str, payload: SpaceFromTemplate, request: Request
) -> Response:
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        view = await _store(request).create_space_from_template(
            template_id,
            actor_user_id=user_id,
            actor_username=username,
            name=payload.name,
            description=payload.description,
        )
    except Exception as exc:
        if mapped := _map(exc):
            return mapped
        raise
    return JSONResponse(status_code=201, content=view)
