"""NEW-219 文章批量归档路由 —— 条件预览 / 勾选归档 / 收据 / 撤销。

预览：POST /api/v1/archive-batches/preview（服务端真实 COUNT +
有界样本；加星恒排除并回显 effectiveExclusions）。
归档：POST /api/v1/archive-batches（只收勾选 refs；加星 → 409）。
收据：GET /api/v1/archive-batches、GET .../{batch_id}。
撤销：POST .../{batch_id}/undo（只撤未被后续修改的部分；单向）。
归档走既有 set-read 管线（FreshRSS set_entry_state + 投影镜像，set 语义）。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.deps import _get_adapter, _get_search_service
from lumirss.entryref import decode_entry_ref
from lumirss.itemref import RSS_DOMAIN, parse_item_ref
from lumirss.new219_archive_batches import (
    ArchiveBatchConflict,
    ArchiveBatchInvalid,
    ArchiveBatchNotFound,
    ArchiveBatchStore,
    archive_preview,
)

router = APIRouter()


class ArchivePreviewRequest(BaseModel):
    model_config = {"extra": "forbid"}

    feedUrl: str | None = Field(default=None, max_length=2048)
    olderThanDays: int | None = Field(default=None, ge=0, le=3650)
    includeRead: bool = False


class ArchiveApplyRequest(BaseModel):
    model_config = {"extra": "forbid"}

    refs: list[str] = Field(min_length=1, max_length=200)


def _error(status: int, error_type: str, message: str, extra: dict | None = None) -> JSONResponse:
    content: dict = {"error": {"type": error_type, "message": message}}
    if extra:
        content["error"].update(extra)
    return JSONResponse(status_code=status, content=content)


def _clean_refs(raw: list[str]) -> list[str]:
    cleaned: list[str] = []
    for ref in raw:
        try:
            parsed = parse_item_ref(ref)
        except ValueError as exc:
            raise ArchiveBatchInvalid(f"引用形状非法：{ref}") from exc
        if parsed.domain != RSS_DOMAIN:
            raise ArchiveBatchInvalid(f"归档只支持 rss 引用：{ref}")
        if parsed.format() not in cleaned:
            cleaned.append(parsed.format())
    return cleaned


@router.post("/api/v1/archive-batches/preview")
async def archive_batch_preview(payload: ArchivePreviewRequest, request: Request) -> JSONResponse:
    return JSONResponse(
        await archive_preview(
            request.app.state.db,
            feed_url=payload.feedUrl,
            older_than_days=payload.olderThanDays,
            include_read=payload.includeRead,
        )
    )


@router.post("/api/v1/archive-batches")
async def archive_batch_apply(payload: ArchiveApplyRequest, request: Request) -> Response:
    try:
        refs = _clean_refs(payload.refs)
    except ArchiveBatchInvalid as exc:
        return _error(422, "invalid_archive_batch", str(exc))
    if not refs:
        return _error(422, "invalid_archive_batch", "勾选清单为空。")
    store = ArchiveBatchStore(request.app.state.db)
    starred = await store.refused_starred(refs)
    if starred:
        return _error(
            409,
            "archive_batch_refused",
            "勾选里含加星条目，归档被整批拒绝。",
            extra={"starredRefs": starred},
        )
    snapshots = await store.snapshot_rows(refs)
    adapter = _get_adapter(request)  # 未配置 → 诚实 503（与积压整理一致）
    search = _get_search_service(request)
    archived: list[str] = []
    failed: list[dict[str, str]] = []

    async def _archive(ref: str) -> None:
        snapshot = snapshots.get(ref)
        if snapshot is None:
            failed.append({"ref": ref, "reason": "not_found"})
            return
        try:
            item_id = decode_entry_ref(parse_item_ref(ref).key)
            await adapter.set_entry_state(item_id, read=True, starred=None)
            await search.set_entry_read(parse_item_ref(ref).key, True)
            archived.append(ref)
        except Exception:  # noqa: BLE001 — 单条失败不中断整批
            failed.append({"ref": ref, "reason": "upstream_failed"})

    for ref in refs:
        await _archive(ref)
    receipt = await store.record_batch(archived=archived, snapshots=snapshots, failed=failed)
    return JSONResponse(receipt)


@router.get("/api/v1/archive-batches")
async def archive_batch_list(request: Request) -> JSONResponse:
    return JSONResponse({"items": await ArchiveBatchStore(request.app.state.db).list_batches()})


@router.get("/api/v1/archive-batches/{batch_id}")
async def archive_batch_receipt(batch_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await ArchiveBatchStore(request.app.state.db).get_batch(batch_id))
    except ArchiveBatchNotFound:
        return _error(404, "archive_batch_not_found", "归档收据不存在。")


@router.post("/api/v1/archive-batches/{batch_id}/undo")
async def archive_batch_undo(batch_id: str, request: Request) -> Response:
    store = ArchiveBatchStore(request.app.state.db)
    adapter = _get_adapter(request)
    search = _get_search_service(request)

    async def _restore(ref: str) -> None:
        item_id = decode_entry_ref(parse_item_ref(ref).key)
        await adapter.set_entry_state(item_id, read=False, starred=None)
        await search.set_entry_read(parse_item_ref(ref).key, False)

    try:
        result = await store.undo_batch(batch_id, restore_fn=_restore)
    except ArchiveBatchNotFound:
        return _error(404, "archive_batch_not_found", "归档收据不存在。")
    except ArchiveBatchConflict:
        return _error(409, "archive_batch_conflict", "这批归档已经撤销过。")
    return JSONResponse(result)
