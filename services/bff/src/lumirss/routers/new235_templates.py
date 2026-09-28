"""NEW-235 笔记模板填空路由 — 模板 CRUD + 笔记结构化填充。

- GET/POST /api/v1/note-templates；DELETE /api/v1/note-templates/{id}
- PUT/GET /api/v1/library/notes/{note_id}/template-fill

填充不改写笔记正文（自由文本区保留）；404/422 同既有口径。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new235_note_templates import (
    NoteTemplateInvalid,
    NoteTemplateNotFound,
    NoteTemplateStore,
)

router = APIRouter()


class TemplateCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    fields: list[dict[str, object]] = Field(min_length=1)


class TemplateFillPut(BaseModel):
    model_config = {"extra": "forbid"}

    templateId: str
    values: dict[str, str]


def _store(request: Request) -> NoteTemplateStore:
    return NoteTemplateStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/note-templates")
async def list_templates(request: Request) -> Response:
    return JSONResponse({"items": await _store(request).list_templates()})


@router.post("/api/v1/note-templates", status_code=201)
async def create_template(payload: TemplateCreate, request: Request) -> Response:
    try:
        template = await _store(request).create(payload.name, payload.fields)
    except NoteTemplateInvalid as exc:
        return _error(422, "invalid_note_template", str(exc))
    return JSONResponse(status_code=201, content=template)


@router.delete("/api/v1/note-templates/{template_id}", status_code=204)
async def delete_template(template_id: str, request: Request) -> Response:
    deleted = await _store(request).delete_template(template_id)
    if not deleted:
        return _error(404, "note_template_not_found", "模板不存在。")
    return Response(status_code=204)


@router.put("/api/v1/library/notes/{note_id}/template-fill")
async def put_template_fill(
    note_id: str, payload: TemplateFillPut, request: Request
) -> Response:
    """把结构化填充写到笔记上（content_md 不动——自由文本区保留）。"""
    try:
        result = await _store(request).fill_note(
            note_id, payload.templateId, payload.values
        )
    except NoteTemplateInvalid as exc:
        return _error(422, "invalid_note_template", str(exc))
    except NoteTemplateNotFound:
        return _error(404, "note_template_not_found", "模板或笔记不存在。")
    return JSONResponse(result)


@router.get("/api/v1/library/notes/{note_id}/template-fill")
async def get_template_fill(note_id: str, request: Request) -> Response:
    try:
        result = await _store(request).get_fill(note_id)
    except NoteTemplateNotFound:
        return _error(404, "note_template_not_found", "笔记不存在。")
    return JSONResponse(result)
