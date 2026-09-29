"""NEW-239 标注冲突解决器路由 — 提交编辑 / 并排素材 / 解决。

- POST /api/v1/library/notes/{note_id}/conflicted-edits
      {title, contentMd, baseVersion, deviceLabel?}
      → 200 {outcome:"applied", note} | 409 {outcome:"conflict",
        pendingEditId, server, incoming}（编辑已暂存，绝不丢弃）。
- GET  /api/v1/library/notes/{note_id}/conflicted-edits → server + pending。
- POST /api/v1/library/notes/{note_id}/conflicted-edits/{pending_id}/resolve
      {resolution: keep_server|keep_pending|keep_both|merged, title?, contentMd?}
- GET  /api/v1/library/notes/{note_id}/conflict-log → 解决台账。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new239_note_conflicts import (
    ConflictInvalid,
    ConflictNotFound,
    ConflictStale,
    NoteConflictResolver,
)

router = APIRouter()


class ConflictedEditSubmit(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    contentMd: str
    baseVersion: int
    deviceLabel: str | None = None


class ConflictResolve(BaseModel):
    model_config = {"extra": "forbid"}

    resolution: str
    title: str | None = None
    contentMd: str | None = None


def _store(request: Request) -> NoteConflictResolver:
    return NoteConflictResolver(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/library/notes/{note_id}/conflicted-edits")
async def submit_conflicted_edit(
    note_id: str, payload: ConflictedEditSubmit, request: Request
) -> Response:
    """设备提交编辑：版本命中 → 应用；过期 → 409 + 暂存（并排解决）。"""
    try:
        result = await _store(request).submit_edit(
            note_id,
            title=payload.title,
            content_md=payload.contentMd,
            base_version=payload.baseVersion,
            device_label=payload.deviceLabel,
        )
    except ConflictInvalid as exc:
        return _error(422, "invalid_conflict_request", str(exc))
    except ConflictNotFound:
        return _error(404, "note_not_found", "笔记不存在。")
    except ConflictStale as exc:
        return JSONResponse(
            status_code=409,
            content={
                "outcome": "conflict",
                "pendingEditId": exc.pending_id,
                "server": exc.server,
                "incoming": exc.incoming,
            },
        )
    return JSONResponse(result)


@router.get("/api/v1/library/notes/{note_id}/conflicted-edits")
async def list_conflicted_edits(note_id: str, request: Request) -> Response:
    """并排素材：服务端当前版 + 待决编辑列表。"""
    try:
        result = await _store(request).pending_edits(note_id)
    except ConflictNotFound:
        return _error(404, "note_not_found", "笔记不存在。")
    return JSONResponse(result)


@router.post("/api/v1/library/notes/{note_id}/conflicted-edits/{pending_id}/resolve")
async def resolve_conflict(
    note_id: str, pending_id: str, payload: ConflictResolve, request: Request
) -> Response:
    """用户选择合并或保留两份（并排 UI 的落点）。"""
    try:
        result = await _store(request).resolve(
            note_id,
            pending_id,
            resolution=payload.resolution,
            merged_title=payload.title,
            merged_content=payload.contentMd,
        )
    except ConflictInvalid as exc:
        return _error(422, "invalid_conflict_request", str(exc))
    except ConflictNotFound:
        return _error(404, "conflict_not_found", "笔记或待决编辑不存在（或已解决）。")
    return JSONResponse(result)


@router.get("/api/v1/library/notes/{note_id}/conflict-log")
async def conflict_log(note_id: str, request: Request) -> Response:
    try:
        items = await _store(request).conflict_log(note_id)
    except ConflictNotFound:
        return _error(404, "note_not_found", "笔记不存在。")
    return JSONResponse({"noteId": note_id, "items": items})
