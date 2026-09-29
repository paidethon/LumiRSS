"""NEW-302 API 分页试抓台路由。

- POST /api/v1/api-sources/{uuid}/pagination-probe {maxPages?≤5}
- GET  /api/v1/api-sources/{uuid}/pagination-probe   最近一次试抓快照
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.api_sources import ApiSourceNotFound
from lumirss.new302_pagination_probe import (
    PaginationProbeInvalid,
    PaginationProbeStore,
    run_probe,
)

router = APIRouter()


class PaginationProbeBody(BaseModel):
    model_config = {"extra": "forbid"}

    maxPages: int | None = Field(default=None, ge=1, le=5)


def _stores(request: Request):
    from lumirss.api_source_store import ApiSourceStore

    return (
        ApiSourceStore(request.app.state.db),
        PaginationProbeStore(request.app.state.db),
    )


@router.post("/api/v1/api-sources/{source_uuid}/pagination-probe")
async def start_pagination_probe(
    source_uuid: str, payload: PaginationProbeBody | None = None, request: Request = None
) -> Response:
    source_store, probe_store = _stores(request)
    record = await source_store.get(source_uuid)
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    try:
        max_pages = (
            payload.maxPages
            if payload is not None and payload.maxPages is not None
            else None
        )
        from lumirss.new302_pagination_probe import clean_probe_max_pages

        max_pages = clean_probe_max_pages(max_pages)
    except PaginationProbeInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_probe_payload", "message": str(exc)}},
        )
    result = await run_probe(
        request.app.state.http_client,
        record.endpoint,
        record.pagination,
        record.items_expr,
        max_pages=max_pages,
    )
    saved = await probe_store.save_result(source_uuid, result)
    return JSONResponse(saved)


@router.get("/api/v1/api-sources/{source_uuid}/pagination-probe")
async def get_pagination_probe(source_uuid: str, request: Request) -> Response:
    source_store, probe_store = _stores(request)
    if await source_store.get(source_uuid) is None:
        raise ApiSourceNotFound(source_uuid)
    result = await probe_store.last_result(source_uuid)
    if result is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "probe_not_found", "message": "尚未试抓过该来源。"}},
        )
    return JSONResponse(result)
