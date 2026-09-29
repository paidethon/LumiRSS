"""NEW-315 书签链接批量替换路由 — 预览 / 执行 / 台账 / 撤销本批。

- POST   /api/v1/library/bookmarks/link-replace/preview {fromDomain,toDomain} → 200 预览（零写入）
- POST   /api/v1/library/bookmarks/link-replace/apply   {fromDomain,toDomain} → 200 执行结果
- GET    /api/v1/library/bookmarks/link-replace/batches → 批次台账
- POST   /api/v1/library/bookmarks/link-replace/batches/{id}/undo → 撤销本批（仅一次）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new315_link_replace import (
    LinkReplaceInvalid,
    LinkReplaceStore,
    ReplaceBatchNotFound,
    UndoneBatch,
)

router = APIRouter()


class DomainMapBody(BaseModel):
    model_config = {"extra": "forbid"}

    fromDomain: str = Field(min_length=1, max_length=255)
    toDomain: str = Field(min_length=1, max_length=255)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> LinkReplaceStore:
    return LinkReplaceStore(request.app.state.db)


@router.post("/api/v1/library/bookmarks/link-replace/preview")
async def preview_link_replace(payload: DomainMapBody, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).preview(payload.fromDomain, payload.toDomain)
        )
    except LinkReplaceInvalid as exc:
        return _error(400, "invalid_domain_mapping", str(exc))


@router.post("/api/v1/library/bookmarks/link-replace/apply")
async def apply_link_replace(payload: DomainMapBody, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).apply(payload.fromDomain, payload.toDomain)
        )
    except LinkReplaceInvalid as exc:
        return _error(400, "invalid_domain_mapping", str(exc))


@router.get("/api/v1/library/bookmarks/link-replace/batches")
async def list_replace_batches(request: Request) -> Response:
    return JSONResponse({"batches": await _store(request).list_batches()})


@router.post("/api/v1/library/bookmarks/link-replace/batches/{batch_id}/undo")
async def undo_replace_batch(batch_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).undo(batch_id))
    except ReplaceBatchNotFound:
        return _error(404, "replace_batch_not_found", "替换批次不存在。")
    except UndoneBatch:
        return _error(409, "replace_batch_undone", "该批次已撤销，不能重复撤销。")
    except LinkReplaceInvalid as exc:
        return _error(400, "invalid_replace_batch", str(exc))
