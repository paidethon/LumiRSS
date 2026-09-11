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


def _snapshot_view(record, url: str, deduped: bool) -> SnapshotView:
    return SnapshotView(
        uuid=record.uuid,
        itemRef=f"library:{record.item_uuid}",
        url=url,
        bytes=record.bytes,
        sha256=record.sha256,
        deduplicated=deduped,
        createdAt=record.created_at,
    )


@router.post("/api/v1/library/snapshots", response_model=SnapshotView, status_code=201)
async def create_snapshot(payload: SnapshotCreate, request: Request) -> SnapshotView:
    runner: SnapshotJobRunner = _get_snapshot_runner(request)
    result = await runner.run(payload.url)
    record = await _get_snapshot_store(request).get_asset(result["asset"]["uuid"])
    assert record is not None
    return _snapshot_view(record, result["url"], bool(result["deduplicated"]))


@router.get("/api/v1/library/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(request: Request) -> SnapshotListResponse:
    store: AssetStore = _get_snapshot_store(request)
    records = await store.list_assets()
    usage = await store.usage()
    items = [
        SnapshotView(
            uuid=record.uuid,
            itemRef=f"library:{record.item_uuid}",
            url="",
            bytes=record.bytes,
            sha256=record.sha256,
            createdAt=record.created_at,
        )
        for record in records
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
