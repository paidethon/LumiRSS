"""NEW-254 研究术语表路由 — 项目内术语 CRUD + 只读查词。

- /projects/{id}/glossary（GET/POST）、/glossary/lookup?term=…（GET）
- /glossary-terms/{id}（PATCH/DELETE）

查词是文章阅读时主动调出的只读动作；查不到 → found=false（诚实空态）。
与全局词典（glossary 表）零交互。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new251_research import ProjectNotFound, ResearchInvalid
from lumirss.new254_project_glossary import (
    ResearchGlossaryStore,
    TermConflict,
    TermNotFound,
)

router = APIRouter()


class TermCreate(BaseModel):
    model_config = {"extra": "forbid"}

    term: str
    interpretation: str
    source: str | None = None


class TermPatch(BaseModel):
    model_config = {"extra": "forbid"}

    interpretation: str | None = None
    source: str | None = None


def _store(request: Request) -> ResearchGlossaryStore:
    return ResearchGlossaryStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/research/projects/{project_id}/glossary")
async def list_terms(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).list(project_id))
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")


@router.post("/api/v1/research/projects/{project_id}/glossary", status_code=201)
async def create_term(project_id: str, payload: TermCreate, request: Request) -> Response:
    try:
        term = await _store(request).create(
            project_id, term=payload.term, interpretation=payload.interpretation, source=payload.source
        )
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")
    except TermConflict as exc:
        return _error(409, "research_term_conflict", f"该项目已有术语「{exc}」。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=term)


@router.get("/api/v1/research/projects/{project_id}/glossary/lookup")
async def lookup_term(project_id: str, request: Request, term: str) -> Response:
    try:
        return JSONResponse(await _store(request).lookup(project_id, term=term))
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.patch("/api/v1/research/glossary-terms/{term_id}")
async def patch_term(term_id: str, payload: TermPatch, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).update(term_id, interpretation=payload.interpretation, source=payload.source)
        )
    except TermNotFound:
        return _error(404, "research_term_not_found", "术语不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.delete("/api/v1/research/glossary-terms/{term_id}", status_code=204)
async def delete_term(term_id: str, request: Request) -> Response:
    try:
        await _store(request).delete(term_id)
    except TermNotFound:
        return _error(404, "research_term_not_found", "术语不存在。")
    return Response(status_code=204)
