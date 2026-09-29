"""NEW-326 可移植打包路由 — 组包（JSON manifest）/ 下载（zip）/ 台账。

- POST /api/v1/obsidian/bundles                  {noteRefs: [...]} → manifest（组包记录落台账）
- GET  /api/v1/obsidian/bundles                  打包台账
- GET  /api/v1/obsidian/bundles/{bundle_id}      manifest（含逐条违规）
- GET  /api/v1/obsidian/bundles/{bundle_id}/download → zip（notes/ + attachments/ + manifest.json）

组包只读 Vault；下载按台账从当前 Vault 重装（Vault 已更新时内容随之
更新，如实说明）。owner 门槛（O168）。
"""

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.new326_portable_bundle import (
    BundleInvalid,
    PortableBundleBuilder,
)
from lumirss.routers.obsidian import _require_owner

router = APIRouter()


async def _builder(request: Request) -> PortableBundleBuilder:
    from lumirss.deps import _get_obsidian_service

    vault_path = await _get_obsidian_service(request).get_vault_path()
    return PortableBundleBuilder(request.app.state.db, vault_path)


@router.post("/api/v1/obsidian/bundles")
async def create_portable_bundle(payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    note_refs = payload.get("noteRefs")
    try:
        built = await (await _builder(request)).build(
            note_refs if isinstance(note_refs, list) else []
        )
    except BundleInvalid as exc:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_bundle", "message": str(exc)}},
        )
    bundle_id = await (await _builder(request)).persist(built["manifest"])
    built["manifest"]["id"] = bundle_id
    return JSONResponse(built["manifest"])


@router.get("/api/v1/obsidian/bundles")
async def list_portable_bundles(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse({"bundles": await (await _builder(request)).list_bundles()})


@router.get("/api/v1/obsidian/bundles/{bundle_id}")
async def get_portable_bundle(bundle_id: str, request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    manifest = await (await _builder(request)).get_bundle(bundle_id)
    if manifest is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "bundle_not_found", "message": "打包记录不存在。"}
            },
        )
    return JSONResponse(manifest)


@router.get("/api/v1/obsidian/bundles/{bundle_id}/download")
async def download_portable_bundle(bundle_id: str, request: Request) -> Response:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    builder = await _builder(request)
    stored = await builder.get_bundle(bundle_id)
    if stored is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "bundle_not_found", "message": "打包记录不存在。"}
            },
        )
    note_refs = [str(note.get("noteUuid") or "") for note in stored["notes"]]
    try:
        built = await builder.build(note_refs)
    except BundleInvalid as exc:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_bundle", "message": str(exc)}},
        )
    built["manifest"]["id"] = str(bundle_id).strip()
    data = builder.build_zip(built["manifest"], built["files"])
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="lumi-bundle-{bundle_id}.zip"',
            "Cache-Control": "no-store",
        },
    )
