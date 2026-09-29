"""NEW-319 资料重新提取路由 — 发起 / 列表 / 应用新版本。

- POST /api/v1/library/clips/{uuid}/reextract → 200（同步完成：done/failed 行）
- GET  /api/v1/library/clips/{uuid}/reextract → 请求列表（状态 + 应用标记）
- POST /api/v1/library/clips/{uuid}/reextract/{request_id}/apply → 应用到修订槽
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from lumirss.new319_reextract import (
    ReextractAlreadyApplied,
    ReextractNotApplicable,
    ReextractNotFound,
    ReextractService,
    ReextractTargetNotFound,
)

router = APIRouter()


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _service(request: Request) -> ReextractService:
    return ReextractService(
        request.app.state.db,
        fetcher=getattr(request.app.state, "reextract_fetcher", None),
    )


@router.post("/api/v1/library/clips/{item_uuid}/reextract")
async def request_reextract(item_uuid: str, request: Request) -> Response:
    try:
        return JSONResponse(await _service(request).request(item_uuid))
    except ReextractTargetNotFound:
        return _error(404, "clip_not_found", "剪藏不存在。")


@router.get("/api/v1/library/clips/{item_uuid}/reextract")
async def list_reextractions(item_uuid: str, request: Request) -> Response:
    try:
        return JSONResponse(await _service(request).list_requests(item_uuid))
    except ReextractTargetNotFound:
        return _error(404, "clip_not_found", "剪藏不存在。")


@router.post("/api/v1/library/clips/{item_uuid}/reextract/{request_id}/apply")
async def apply_reextract(item_uuid: str, request_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _service(request).apply(item_uuid, request_id))
    except ReextractNotFound:
        return _error(404, "reextract_not_found", "重提取请求不存在。")
    except ReextractTargetNotFound:
        return _error(404, "clip_not_found", "剪藏不存在。")
    except ReextractNotApplicable:
        return _error(409, "reextract_not_done", "只有成功完成的新版本可以应用。")
    except ReextractAlreadyApplied:
        return _error(409, "reextract_applied", "该版本已应用过，不能重复应用。")
