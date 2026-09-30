"""NEW-388 个人索引导出路由 — 目录导出（JSON）/ 台账。

- GET|POST /api/v1/preservation/index-export?format=  → 目录 JSON
  （只含目录、标签、来源与校验值，不附摘要/全文）
- GET /api/v1/preservation/index-export/exports       → 台账
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from lumirss.new381_bib import BibInvalid
from lumirss.new388_index_export import build_catalog, list_exports, persist_export
from lumirss.routers.preservation_gate import (
    error_response,
    no_store,
    require_preservation_user,
)

router = APIRouter()


async def _export_catalog(request: Request, source_format: str | None, download: bool) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    try:
        catalog = await build_catalog(request.app.state.db, source_format)
    except BibInvalid as exc:
        return error_response(400, "invalid_index_request", str(exc))
    export_id = await persist_export(request.app.state.db, catalog)
    if not download:
        return no_store({**catalog, "exportId": export_id})
    import json

    return Response(
        content=json.dumps(catalog, ensure_ascii=False, indent=1),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="lumi-index-{export_id}.json"',
            "X-Lumi-Catalog-Sha256": catalog["catalogSha256"],
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/v1/preservation/index-export")
async def export_index(
    request: Request,
    format: Annotated[str | None, Query()] = None,
    download: bool = False,
) -> Any:
    return await _export_catalog(request, format, download)


@router.post("/api/v1/preservation/index-export")
async def export_index_post(payload: dict[str, Any], request: Request) -> Any:
    fmt = payload.get("format")
    return await _export_catalog(
        request, str(fmt) if fmt else None, bool(payload.get("download"))
    )


@router.get("/api/v1/preservation/index-export/exports")
async def list_index_exports(request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store({"exports": await list_exports(request.app.state.db)})
