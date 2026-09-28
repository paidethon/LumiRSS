"""NEW-240 笔记附件清单路由 — 添加 / 列表（含容量）/ 下载 / 移除。

- POST   /api/v1/library/notes/{note_id}/attachments
         {filename, mimeType?, contentBase64} → 201
- GET    /api/v1/library/notes/{note_id}/attachments → items + usage（容量）
- GET    /api/v1/library/notes/{note_id}/attachments/{id}/content → 字节流
- DELETE /api/v1/library/notes/{note_id}/attachments/{id} → 204（笔记文字保留）

限额：单文件 ≤256KB、每笔记 ≤1MB、≤10 个、同名拒绝（422）。
"""

import base64

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new240_note_attachments import (
    NoteAttachmentInvalid,
    NoteAttachmentNotFound,
    NoteAttachmentStore,
)

router = APIRouter()


class AttachmentCreate(BaseModel):
    model_config = {"extra": "forbid"}

    filename: str = Field(min_length=1, max_length=200)
    mimeType: str | None = Field(default=None, max_length=100)
    contentBase64: str = Field(min_length=1)


def _store(request: Request) -> NoteAttachmentStore:
    return NoteAttachmentStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/library/notes/{note_id}/attachments", status_code=201)
async def add_attachment(
    note_id: str, payload: AttachmentCreate, request: Request
) -> Response:
    try:
        content = base64.b64decode(payload.contentBase64, validate=True)
    except (ValueError, TypeError):
        return _error(422, "invalid_attachment", "contentBase64 不是合法的 base64。")
    try:
        item = await _store(request).add(
            note_id,
            filename=payload.filename,
            mime_type=payload.mimeType or "application/octet-stream",
            content=content,
        )
    except NoteAttachmentInvalid as exc:
        return _error(422, "invalid_attachment", str(exc))
    except NoteAttachmentNotFound:
        return _error(404, "note_not_found", "笔记不存在。")
    return JSONResponse(status_code=201, content=item)


@router.get("/api/v1/library/notes/{note_id}/attachments")
async def list_attachments(note_id: str, request: Request) -> Response:
    try:
        result = await _store(request).list_attachments(note_id)
    except NoteAttachmentNotFound:
        return _error(404, "note_not_found", "笔记不存在。")
    return JSONResponse(result)


@router.get("/api/v1/library/notes/{note_id}/attachments/{attachment_id}/content")
async def download_attachment(
    note_id: str, attachment_id: str, request: Request
) -> Response:
    try:
        item = await _store(request).get_content(note_id, attachment_id)
    except NoteAttachmentNotFound:
        return _error(404, "attachment_not_found", "附件不存在。")
    # Content-Disposition 只允许 latin-1：ASCII 回退 + RFC 5987 filename*
    from urllib.parse import quote

    filename = item["filename"]
    ascii_fallback = filename.encode("ascii", "ignore").decode() or "attachment"
    disposition = (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=item["content"],
        media_type=item["mimeType"],
        headers={"Content-Disposition": disposition},
    )


@router.delete(
    "/api/v1/library/notes/{note_id}/attachments/{attachment_id}", status_code=204
)
async def remove_attachment(
    note_id: str, attachment_id: str, request: Request
) -> Response:
    """移除附件（笔记正文不动）。"""
    removed = await _store(request).remove(note_id, attachment_id)
    if not removed:
        return _error(404, "attachment_not_found", "附件不存在。")
    return Response(status_code=204)
