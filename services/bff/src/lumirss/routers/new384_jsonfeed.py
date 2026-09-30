"""NEW-384 JSON Feed 个人导出路由 — 生成（JSON / 下载）/ 台账。

- POST /api/v1/preservation/json-feed   {scopes: ["clips","bib"]} →
  JSON Feed 1.1 字典（含 _lumi.fieldsIncluded / authorizationScope）
- POST /api/v1/preservation/json-feed/download?scopes= → .json 下载
- GET  /api/v1/preservation/json-feed/exports → 导出台账
"""

import json
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from lumirss.new384_jsonfeed import (
    FeedScopeInvalid,
    build_feed,
    list_exports,
    persist_export,
)
from lumirss.routers.preservation_gate import (
    error_response,
    no_store,
    require_preservation_user,
)

router = APIRouter()


def _scopes_of(payload: dict, fallback: list[str] | None) -> list[str]:
    raw = payload.get("scopes")
    if isinstance(raw, list) and raw:
        return [str(item) for item in raw]
    return list(fallback or [])


@router.post("/api/v1/preservation/json-feed")
async def create_json_feed(payload: dict, request: Request) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    try:
        feed = await build_feed(request.app.state.db, _scopes_of(payload, None))
    except FeedScopeInvalid as exc:
        return error_response(400, "invalid_feed_scope", str(exc))
    feed["_lumi"]["exportId"] = await persist_export(request.app.state.db, feed)
    return no_store(feed)


@router.post("/api/v1/preservation/json-feed/download")
async def download_json_feed(
    request: Request,
    scopes: Annotated[list[str] | None, Query()] = None,
) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    try:
        feed = await build_feed(request.app.state.db, list(scopes or []))
    except FeedScopeInvalid as exc:
        return error_response(400, "invalid_feed_scope", str(exc))
    export_id = await persist_export(request.app.state.db, feed)
    return Response(
        content=json.dumps(feed, ensure_ascii=False, indent=1),
        media_type="application/feed+json",
        headers={
            "Content-Disposition": f'attachment; filename="lumi-feed-{export_id}.json"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/v1/preservation/json-feed/exports")
async def list_json_feed_exports(request: Request) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store({"exports": await list_exports(request.app.state.db)})
