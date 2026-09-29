"""NEW-247 原文变动关注路由 — 关注 / 查询 / 检测 / 差异入口 / 取消关注。

- POST   /api/v1/entries/{entry_ref}/content-watch          关注（基线正文；重复 → 409）；
- GET    /api/v1/entries/{entry_ref}/content-watch          关注状态；
- DELETE /api/v1/entries/{entry_ref}/content-watch          取消关注（204）；
- POST   /api/v1/entries/{entry_ref}/content-watch/check     提交当前正文做显式哈希比对；
- GET    /api/v1/entries/{entry_ref}/content-watch/diff      差异入口（仅 changed 后可用，
       watching 时 → 409 content_watch_not_changed——还没有变化可差异）。

负载非法 → 422 content_watch_invalid；没有关注 → 404 content_watch_not_found。
per-user 库天然隔离。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new247_content_watch import (
    ContentWatchStore,
    WatchConflict,
    WatchInvalid,
    WatchNotChanged,
    WatchNotFound,
)

router = APIRouter()


class WatchCreate(BaseModel):
    model_config = {"extra": "forbid"}

    baselineText: str = Field(min_length=1, max_length=200_000)


class WatchCheck(BaseModel):
    model_config = {"extra": "forbid"}

    currentText: str = Field(min_length=1, max_length=200_000)


def _store(request: Request) -> ContentWatchStore:
    return ContentWatchStore(request.app.state.db)


def _error(status: int, kind: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"type": kind, "message": message}})


@router.post("/api/v1/entries/{entry_ref}/content-watch", status_code=201)
async def create_content_watch(entry_ref: str, payload: WatchCreate, request: Request) -> Response:
    try:
        item = await _store(request).watch(entry_ref, payload.baselineText)
    except WatchInvalid as exc:
        return _error(422, "content_watch_invalid", str(exc))
    except WatchConflict:
        return _error(409, "content_watch_conflict", "这篇文章已在关注中；先取消旧关注再重新关注。")
    return JSONResponse(status_code=201, content=item)


@router.get("/api/v1/entries/{entry_ref}/content-watch")
async def get_content_watch(entry_ref: str, request: Request) -> Response:
    try:
        item = await _store(request).get_watch(entry_ref)
    except WatchNotFound:
        return _error(404, "content_watch_not_found", "这篇文章还没有关注记录。")
    return JSONResponse(item)


@router.delete("/api/v1/entries/{entry_ref}/content-watch", status_code=204)
async def delete_content_watch(entry_ref: str, request: Request) -> Response:
    await _store(request).unwatch(entry_ref)
    return Response(status_code=204)


@router.post("/api/v1/entries/{entry_ref}/content-watch/check")
async def check_content_watch(entry_ref: str, payload: WatchCheck, request: Request) -> Response:
    try:
        item = await _store(request).check(entry_ref, payload.currentText)
    except WatchInvalid as exc:
        return _error(422, "content_watch_invalid", str(exc))
    except WatchNotFound:
        return _error(404, "content_watch_not_found", "这篇文章还没有关注记录。")
    return JSONResponse(item)


@router.get("/api/v1/entries/{entry_ref}/content-watch/diff")
async def get_content_watch_diff(entry_ref: str, request: Request) -> Response:
    try:
        item = await _store(request).diff(entry_ref)
    except WatchNotFound:
        return _error(404, "content_watch_not_found", "这篇文章还没有关注记录。")
    except WatchNotChanged:
        return _error(409, "content_watch_not_changed", "尚未检测到变化，没有差异可展示。")
    return JSONResponse(item)
