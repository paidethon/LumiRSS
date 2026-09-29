"""NEW-311 浏览器书签目录导入路由 — 预览 / 确认形成集合 / 台账查询。

- POST /api/v1/library/bookmarks/import/preview   raw Netscape HTML → 200 预览（零写入）
- POST /api/v1/library/bookmarks/import/sets      raw HTML + ?folder=&includeDuplicates= → 201 集合
- GET  /api/v1/library/bookmarks/import/sets      → 导入集合台账（最近 100）
- GET  /api/v1/library/bookmarks/import/sets/{id} → 集合明细（逐条状态）
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from lumirss.new311_bookmark_import import (
    BookmarkImportSetStore,
    ImportPreviewInvalid,
)
from lumirss.routers.library import _MAX_IMPORT_BYTES

router = APIRouter()

_EMPTY_FOLDERS: list[str] = []


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


async def _read_body(request: Request) -> str | JSONResponse:
    """10MiB 上限内读取原始 Netscape HTML（与既有导入同口径）。"""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_IMPORT_BYTES:
            return _error(400, "invalid_import_file", "导入文件超过 10MiB 上限。")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return _error(400, "invalid_import_file", "导入文件不是有效的 UTF-8 文本。")


def _store(request: Request) -> BookmarkImportSetStore:
    return BookmarkImportSetStore(request.app.state.db)


@router.post("/api/v1/library/bookmarks/import/preview")
async def preview_import(request: Request) -> Response:
    body = await _read_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        return JSONResponse(await _store(request).preview(body))
    except ImportPreviewInvalid as exc:
        return _error(400, "invalid_import_file", str(exc))


@router.post("/api/v1/library/bookmarks/import/sets", status_code=201)
async def confirm_import(
    request: Request,
    folder: Annotated[list[str], Query()] = _EMPTY_FOLDERS,
    includeDuplicates: bool = False,
    sourceName: str = "",
) -> Response:
    body = await _read_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        result = await _store(request).confirm(
            body,
            folders=[f for f in folder if f],
            include_duplicates=includeDuplicates,
            source_name=sourceName[:200],
        )
    except ImportPreviewInvalid as exc:
        return _error(400, "invalid_import_file", str(exc))
    return JSONResponse(result, status_code=201)


@router.get("/api/v1/library/bookmarks/import/sets")
async def list_import_sets(request: Request) -> Response:
    return JSONResponse({"sets": await _store(request).list_sets()})


@router.get("/api/v1/library/bookmarks/import/sets/{set_id}")
async def get_import_set(set_id: str, request: Request) -> Response:
    result = await _store(request).get_set(set_id)
    if result is None:
        return _error(404, "import_set_not_found", "导入集合不存在。")
    return JSONResponse(result)
