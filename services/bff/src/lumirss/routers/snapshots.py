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
    # F033：采集即记录资源状态；F034：首个版本行（sha256 + 净化文本）。
    from lumirss.snapshot_versions import (
        SnapshotVersionStore,
        save_resources,
    )

    asset = result["asset"]
    await save_resources(
        request.app.state.db,
        asset["uuid"],
        result["resources"],
        bool(result["resourcesTruncated"]),
    )
    await SnapshotVersionStore(request.app.state.db).record_version(
        snapshot_uuid=asset["uuid"],
        sha256=asset["sha256"],
        text=_html_to_plain(result.get("_data") or b""),
    )
    return _snapshot_view_from_dict(asset, bool(result["deduplicated"]))


def _html_to_plain(data: bytes) -> str:
    """净化后纯文本（版本存储/旧版查看用）；提取失败诚实降级为空。"""
    from lumirss.article_extract import extract_article

    try:
        return extract_article(data.decode("utf-8", errors="replace")).content_text
    except Exception:  # noqa: BLE001 — 文本提取失败不影响快照本体
        return ""


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
    record = await store.get_asset(asset_uuid)
    deleted = await store.delete_asset(asset_uuid)
    if not deleted:
        raise AssetNotFound(asset_uuid)
    from ..deps import _rag_mark_stale

    if record is not None:
        await _rag_mark_stale(request, [f"library:{record.item_uuid}"])
    return Response(status_code=204)


_ = (MonolithUnavailable, SnapshotFailed)  # mapped in errors.py


# -- F033 快照资源诊断 + F034 快照版本 ---------------------------------------


def _version_store(request: Request):
    from lumirss.snapshot_versions import SnapshotVersionStore

    return SnapshotVersionStore(request.app.state.db)


@router.get("/api/v1/library/snapshots/{asset_uuid}")
async def snapshot_detail(asset_uuid: str, request: Request) -> dict:
    """快照详情（含资源状态诊断；ok/failed/skipped 如实回显）。"""
    from lumirss.snapshot_versions import parse_resources

    store: AssetStore = _get_snapshot_store(request)
    record = await store.get_asset(asset_uuid)
    if record is None:
        raise AssetNotFound(asset_uuid)
    row = await request.app.state.db.fetch_one(
        "SELECT resources, resources_truncated FROM library_assets WHERE uuid = ?",
        (asset_uuid,),
    )
    return {
        **record.to_dict(),
        "resources": parse_resources(
            str(row["resources"]) if row is not None and row["resources"] else "[]"
        ),
        "resourcesTruncated": bool(row["resources_truncated"]) if row is not None else False,
    }


@router.post("/api/v1/library/snapshots/{asset_uuid}/retry-failed")
async def retry_failed_resources(asset_uuid: str, request: Request) -> dict:
    """仅对 failed 资源重采（走既有 SSRF 防护采集层，私网/元数据地址
    在 validate 层拒绝）；无失败 → no-op 返回 0（幂等）。"""
    from lumirss.snapshot_versions import parse_resources, save_resources

    store: AssetStore = _get_snapshot_store(request)
    record = await store.get_asset(asset_uuid)
    if record is None:
        raise AssetNotFound(asset_uuid)
    row = await request.app.state.db.fetch_one(
        "SELECT resources FROM library_assets WHERE uuid = ?", (asset_uuid,)
    )
    resources = parse_resources(
        str(row["resources"]) if row is not None and row["resources"] else "[]"
    )
    failed = [item for item in resources if item.get("status") == "failed"]
    if not failed:
        return {"retried": 0, "resources": resources}
    # 重采 = 对页面 URL 重跑既有采集。
    runner: SnapshotJobRunner = _get_snapshot_runner(request)
    await runner.run(record.url)
    updated = [
        (
            {**item, "status": "ok", "error": None}
            if item.get("status") == "failed"
            else item
        )
        for item in resources
    ]
    await save_resources(request.app.state.db, asset_uuid, updated, False)
    return {"retried": len(failed), "resources": updated}


@router.post("/api/v1/library/snapshots/{asset_uuid}/versions")
async def create_snapshot_version(asset_uuid: str, request: Request) -> dict:
    """F034：重新采集当前 URL 为新版本（≤5 版 FIFO；与最新版内容
    相同 → deduped 跳过）。采集失败不影响旧版（记录前即抛出）。"""
    store: AssetStore = _get_snapshot_store(request)
    record = await store.get_asset(asset_uuid)
    if record is None:
        raise AssetNotFound(asset_uuid)
    runner: SnapshotJobRunner = _get_snapshot_runner(request)
    result = await runner.run(record.url)
    sha = str(result["asset"]["sha256"])
    version_store = _version_store(request)
    latest = await version_store.latest_sha(asset_uuid)
    if latest is not None and latest == sha:
        return {
            "deduplicated": True,
            "versions": await version_store.list_versions(asset_uuid),
        }
    created = await version_store.record_version(
        snapshot_uuid=asset_uuid,
        sha256=sha,
        text=_html_to_plain(result.get("_data") or b""),
    )
    return {
        "deduplicated": False,
        "created": created,
        "versions": await version_store.list_versions(asset_uuid),
    }


@router.get("/api/v1/library/snapshots/{asset_uuid}/versions")
async def list_snapshot_versions(asset_uuid: str, request: Request) -> dict:
    store: AssetStore = _get_snapshot_store(request)
    if await store.get_asset(asset_uuid) is None:
        raise AssetNotFound(asset_uuid)
    versions = await _version_store(request).list_versions(asset_uuid)
    return {
        "versions": [
            {**version, "sha8": version["sha256"][:8], "text": None}
            for version in versions
        ]
    }


@router.get("/api/v1/library/snapshots/{asset_uuid}/versions/{version_id}")
async def get_snapshot_version(asset_uuid: str, version_id: int, request: Request) -> dict:
    """旧版查看（净化后纯文本）。"""
    version = await _version_store(request).get_version(version_id)
    if version is None or version["snapshotUuid"] != asset_uuid:
        raise AssetNotFound(asset_uuid)
    return version


@router.get("/api/v1/library/snapshots/{asset_uuid}/versions/{version_id}/diff")
async def diff_snapshot_versions(
    asset_uuid: str, version_id: int, request: Request, against: int = 0
) -> dict:
    """逐行 unified 文本差异（stdlib difflib；纯文本输出）。"""
    store = _version_store(request)
    a = await store.get_version(version_id)
    b = await store.get_version(against)
    if (
        a is None
        or b is None
        or a["snapshotUuid"] != asset_uuid
        or b["snapshotUuid"] != asset_uuid
    ):
        raise AssetNotFound(f"{asset_uuid}/{version_id}/{against}")
    from lumirss.snapshot_versions import text_diff

    return {"diff": text_diff(b["text"], a["text"])}
