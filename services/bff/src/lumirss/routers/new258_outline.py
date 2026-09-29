"""NEW-258 研究大纲编排路由 — 章节 / 素材 / Markdown 草稿。

- /projects/{id}/outline（GET）、/outline-draft（GET 只读生成）
- /projects/{id}/outline-sections（POST）、/outline-sections/{id}（PATCH/DELETE）
- /outline-sections/{id}/move（POST direction=up|down）
- /outline-sections/{id}/items（POST）、/outline-items/{id}（PATCH/DELETE）
- /outline-items/{id}/move（POST）、/outline-items/{id}/assign（POST）

排序诚实边界：上移/下移 + 跨章节分配，不是拖拽；响应 note 如实说明。
quote（选定引文）必须写明出处（citation）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new251_research import ProjectNotFound, ResearchInvalid
from lumirss.new258_outline import OutlineNotFound, OutlineStore

router = APIRouter()


class SectionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str


class SectionPatch(BaseModel):
    model_config = {"extra": "forbid"}

    title: str


class MoveBody(BaseModel):
    model_config = {"extra": "forbid"}

    direction: str


class OutlineItemCreate(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str
    content: str
    citation: str | None = None


class OutlineItemPatch(BaseModel):
    model_config = {"extra": "forbid"}

    content: str | None = None
    citation: str | None = None


class AssignBody(BaseModel):
    model_config = {"extra": "forbid"}

    targetSectionId: str


def _store(request: Request) -> OutlineStore:
    return OutlineStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/research/projects/{project_id}/outline")
async def get_outline(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).get(project_id))
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")


@router.get("/api/v1/research/projects/{project_id}/outline-draft")
async def get_outline_draft(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).draft_markdown(project_id))
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")


@router.post("/api/v1/research/projects/{project_id}/outline-sections", status_code=201)
async def add_section(project_id: str, payload: SectionCreate, request: Request) -> Response:
    try:
        section = await _store(request).add_section(project_id, title=payload.title)
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=section)


@router.patch("/api/v1/research/outline-sections/{section_id}")
async def rename_section(section_id: str, payload: SectionPatch, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).rename_section(section_id, title=payload.title))
    except OutlineNotFound:
        return _error(404, "research_outline_not_found", "章节不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.delete("/api/v1/research/outline-sections/{section_id}", status_code=204)
async def delete_section(section_id: str, request: Request) -> Response:
    try:
        await _store(request).delete_section(section_id)
    except OutlineNotFound:
        return _error(404, "research_outline_not_found", "章节不存在。")
    return Response(status_code=204)


@router.post("/api/v1/research/outline-sections/{section_id}/move")
async def move_section(section_id: str, payload: MoveBody, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).move_section(section_id, direction=payload.direction)
        )
    except OutlineNotFound:
        return _error(404, "research_outline_not_found", "章节不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.post("/api/v1/research/outline-sections/{section_id}/items", status_code=201)
async def add_item(section_id: str, payload: OutlineItemCreate, request: Request) -> Response:
    try:
        item = await _store(request).add_item(
            section_id, kind=payload.kind, content=payload.content, citation=payload.citation
        )
    except OutlineNotFound:
        return _error(404, "research_outline_not_found", "章节不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=item)


@router.patch("/api/v1/research/outline-items/{item_id}")
async def patch_item(item_id: str, payload: OutlineItemPatch, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).update_item(item_id, content=payload.content, citation=payload.citation)
        )
    except OutlineNotFound:
        return _error(404, "research_outline_item_not_found", "素材不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.delete("/api/v1/research/outline-items/{item_id}", status_code=204)
async def delete_item(item_id: str, request: Request) -> Response:
    try:
        await _store(request).delete_item(item_id)
    except OutlineNotFound:
        return _error(404, "research_outline_item_not_found", "素材不存在。")
    return Response(status_code=204)


@router.post("/api/v1/research/outline-items/{item_id}/move")
async def move_item(item_id: str, payload: MoveBody, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).move_item(item_id, direction=payload.direction))
    except OutlineNotFound:
        return _error(404, "research_outline_item_not_found", "素材不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.post("/api/v1/research/outline-items/{item_id}/assign")
async def assign_item(item_id: str, payload: AssignBody, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).assign_item(item_id, target_section_id=payload.targetSectionId)
        )
    except OutlineNotFound:
        return _error(404, "research_outline_not_found", "章节或素材不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
