"""NEW-381 Zotero RDF 书目导入路由 — 预览 / 导入 / 记录清单。

- POST /api/v1/preservation/zotero/preview   raw RDF 文本 → 字段映射
  + 重复预览（零写入）
- POST /api/v1/preservation/zotero/import?includeDuplicates=  → 写入
  （重复默认跳过，台账计数）
- GET  /api/v1/preservation/records?format=zotero_rdf  → 本人书目清单
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from lumirss.new381_bib import BibInvalid, BibStore, parse_zotero_rdf
from lumirss.routers.preservation_gate import (
    MAX_PREVIEW_BYTES,
    error_response,
    no_store,
    read_limited_text,
    require_preservation_user,
)

router = APIRouter()


@router.post("/api/v1/preservation/zotero/preview")
async def preview_zotero(request: Request) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    body = await read_limited_text(request, MAX_PREVIEW_BYTES)
    if isinstance(body, Response):
        return body
    try:
        records = parse_zotero_rdf(body)
        return no_store(await BibStore(request.app.state.db).preview("zotero_rdf", records))
    except BibInvalid as exc:
        return error_response(400, "invalid_bib_file", str(exc))


@router.post("/api/v1/preservation/zotero/import", status_code=201)
async def import_zotero(
    request: Request,
    includeDuplicates: bool = False,
) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    body = await read_limited_text(request, MAX_PREVIEW_BYTES)
    if isinstance(body, Response):
        return body
    try:
        records = parse_zotero_rdf(body)
        return no_store(
            await BibStore(request.app.state.db).import_records(
                "zotero_rdf", records, include_duplicates=includeDuplicates
            ),
            201,
        )
    except BibInvalid as exc:
        return error_response(400, "invalid_bib_file", str(exc))


@router.get("/api/v1/preservation/records")
async def list_records(
    request: Request,
    format: Annotated[str | None, Query()] = None,
) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store(
        {"records": await BibStore(request.app.state.db).list_records(format)}
    )
