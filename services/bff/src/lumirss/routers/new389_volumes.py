"""NEW-389 分卷导出路由 — 导出 / 校验 / 导入（缺卷 409）/ 台账。

- POST /api/v1/preservation/volumes/export   {itemIds?, maxVolumeBytes}
  → set-manifest + 逐卷（items 内嵌 + manifest）
- POST /api/v1/preservation/volumes/check    {setManifest, volumes} →
  完整性报告（零写入）
- POST /api/v1/preservation/volumes/import   {setManifest, volumes} →
  缺卷 → 409 + 缺失报告；完整 → 写入 + NEW-390 对账单
- GET  /api/v1/preservation/volumes/sets / imports → 台账
"""

from typing import Any

from fastapi import APIRouter, Request

from lumirss.new389_volumes import (
    VolumeInvalid,
    VolumeSetIncomplete,
    check_volumes,
    export_volumes,
    import_volumes,
    list_imports,
    list_sets,
)
from lumirss.routers.preservation_gate import (
    error_response,
    no_store,
    require_preservation_user,
)

router = APIRouter()


@router.post("/api/v1/preservation/volumes/export")
async def export_volume_set(payload: dict[str, Any], request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    raw_ids = payload.get("itemIds")
    ids = [str(ref) for ref in raw_ids] if isinstance(raw_ids, list) else []
    try:
        split = await export_volumes(
            request.app.state.db, ids, int(payload.get("maxVolumeBytes") or 64 * 1024)
        )
    except (VolumeInvalid, TypeError, ValueError) as exc:
        return error_response(400, "invalid_volume_request", str(exc))
    return no_store(split)


@router.post("/api/v1/preservation/volumes/check")
async def check_volume_set(payload: dict[str, Any], request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    set_manifest = payload.get("setManifest")
    volumes = payload.get("volumes")
    try:
        return no_store(
            await check_volumes(
                request.app.state.db,
                set_manifest if isinstance(set_manifest, dict) else {},
                volumes if isinstance(volumes, list) else [],
            )
        )
    except VolumeInvalid as exc:
        return error_response(400, "invalid_volume_request", str(exc))


@router.post("/api/v1/preservation/volumes/import")
async def import_volume_set(payload: dict[str, Any], request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    set_manifest = payload.get("setManifest")
    volumes = payload.get("volumes")
    try:
        return no_store(
            await import_volumes(
                request.app.state.db,
                set_manifest if isinstance(set_manifest, dict) else {},
                volumes if isinstance(volumes, list) else [],
            )
        )
    except VolumeInvalid as exc:
        return error_response(400, "invalid_volume_request", str(exc))
    except VolumeSetIncomplete as exc:
        return no_store(
            {
                "error": {
                    "type": "volume_set_incomplete",
                    "message": "卷集不完整——已拒绝导入，绝不默默少导。",
                    **exc.report,
                }
            },
            409,
        )


@router.get("/api/v1/preservation/volumes/sets")
async def list_volume_sets(request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store({"sets": await list_sets(request.app.state.db)})


@router.get("/api/v1/preservation/volumes/imports")
async def list_volume_imports(request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store({"imports": await list_imports(request.app.state.db)})
