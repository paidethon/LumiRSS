"""Offline snapshot routes (phase2 M2).

POST /api/v1/library/snapshots runs the serial monolith job inline
(single user; the client shows a generating state). Artifacts are served
from /api/v1/library/assets/{uuid}/page.html with a strict
``Content-Security-Policy: sandbox`` response set — no script, no same-
origin powers, no forms, no top navigation — so even a malicious
snapshot cannot touch Lumi's origin, cookies or /api.
"""

import hashlib
import shutil
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

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


# ---- N124：快照资源预算（storage accounting）+ 选择性清理 -------------------


class SnapshotCleanupRequest(BaseModel):
    """POST /api/v1/library/snapshots/{id}/cleanup body.

    ``kinds`` 非空、白名单（images/styles/attachments）；条目本体
    （页面 HTML 文本 / 标题 / library 行）永不参与清理。"""

    model_config = {"extra": "forbid"}

    kinds: list[Literal["images", "styles", "attachments"]] = Field(min_length=1)


async def _storage_payload(store: AssetStore, asset_uuid: str) -> dict:
    from lumirss.snapshot_versions import storage_breakdown

    data = await store.read_bytes(asset_uuid)
    breakdown = storage_breakdown(data.decode("utf-8", errors="replace"))
    return {
        "uuid": asset_uuid,
        "totalBytes": len(data),
        "breakdown": breakdown,
    }


@router.get("/api/v1/library/snapshots/{asset_uuid}/storage")
async def snapshot_storage(asset_uuid: str, request: Request) -> dict:
    """N124：单个快照的资源预算。

    ``totalBytes`` = 磁盘文件的真实大小（monolith 单文件化，子资源内联
    为 base64 data: URI）；``breakdown`` 按 data: URI 的 MIME 类别算术
    拆分（images 带内联数量；styles/attachments 计解码后字节）——纯
    长度计算，绝不整包解码。"""
    store: AssetStore = _get_snapshot_store(request)
    record = await store.get_asset(asset_uuid)
    if record is None:
        raise AssetNotFound(asset_uuid)
    return await _storage_payload(store, asset_uuid)


@router.post("/api/v1/library/snapshots/{asset_uuid}/cleanup")
async def cleanup_snapshot_resources(
    asset_uuid: str, payload: SnapshotCleanupRequest, request: Request
) -> dict:
    """N124：只删除选中类别的内联资源；条目本体与 library 行保留。

    - 共享文件（sha256 去重让多行引用同一物理文件）→ 本行改写为
      自己的私有新文件，旧文件留给其他引用行，绝不改写他人内容；
    - 独占文件 → 原子改写（tmp + move；崩溃至多留下 reconcile()
      可清扫的孤儿 tmp）；
    - 被清理的子资源在既有完整性清单（resources 列）中如实标记
      missing——随后的快照诊断端点按缺失回显；
    - 内容变化 → RAG 标记 stale（与删除快照同一诚实语义）。
    """
    from lumirss.snapshot_versions import (
        mark_resources_missing,
        parse_resources,
        save_resources,
        storage_breakdown,
        strip_inline_resources,
    )

    store: AssetStore = _get_snapshot_store(request)
    record = await store.get_asset(asset_uuid)
    if record is None:
        raise AssetNotFound(asset_uuid)
    kinds = tuple(dict.fromkeys(payload.kinds))  # 去重保序
    data = await store.read_bytes(asset_uuid)
    html = data.decode("utf-8", errors="replace")
    new_html, removed = strip_inline_resources(html, kinds)
    cleaned = {kind: int(removed.get(kind, 0)) for kind in kinds}
    if new_html == html:
        # 没有可清理的该类资源 → 幂等 no-op（如实回 0 + 当前预算）。
        return {"cleaned": cleaned, "storage": await _storage_payload(store, asset_uuid)}

    new_data = new_html.encode("utf-8")
    digest = hashlib.sha256(new_data).hexdigest()
    row = await request.app.state.db.fetch_one(
        "SELECT COUNT(*) AS n FROM library_assets WHERE uuid != ? AND sha256 = ?",
        (asset_uuid, record.sha256),
    )
    shared = row is not None and int(row["n"]) > 0
    store.root.mkdir(parents=True, exist_ok=True)
    if shared:
        # 本行迁移到私有新文件；旧物理文件仍被其他行引用，保持不动。
        new_path = f"{asset_uuid}.cleaned-{digest[:8]}.html"
        target = store.root / new_path
    else:
        new_path = record.path
        target = store.file_path(record)
    tmp = store.root / f".{asset_uuid}.cleanup.tmp"
    try:
        tmp.write_bytes(new_data)
        shutil.move(str(tmp), str(target))
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    await request.app.state.db.execute(
        "UPDATE library_assets SET bytes = ?, sha256 = ?, path = ? WHERE uuid = ?",
        (len(new_data), digest, new_path, asset_uuid),
    )
    # 完整性清单：被清理的子资源标记 missing（既有诊断端点原样回显）。
    row = await request.app.state.db.fetch_one(
        "SELECT resources FROM library_assets WHERE uuid = ?", (asset_uuid,)
    )
    resources = parse_resources(
        str(row["resources"]) if row is not None and row["resources"] else "[]"
    )
    await save_resources(
        request.app.state.db,
        asset_uuid,
        mark_resources_missing(resources, kinds),
        False,
    )
    from ..deps import _rag_mark_stale

    await _rag_mark_stale(request, [f"library:{record.item_uuid}"])
    return {
        "cleaned": cleaned,
        "storage": {
            "uuid": asset_uuid,
            "totalBytes": len(new_data),
            "breakdown": storage_breakdown(new_html),
        },
    }
