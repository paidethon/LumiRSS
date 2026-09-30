"""NEW-385 WARC 档案索引导入路由 — 预览 / 导入 / 索引查询 / 台账。

- POST /api/v1/preservation/warc/preview?importBodies=  raw WARC →
  索引预览（零写入；importBodies=true 时对安全文本记录提取正文预览）
- POST /api/v1/preservation/warc/import?importBodies=   → 索引入库
- GET  /api/v1/preservation/warc/records?batchId=       → 索引清单
- GET  /api/v1/preservation/warc/batches                → 台账
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from lumirss.new385_warc import WarcInvalid, WarcStore, parse_warc
from lumirss.routers.preservation_gate import (
    MAX_WARC_BYTES,
    error_response,
    no_store,
    read_limited_text,
    require_preservation_user,
)

router = APIRouter()


async def _parse_request(request: Request, import_bodies: bool):
    body = await read_limited_text(request, MAX_WARC_BYTES)
    if isinstance(body, Response):
        return body
    # WARC 是字节精准格式（Content-Length 定位），以 UTF-8 替换解码保序。
    raw = body.encode("utf-8", "replace")
    try:
        return parse_warc(raw, import_bodies=import_bodies)
    except WarcInvalid as exc:
        return error_response(400, "invalid_warc", str(exc))


@router.post("/api/v1/preservation/warc/preview")
async def preview_warc(
    request: Request, importBodies: bool = False
) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    parsed = await _parse_request(request, importBodies)
    if isinstance(parsed, Response):
        return parsed
    return no_store(parsed)


@router.post("/api/v1/preservation/warc/import", status_code=201)
async def import_warc(request: Request, importBodies: bool = False) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    parsed = await _parse_request(request, importBodies)
    if isinstance(parsed, Response):
        return parsed
    return no_store(await WarcStore(request.app.state.db).import_index(parsed), 201)


@router.get("/api/v1/preservation/warc/records")
async def list_warc_records(
    request: Request,
    batchId: Annotated[str | None, Query()] = None,
) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store(
        {"records": await WarcStore(request.app.state.db).list_records(batchId)}
    )


@router.get("/api/v1/preservation/warc/batches")
async def list_warc_batches(request: Request) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store({"batches": await WarcStore(request.app.state.db).list_batches()})
