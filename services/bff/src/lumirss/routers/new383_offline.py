"""NEW-383 离线 HTML 资料集路由 — 组包 / 下载 / 台账。

- POST /api/v1/preservation/offline-sites        {bibIds, clipRefs} →
  manifest（组包 + 链接自洽终检，落台账）
- GET  /api/v1/preservation/offline-sites        台账
- GET  /api/v1/preservation/offline-sites/{id}   manifest
- GET  /api/v1/preservation/offline-sites/{id}/download → zip（按台账
  从当前数据重装，条目已删除的如实列入 missing）
"""

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from lumirss.new383_offline_site import (
    OfflineSiteBuilder,
    OfflineSiteInvalid,
    assemble_zip,
)
from lumirss.routers.preservation_gate import (
    error_response,
    no_store,
    require_preservation_user,
)

router = APIRouter()


def _refs(payload: dict[str, Any], key: str, prefix: str) -> list[str]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        return []
    return [
        str(ref).removeprefix(prefix).strip()
        for ref in raw
        if str(ref).strip()
    ]


@router.post("/api/v1/preservation/offline-sites")
async def create_offline_site(payload: dict[str, Any], request: Request) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    builder = OfflineSiteBuilder(request.app.state.db)
    try:
        built = await builder.build(
            _refs(payload, "bibIds", ""), _refs(payload, "clipRefs", "library:")
        )
    except OfflineSiteInvalid as exc:
        return error_response(400, "invalid_offline_site", str(exc))
    site_id = await builder.persist(built["manifest"])
    built["manifest"]["id"] = site_id
    return no_store(built["manifest"])


@router.get("/api/v1/preservation/offline-sites")
async def list_offline_sites(request: Request) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    sites = await OfflineSiteBuilder(request.app.state.db).list_sites()
    return no_store({"sites": sites})


@router.get("/api/v1/preservation/offline-sites/{site_id}")
async def get_offline_site(site_id: str, request: Request) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    site = await OfflineSiteBuilder(request.app.state.db).get_site(site_id)
    if site is None:
        return error_response(404, "site_not_found", "离线资料集记录不存在。")
    return no_store(site)


@router.get("/api/v1/preservation/offline-sites/{site_id}/download")
async def download_offline_site(site_id: str, request: Request) -> Response:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    builder = OfflineSiteBuilder(request.app.state.db)
    built = await builder.rebuild(site_id)
    if built is None:
        return error_response(404, "site_not_found", "离线资料集记录不存在。")
    zip_bytes = assemble_zip(built["files"])
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="lumi-offline-site.zip"',
            "X-Lumi-Missing": json.dumps(built["manifest"]["missing"][:50]),
            "Cache-Control": "no-store",
        },
    )
