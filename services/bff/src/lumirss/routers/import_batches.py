"""F049 导入批次路由 — 列表 / 详情 / 仅重试失败项。

重试语义：调用方（路由层）按 batch.kind 用存下的 retry_payload 重新
执行导入；已存在的目标记 skipped（幂等：不重复创建、不覆盖）。批次
记录本身不删除（审计），重试成功会新建一条批次记录。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.import_batch_store import ImportBatchStore

router = APIRouter()


@router.get("/api/v1/library/import-batches")
async def list_import_batches(request: Request, limit: int = 20) -> Response:
    store = ImportBatchStore(request.app.state.db)
    batches = await store.list_batches(limit)
    return JSONResponse({"items": batches})


@router.post("/api/v1/library/import-batches/{batch_id}/retry")
async def retry_import_batch(batch_id: str, request: Request) -> Response:
    """仅重试失败项（F049）。幂等：已存在的目标记 skipped，不覆盖。"""
    from lumirss.deps import _get_control_adapter, _get_library_store
    from lumirss.library import BookmarkInvalid

    store = ImportBatchStore(request.app.state.db)
    batch = await store.get(batch_id)
    if batch is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "import_batch_not_found", "message": "批次不存在。"}},
        )
    items = batch["retryPayload"]
    if not items:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "nothing_to_retry", "message": "该批次没有可重试的失败项。"}},
        )
    imported = 0
    skipped = 0
    errors: list[dict[str, object]] = []
    if batch["kind"] == "md_notes":
        # F049 收尾：MD 笔记重试按 name/content/workspaceId 重放；
        # content_hash 幂等（已存在 → skipped，不覆盖）。
        from lumirss.lumi_notes import MAX_FILE_BYTES, LumiNotesStore

        notes = LumiNotesStore(request.app.state.db)
        for item in items:
            name = str(item.get("name") or "")
            content = str(item.get("content") or "")
            if not name.strip():
                errors.append({"url": name, "reason": "invalid"})
                continue
            if len(content.encode("utf-8", errors="ignore")) > MAX_FILE_BYTES:
                errors.append({"url": name, "reason": "too_large"})
                continue
            try:
                _view, created = await notes.import_note(
                    name=name.strip(),
                    content=content,
                    workspace_id=item.get("workspaceId"),
                )
            except Exception as exc:  # noqa: BLE001 — 逐项如实汇报
                errors.append({"url": name, "reason": str(exc)})
                continue
            if created:
                imported += 1
            else:
                skipped += 1
    elif batch["kind"] == "opml":
        control = _get_control_adapter(request)
        existing = {sub.feed_url for sub in await control.list_subscriptions()}
        for item in items:
            url = str(item.get("url") or "")
            if not url:
                continue
            if url in existing:
                skipped += 1
                continue
            try:
                await control.subscribe(url, title=item.get("title") or None)
                existing.add(url)
                imported += 1
            except Exception as exc:  # noqa: BLE001 — 逐项如实汇报
                errors.append({"url": url, "reason": str(exc)})
    else:
        library = _get_library_store(request)
        for item in items:
            url = str(item.get("url") or "")
            if not url:
                continue
            try:
                _view, created = await library.create_url_bookmark(url, item.get("title"))
            except BookmarkInvalid as exc:
                errors.append({"url": url, "reason": str(exc)})
                continue
            if created:
                imported += 1
            else:
                skipped += 1
    new_batch_id = await store.record(
        kind=batch["kind"],
        counts={"imported": imported, "skipped": skipped, "failed": len(errors)},
        errors=errors,
        # md_notes 的重放载荷是 name/content/workspaceId（非 url/title），
        # 原样传递仍失败项，供链式重试。
        retry_payload=(
            [
                {
                    "name": item.get("name"),
                    "content": item.get("content"),
                    "workspaceId": item.get("workspaceId"),
                }
                for item in items
            ]
            if batch["kind"] == "md_notes"
            else [{"url": item.get("url"), "title": item.get("title")} for item in items]
        ),
    )
    return JSONResponse(
        {
            "batchId": new_batch_id,
            "imported": imported,
            "skipped": skipped,
            "failed": len(errors),
            "errors": errors,
        }
    )


@router.get("/api/v1/library/import-batches/{batch_id}")
async def get_import_batch(batch_id: str, request: Request) -> Response:
    store = ImportBatchStore(request.app.state.db)
    batch = await store.get(batch_id)
    if batch is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "import_batch_not_found", "message": "批次不存在。"}},
        )
    return JSONResponse(batch)
