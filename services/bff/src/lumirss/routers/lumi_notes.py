"""Lumi notes routes (F020) — 本地 Markdown 批量入库与列表（最小实体）。

- POST /api/v1/library/notes/import：逐文件校验（≤200KB/文件、≤50
  文件/批、合法 UTF-8——非法字节序列在 JSON 解码层已失败，这里对空
  内容/空名拒绝），content_hash 幂等（同 hash 已存在 → skipped），
  逐项返回 {name, ok, uuid?, reason?}；重名不同内容共存。
- GET /api/v1/library/notes?workspace_id=：列表（title/updated_at/
  摘要首行）。导入前零写入：入库仅发生在本端点（预览由前端用文件
  元数据构造，不发请求）。
"""

from fastapi import APIRouter, Query, Request, Response

from lumirss.lumi_notes import (
    MAX_BATCH_FILES,
    MAX_FILE_BYTES,
    LumiNotesStore,
)
from lumirss.models import (
    LumiNoteCreate,
    LumiNoteDetail,
    LumiNoteList,
    LumiNoteUpdate,
    NoteImportRequest,
    NoteImportResult,
)

router = APIRouter()


@router.post(
    "/api/v1/library/notes/import",
    response_model=NoteImportResult,
)
async def import_notes(payload: NoteImportRequest, request: Request) -> NoteImportResult:
    """批量入库 Markdown 文件（幂等；部分失败不中断整批）。"""
    if len(payload.files) > MAX_BATCH_FILES:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "too_many_files",
                    "message": f"每批最多 {MAX_BATCH_FILES} 个文件。",
                }
            },
        )
    store = LumiNotesStore(request.app.state.db)
    items = []
    imported = 0
    skipped = 0
    for file in payload.files:
        size = len(file.content.encode("utf-8", errors="ignore"))
        if not file.name.strip():
            items.append({"name": file.name, "ok": False, "reason": "invalid"})
            continue
        if size > MAX_FILE_BYTES:
            items.append({"name": file.name, "ok": False, "reason": "too_large"})
            continue
        try:
            file.content.encode("utf-8")
        except UnicodeEncodeError:
            items.append({"name": file.name, "ok": False, "reason": "invalid"})
            continue
        view, created = await store.import_note(
            name=file.name.strip(),
            content=file.content,
            workspace_id=payload.workspaceId,
        )
        if created:
            imported += 1
            items.append({"name": file.name, "ok": True, "uuid": view.uuid})
        else:
            skipped += 1
            items.append({"name": file.name, "ok": True, "uuid": view.uuid, "reason": "duplicate"})
    # F049 收尾：MD 笔记导入写批次（kind="md_notes"）；失败项存
    # retry_payload（name/content/workspaceId 足以重放），批次记录失败
    # 不影响导入本身。
    failed_items = [item for item in items if not item.get("ok")]
    try:
        from lumirss.import_batch_store import ImportBatchStore

        await ImportBatchStore(request.app.state.db).record(
            kind="md_notes",
            counts={
                "imported": imported,
                "skipped": skipped,
                "failed": len(failed_items),
            },
            errors=[
                {"url": item.get("name"), "reason": item.get("reason")}
                for item in failed_items
            ],
            retry_payload=[
                {
                    "name": file.name,
                    "content": file.content,
                    "workspaceId": payload.workspaceId,
                }
                for file, item in zip(payload.files, items, strict=False)
                if not item.get("ok")
            ],
        )
    except Exception:  # noqa: BLE001 — 批次记录失败不影响导入本身
        pass
    return NoteImportResult(
        items=items,
        imported=imported,
        skipped=skipped,
    )


@router.get("/api/v1/library/notes", response_model=LumiNoteList)
async def list_notes(
    request: Request,
    workspace_id: str | None = Query(None),
) -> LumiNoteList:
    """F020：笔记列表（title/updated_at/摘要首行；workspace 过滤可选）。"""
    store = LumiNotesStore(request.app.state.db)
    items = await store.list_notes(workspace_id)
    return LumiNoteList(items=items)


# ---------------------------------------------------------------------------
# F090 Lumi 笔记全生命周期（创建/读取/更新乐观锁/软删恢复 + 搜索接线）
# ---------------------------------------------------------------------------


def _lifecycle(request: Request):
    from lumirss.lumi_notes_lifecycle import NoteLifecycleStore

    return NoteLifecycleStore(request.app.state.db)


@router.post("/api/v1/library/notes", response_model=LumiNoteDetail, status_code=201)
async def create_note(
    payload: LumiNoteCreate, request: Request
) -> LumiNoteDetail:
    """手动创建笔记（contentMd ≤100KB；同步入搜索投影）。
    N079：可选类型化分栏（facts/interpretation/toVerify）。"""
    note = await _lifecycle(request).create_note(
        title=payload.title,
        content_md=payload.contentMd,
        workspace_id=payload.workspaceId,
        sections=payload.sections,
    )
    return LumiNoteDetail(**note)


@router.get("/api/v1/library/notes/{note_id}", response_model=LumiNoteDetail)
async def get_note(note_id: str, request: Request) -> LumiNoteDetail:
    from lumirss.errors import LumiNoteNotFound

    note = await _lifecycle(request).get_note(note_id)
    if note is None:
        raise LumiNoteNotFound(note_id)
    return LumiNoteDetail(
        uuid=note["uuid"],
        title=note["title"],
        contentMd=note["contentMd"],
        workspaceId=note["workspaceId"],
        sections=note["sections"],
        createdAt=note["createdAt"],
        updatedAt=note["updatedAt"],
    )


@router.patch("/api/v1/library/notes/{note_id}", response_model=LumiNoteDetail)
async def update_note(
    note_id: str, payload: LumiNoteUpdate, request: Request
) -> LumiNoteDetail:
    """更新（baseUpdatedAt 乐观锁 → 409 note_conflict）。"""
    from lumirss.errors import LumiNoteNotFound
    from lumirss.note_sections import NoteSectionsInvalid

    try:
        note = await _lifecycle(request).update_note(
            note_id,
            title=payload.title,
            content_md=payload.contentMd,
            base_updated_at=payload.baseUpdatedAt,
            sections=payload.sections,
            sections_given="sections" in payload.model_fields_set,
        )
    except KeyError as exc:
        raise LumiNoteNotFound(note_id) from exc
    except NoteSectionsInvalid as exc:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=422,
            content={
                "error": {"type": "invalid_note_sections", "message": str(exc)}
            },
        )
    return LumiNoteDetail(**note)


@router.delete("/api/v1/library/notes/{note_id}", status_code=204)
async def delete_note(note_id: str, request: Request) -> Response:
    """软删（回收站 kind=note；搜索投影同步移除）。"""
    from fastapi.responses import JSONResponse


    deleted = await _lifecycle(request).soft_delete_note(note_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "note_not_found", "message": "笔记不存在。"}
            },
        )
    return Response(status_code=204)
