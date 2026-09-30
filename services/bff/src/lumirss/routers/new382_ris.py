"""NEW-382 RIS 引文导入与导出路由 — 预览 / 导入 / 导出（含往返校验）/
校验台账。

- POST /api/v1/preservation/ris/preview        raw RIS 文本 → 映射 +
  不支持字段预览（零写入）
- POST /api/v1/preservation/ris/import?includeDuplicates=  → 写入
- GET  /api/v1/preservation/ris/export?ids=…   → RIS 文件下载；导出
  即附带往返重解析校验（结论随台账落库，报告在响应头 X-Lumi-Roundtrip）
- GET  /api/v1/preservation/ris/exports        → 往返校验台账
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from lumirss.new381_bib import BibInvalid, BibStore
from lumirss.new382_ris import (
    RisExportStore,
    parse_ris,
    roundtrip_report,
    serialize_ris,
)
from lumirss.routers.preservation_gate import (
    MAX_PREVIEW_BYTES,
    error_response,
    no_store,
    read_limited_text,
    require_preservation_user,
)

router = APIRouter()


@router.post("/api/v1/preservation/ris/preview")
async def preview_ris(request: Request) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    body = await read_limited_text(request, MAX_PREVIEW_BYTES)
    if isinstance(body, Response):
        return body
    try:
        records = parse_ris(body)
        return no_store(await BibStore(request.app.state.db).preview("ris", records))
    except BibInvalid as exc:
        return error_response(400, "invalid_bib_file", str(exc))


@router.post("/api/v1/preservation/ris/import", status_code=201)
async def import_ris(request: Request, includeDuplicates: bool = False) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    body = await read_limited_text(request, MAX_PREVIEW_BYTES)
    if isinstance(body, Response):
        return body
    try:
        records = parse_ris(body)
        return no_store(
            await BibStore(request.app.state.db).import_records(
                "ris", records, include_duplicates=includeDuplicates
            ),
            201,
        )
    except BibInvalid as exc:
        return error_response(400, "invalid_bib_file", str(exc))


@router.get("/api/v1/preservation/ris/export")
async def export_ris(
    request: Request,
    ids: Annotated[list[str] | None, Query()] = None,
    format: Annotated[str | None, Query()] = None,
) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    db = request.app.state.db
    store = BibStore(db)
    source = format if format in ("ris", "zotero_rdf") else "ris"
    records = (
        await store.get_records_by_ids([str(i) for i in (ids or [])], None)
        if ids
        else await store.list_records(source)
    )
    if not records:
        return error_response(400, "nothing_to_export", "没有可导出的 RIS 资料。")
    exported = serialize_ris(records)
    report = roundtrip_report(records, exported)
    export_id = await RisExportStore(db).persist(len(records), report)
    return Response(
        content=exported,
        media_type="application/x-research-info-systems",
        headers={
            "Content-Disposition": f'attachment; filename="lumi-bibliography-{export_id}.ris"',
            "X-Lumi-Roundtrip": "ok" if report["roundtripOk"] else "diffs",
            "X-Lumi-Export-Id": export_id,
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/v1/preservation/ris/exports")
async def list_ris_exports(request: Request) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store({"exports": await RisExportStore(request.app.state.db).list_exports()})
