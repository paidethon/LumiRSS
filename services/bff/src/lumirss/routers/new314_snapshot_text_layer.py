"""NEW-314 快照文字检索层路由 — 构建 / 检索定位 / 状态。

- POST /api/v1/library/snapshots/{asset_uuid}/text-layer         → 构建或重建（原快照不变）
- GET  /api/v1/library/snapshots/{asset_uuid}/text-layer?q=…     → 命中块（seq 定位）
- GET  /api/v1/library/snapshots/{asset_uuid}/text-layer/status  → 构建状态
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from lumirss.library_assets import AssetNotFound
from lumirss.new314_snapshot_text_layer import (
    SnapshotTextLayerStore,
    TextLayerInvalid,
)

router = APIRouter()


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> SnapshotTextLayerStore:
    from lumirss.deps import _get_snapshot_store

    return SnapshotTextLayerStore(
        request.app.state.db, _get_snapshot_store(request)
    )


@router.post("/api/v1/library/snapshots/{asset_uuid}/text-layer", status_code=201)
async def build_text_layer(asset_uuid: str, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).build(asset_uuid), status_code=201
        )
    except AssetNotFound:
        return _error(404, "snapshot_not_found", "快照不存在。")


@router.get("/api/v1/library/snapshots/{asset_uuid}/text-layer")
async def search_text_layer(
    asset_uuid: str, request: Request, q: str = ""
) -> Response:
    try:
        return JSONResponse(await _store(request).search(asset_uuid, q))
    except AssetNotFound:
        return _error(
            404,
            "text_layer_not_found",
            "该快照还没有文字检索层，请先构建。",
        )
    except TextLayerInvalid as exc:
        return _error(400, "invalid_text_query", str(exc))


@router.get("/api/v1/library/snapshots/{asset_uuid}/text-layer/status")
async def text_layer_status(asset_uuid: str, request: Request) -> Response:
    return JSONResponse(await _store(request).status(asset_uuid))
