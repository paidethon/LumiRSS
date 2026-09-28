"""NEW-203 来源分流视图路由（视图 CRUD + 读取侧条目查询）。"""

from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new203_views import (
    ENTRIES_LIMIT_MAX,
    SourceViewExists,
    SourceViewInvalid,
    SourceViewNotFound,
    SourceViewStore,
    validate_view_input,
)

router = APIRouter()


def _store(request: Request) -> SourceViewStore:
    return SourceViewStore(request.app.state.db)


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_source_view", "message": message}},
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"type": "source_view_not_found", "message": "视图不存在。"}},
    )


class ViewCreate(BaseModel):
    """POST /api/v1/new203/views body。"""

    model_config = {"extra": "forbid"}

    feedUrl: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=60)
    field: str
    """title | content | author（op 固定 contains）。"""
    value: str = Field(min_length=1, max_length=120)


class ViewPatch(BaseModel):
    """PATCH /api/v1/new203/views/{id} body（局部更新）。"""

    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1, max_length=60)
    field: str | None = None
    value: str | None = Field(default=None, min_length=1, max_length=120)


class SourceView(BaseModel):
    id: str
    feedUrl: str
    name: str
    field: str
    value: str
    createdAt: str


class ViewList(BaseModel):
    items: list[SourceView]


class ViewEntry(BaseModel):
    entryRef: str
    title: str
    author: str
    publishedAt: str
    url: str


class ViewEntries(BaseModel):
    view: SourceView
    entries: list[ViewEntry]
    basis: str
    note: str


@router.post("/api/v1/new203/views", response_model=SourceView, status_code=201)
async def create_view(payload: ViewCreate, request: Request) -> Any:
    """创建个人分流视图（同 feed 同名 → 409）。"""
    try:
        parts = validate_view_input(
            feed_url=payload.feedUrl,
            name=payload.name,
            field=payload.field,
            value=payload.value,
        )
        return await _store(request).create(parts)
    except SourceViewInvalid as exc:
        return _invalid(str(exc))
    except SourceViewExists:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "source_view_exists",
                    "message": "该来源下已有同名视图。",
                }
            },
        )


@router.get("/api/v1/new203/views", response_model=ViewList)
async def list_views(request: Request, feedUrl: str | None = Query(default=None)) -> ViewList:
    """视图列表（可按来源过滤）。"""
    items = await _store(request).list_views(feed_url=feedUrl)
    return ViewList(items=[SourceView(**item) for item in items])


@router.patch("/api/v1/new203/views/{view_id}", response_model=SourceView)
async def patch_view(view_id: str, payload: ViewPatch, request: Request) -> Any:
    try:
        parts = validate_view_input(
            name=payload.name, field=payload.field, value=payload.value
        )
    except SourceViewInvalid as exc:
        return _invalid(str(exc))
    try:
        row = await _store(request).update(view_id, parts)
    except SourceViewNotFound:
        return _not_found()
    except SourceViewExists:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "source_view_exists",
                    "message": "该来源下已有同名视图。",
                }
            },
        )
    return SourceView(**row)


@router.delete("/api/v1/new203/views/{view_id}", status_code=204)
async def delete_view(view_id: str, request: Request) -> Response:
    deleted = await _store(request).delete(view_id)
    if not deleted:
        return _not_found()
    return Response(status_code=204)


@router.get("/api/v1/new203/views/{view_id}/entries", response_model=ViewEntries)
async def get_view_entries(
    view_id: str,
    request: Request,
    limit: int = Query(default=ENTRIES_LIMIT_MAX, ge=1, le=ENTRIES_LIMIT_MAX),
) -> Any:
    """视图条目（读取侧投影过滤；同一抓取任务/条目身份不变）。"""
    try:
        return ViewEntries(**await _store(request).view_entries(view_id, limit=limit))
    except SourceViewNotFound:
        return _not_found()
