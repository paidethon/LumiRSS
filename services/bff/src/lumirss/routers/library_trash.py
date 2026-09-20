"""Library trash routes (F019) — 回收站的列表 / 恢复 / 永久删除。

软删由既有 DELETE /library/bookmarks|clips 端点承担（标记 deleted_at +
移除搜索投影）；本路由提供：
- GET  /api/v1/library/trash?type=bookmark|clip —— 回收站列表；
- POST /api/v1/library/trash/{uuid}/restore —— 恢复（重新入搜索索引，
  标签/工作区关联原样保留）；
- DELETE /api/v1/library/trash/{uuid}?permanent=true —— 永久删除
  （必须显式 permanent=true；UI 侧二次确认）。
"""

from fastapi import APIRouter, Query, Request, Response

from lumirss.models import TrashItem, TrashList

from ..deps import _get_clip_store, _get_library_store

router = APIRouter()

_NOT_FOUND = {
    "error": {"type": "library_not_found", "message": "回收站中没有该条目。"}
}
_BAD_KIND = {
    "error": {
        "type": "invalid_kind",
        "message": 'type 仅支持 "bookmark" 或 "clip"。',
    }
}


@router.get("/api/v1/library/trash", response_model=TrashList)
async def list_trash(
    request: Request,
    type: str | None = Query(None),
) -> TrashList:
    """F019：回收站列表（可选 type 过滤；新删除在前）。"""
    if type is not None and type not in ("bookmark", "clip", "note"):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content=_BAD_KIND)
    db = request.app.state.db
    await db.migrate()
    items: list[TrashItem] = []
    kinds = (type,) if type is not None else ("bookmark", "clip", "note")
    for kind in kinds:
        if kind == "note":
            note_rows = await db.fetch_all(
                "SELECT uuid, title, deleted_at FROM lumi_notes WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
            )
            for row in note_rows:
                items.append(
                    TrashItem(
                        uuid=str(row["uuid"]),
                        kind="note",
                        title=str(row["title"] or ""),
                        url=None,
                        deletedAt=str(row["deleted_at"]),
                    )
                )
            continue
        if kind == "bookmark":
            rows = await db.fetch_all(
                "SELECT b.item_uuid, b.title, b.url, i.deleted_at FROM library_bookmarks b"
                " JOIN library_items i ON i.uuid = b.item_uuid"
                " WHERE i.deleted_at IS NOT NULL ORDER BY i.deleted_at DESC"
            )
        else:
            rows = await db.fetch_all(
                "SELECT c.item_uuid, c.title, c.url, i.deleted_at FROM library_clips c"
                " JOIN library_items i ON i.uuid = c.item_uuid"
                " WHERE i.deleted_at IS NOT NULL ORDER BY i.deleted_at DESC"
            )
        for row in rows:
            deleted_at = row["deleted_at"]
            if deleted_at is None:
                continue
            items.append(
                TrashItem(
                    uuid=str(row["item_uuid"]),
                    kind=kind,
                    title=str(row["title"] or ""),
                    url=row["url"],
                    deletedAt=str(deleted_at),
                )
            )
    return TrashList(items=items)


@router.post("/api/v1/library/trash/{item_uuid}/restore", status_code=204)
async def restore_trash_item(item_uuid: str, request: Request) -> Response:
    """F019：恢复（按身份行 kind 分派到书签/剪辑存储）。"""
    db = request.app.state.db
    await db.migrate()
    row = await db.fetch_one(
        "SELECT uuid, kind FROM library_items WHERE uuid = ? AND deleted_at IS NOT NULL",
        (item_uuid,),
    )
    note_row = await db.fetch_one(
        "SELECT uuid FROM lumi_notes WHERE uuid = ? AND deleted_at IS NOT NULL",
        (item_uuid,),
    )
    if row is None and note_row is None:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content=_NOT_FOUND)
    kind = str(row["kind"]) if row is not None else "note"
    restored = False
    if kind == "note":
        from lumirss.lumi_notes_lifecycle import NoteLifecycleStore

        restored = await NoteLifecycleStore(db).restore_note(item_uuid)
    elif kind == "bookmark":
        restored = await _get_library_store(request).restore_bookmark(item_uuid)
    elif kind == "clip":
        restored = await _get_clip_store(request).restore_clip(item_uuid)
    if not restored:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content=_NOT_FOUND)
    from ..deps import _rag_mark_stale

    await _rag_mark_stale(request, [f"library:{item_uuid}"])
    return Response(status_code=204)


@router.delete("/api/v1/library/trash/{item_uuid}", status_code=204)
async def purge_trash_item(
    item_uuid: str, request: Request, permanent: bool = Query(False)
) -> Response:
    """F019：永久删除——必须显式 permanent=true（UI 二次确认的契约），
    缺失时拒绝（409 confirm_required），绝不静默清空。"""
    from fastapi.responses import JSONResponse

    if permanent is not True:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "confirm_required",
                    "message": "永久删除必须显式携带 permanent=true。",
                }
            },
        )
    db = request.app.state.db
    await db.migrate()
    row = await db.fetch_one(
        "SELECT kind FROM library_items WHERE uuid = ?", (item_uuid,)
    )
    note_row = await db.fetch_one(
        "SELECT uuid FROM lumi_notes WHERE uuid = ? AND deleted_at IS NOT NULL",
        (item_uuid,),
    )
    kind = str(row["kind"]) if row is not None else ("note" if note_row else None)
    purged = False
    if kind == "note":
        from lumirss.db_tx import transaction as _note_tx

        def _purge_note(conn):
            conn.execute(
                "DELETE FROM search_library WHERE ref = ?", (f"note:{item_uuid}",)
            )
            cursor2 = conn.execute(
                "DELETE FROM lumi_notes WHERE uuid = ?", (item_uuid,)
            )
            return cursor2.rowcount

        purged = bool(await _note_tx(db, _purge_note))
    elif kind == "bookmark":
        purged = await _get_library_store(request).purge_bookmark(item_uuid)
    elif kind == "clip":
        purged = await _get_clip_store(request).purge_clip(item_uuid)
    if not purged:
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    from ..deps import _rag_mark_stale

    await _rag_mark_stale(request, [f"library:{item_uuid}"])
    return Response(status_code=204)
