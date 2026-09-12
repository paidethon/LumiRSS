"""Offline snapshot routes (phase2 M2).

POST /api/v1/library/snapshots runs the serial monolith job inline
(single user; the client shows a generating state). Artifacts are served
from /api/v1/library/assets/{uuid}/page.html with a strict
``Content-Security-Policy: sandbox`` response set — no script, no same-
origin powers, no forms, no top navigation — so even a malicious
snapshot cannot touch Lumi's origin, cookies or /api.
"""

from fastapi import APIRouter, Request, Response

from lumirss.library_assets import (
    AssetNotFound,
    AssetStore,
)
from lumirss.models import (
    SnapshotCreate,
    SnapshotListResponse,
    SnapshotUsage,
    SnapshotView,
)
from lumirss.snapshots import (
    MonolithUnavailable,
    SnapshotFailed,
    SnapshotJobRunner,
)

from ..deps import _get_snapshot_runner, _get_snapshot_store

router = APIRouter()


@router.post("/api/v1/library/snapshots", response_model=SnapshotView, status_code=201)
async def create_snapshot(payload: SnapshotCreate, request: Request) -> SnapshotView:
    runner: SnapshotJobRunner = _get_snapshot_runner(request)
    result = await runner.run(payload.url)
    return _snapshot_view_from_dict(result["asset"], bool(result["deduplicated"]))


def _snapshot_view_from_dict(record: dict, deduped: bool) -> SnapshotView:
    return SnapshotView(
        uuid=record["uuid"],
        itemRef=record["itemRef"],
        url=record.get("url", ""),
        bytes=record["bytes"],
        sha256=record["sha256"],
        deduplicated=deduped,
        createdAt=record["createdAt"],
    )


@router.get("/api/v1/library/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(request: Request) -> SnapshotListResponse:
    store: AssetStore = _get_snapshot_store(request)
    rows = await store.list_snapshots()
    usage = await store.usage()
    items = [
        SnapshotView(
            uuid=row.record.uuid,
            itemRef=f"library:{row.record.item_uuid}",
            url=row.record.url,
            bytes=row.record.bytes,
            sha256=row.record.sha256,
            deduplicated=row.deduplicated,
            createdAt=row.record.created_at,
        )
        for row in rows
    ]
    return SnapshotListResponse(
        items=items,
        usage=SnapshotUsage(
            count=usage["count"],
            bytes=usage["bytes"],
            quotaBytes=usage["quotaBytes"],
        ),
    )


@router.get("/api/v1/library/assets/{asset_uuid}/page.html")
async def serve_snapshot(asset_uuid: str, request: Request) -> Response:
    """Sandboxed artifact read-out. The CSP `sandbox` directive strips
    scripts, forms, same-origin access and top navigation — the snapshot
    can never reach Lumi's origin, cookies or /api endpoints."""
    store: AssetStore = _get_snapshot_store(request)
    try:
        data = await store.read_bytes(asset_uuid)
    except AssetNotFound:
        raise
    return Response(
        content=data,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": (
                "sandbox; default-src 'none'; img-src data: blob:;"
                " style-src data: 'unsafe-inline';"
                " frame-ancestors 'self';"
            ),
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@router.delete("/api/v1/library/snapshots/{asset_uuid}", status_code=204)
async def delete_snapshot(asset_uuid: str, request: Request) -> Response:
    store: AssetStore = _get_snapshot_store(request)
    deleted = await store.delete_asset(asset_uuid)
    if not deleted:
        raise AssetNotFound(asset_uuid)
    return Response(status_code=204)


_ = (MonolithUnavailable, SnapshotFailed)  # mapped in errors.py
