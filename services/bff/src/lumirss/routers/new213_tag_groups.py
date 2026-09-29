"""NEW-213 标签互斥组路由 —— 组 CRUD + 冲突预览 + 批量解决。

422 invalid_tag_group / 404 tag_group_not_found / 409 tag_group_conflict。
互斥约束不在 attach 时硬卡（打标签不受阻），而是「冲突预览 + 用户逐条
选保留值」——批量修改的每一步都由用户确认。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new213_tag_groups import (
    TagGroupConflictRequest,
    TagGroupInvalid,
    TagGroupNotFound,
    TagGroupStore,
)

router = APIRouter()


class TagGroupCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=64)
    members: list[str] = Field(min_length=2, max_length=30)


class TagGroupResolveItem(BaseModel):
    model_config = {"extra": "forbid"}

    ref: str = Field(min_length=1, max_length=200)
    keep: str = Field(min_length=1, max_length=50)


class TagGroupResolveRequest(BaseModel):
    model_config = {"extra": "forbid"}

    resolutions: list[TagGroupResolveItem] = Field(min_length=1, max_length=200)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> TagGroupStore:
    return TagGroupStore(request.app.state.db)


@router.post("/api/v1/tag-groups", status_code=201)
async def create_tag_group(payload: TagGroupCreate, request: Request) -> Response:
    try:
        result = await _store(request).create(payload.name, payload.members)
    except TagGroupInvalid as exc:
        return _error(422, "invalid_tag_group", str(exc))
    return JSONResponse(status_code=201, content=result)


@router.get("/api/v1/tag-groups")
async def list_tag_groups(request: Request) -> JSONResponse:
    return JSONResponse({"items": await _store(request).list_groups()})


@router.delete("/api/v1/tag-groups/{group_id}", status_code=204)
async def delete_tag_group(group_id: int, request: Request) -> Response:
    deleted = await _store(request).delete(group_id)
    if not deleted:
        return _error(404, "tag_group_not_found", "互斥组不存在。")
    return Response(status_code=204)


@router.get("/api/v1/tag-groups/{group_id}/conflicts")
async def tag_group_conflicts(group_id: int, request: Request) -> Response:
    try:
        result = await _store(request).conflicts(group_id)
    except TagGroupNotFound:
        return _error(404, "tag_group_not_found", "互斥组不存在。")
    return JSONResponse(result)


@router.post("/api/v1/tag-groups/{group_id}/resolve")
async def tag_group_resolve(group_id: int, payload: TagGroupResolveRequest, request: Request) -> Response:
    try:
        result = await _store(request).resolve(
            group_id, [item.model_dump() for item in payload.resolutions]
        )
    except TagGroupInvalid as exc:
        return _error(422, "invalid_tag_group", str(exc))
    except TagGroupNotFound:
        return _error(404, "tag_group_not_found", "互斥组不存在。")
    except TagGroupConflictRequest as exc:
        return _error(409, "tag_group_conflict", str(exc))
    return JSONResponse(result)
