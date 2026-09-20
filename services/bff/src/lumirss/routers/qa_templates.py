"""F030 问答模板 routes（CRUD；普通文本，不升级任何权限）。"""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.models import QaTemplate, QaTemplateList
from lumirss.qa_templates import (
    QaTemplateNotFound,
    QaTemplateStore,
)

router = APIRouter()


class QaTemplateCreate(BaseModel):
    """POST /api/v1/qa-templates body。"""

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=500)


class QaTemplateUpdate(BaseModel):
    """PATCH /api/v1/qa-templates/{id} body（重命名 + 可选改文本）。"""

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=60)
    text: str | None = Field(default=None, min_length=1, max_length=500)


def _store(request: Request) -> QaTemplateStore:
    from lumirss.deps import _cached_on_app_state

    return _cached_on_app_state(
        request,
        "qa_template_store",
        lambda: QaTemplateStore(request.app.state.db),
    )


@router.get("/api/v1/qa-templates", response_model=QaTemplateList)
async def list_qa_templates(request: Request) -> QaTemplateList:
    return QaTemplateList(items=[QaTemplate(**item) for item in await _store(request).list()])


@router.post("/api/v1/qa-templates", response_model=QaTemplate, status_code=201)
async def create_qa_template(payload: QaTemplateCreate, request: Request) -> QaTemplate:
    created = await _store(request).create(payload.name, payload.text)
    return QaTemplate(**created)


@router.patch("/api/v1/qa-templates/{template_id}", response_model=QaTemplate)
async def update_qa_template(
    template_id: str, payload: QaTemplateUpdate, request: Request
) -> QaTemplate:
    updated = await _store(request).rename(
        template_id, payload.name, payload.text
    )
    if updated is None:
        raise QaTemplateNotFound(template_id)
    return QaTemplate(**updated)


@router.delete("/api/v1/qa-templates/{template_id}", status_code=204)
async def delete_qa_template(template_id: str, request: Request) -> Response:
    deleted = await _store(request).delete(template_id)
    if not deleted:
        raise QaTemplateNotFound(template_id)
    return Response(status_code=204)
