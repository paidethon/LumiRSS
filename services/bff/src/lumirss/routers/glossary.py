"""F21 个人术语本路由（CRUD + 搜索）。"""

from fastapi import APIRouter, Request, Response

from lumirss.glossary import GlossaryNotFound, GlossaryStore
from lumirss.models import (
    GlossaryTerm,
    GlossaryTermCreate,
    GlossaryTermList,
)

router = APIRouter()


def _store(request: Request) -> GlossaryStore:
    return GlossaryStore(request.app.state.db)


def _model(entry: dict) -> GlossaryTerm:
    return GlossaryTerm(**entry)


@router.get("/api/v1/glossary", response_model=GlossaryTermList)
async def list_glossary(request: Request, q: str | None = None, limit: int = 100) -> GlossaryTermList:
    items = await _store(request).list_terms(q=q, limit=limit)
    return GlossaryTermList(items=[_model(item) for item in items])


@router.post("/api/v1/glossary", response_model=GlossaryTerm, status_code=201)
async def create_glossary_term(payload: GlossaryTermCreate, request: Request) -> GlossaryTerm:
    return _model(
        await _store(request).create(
            payload.term, payload.definition, payload.sourceRef
        )
    )


@router.patch("/api/v1/glossary/{term_id}", response_model=GlossaryTerm)
async def update_glossary_term(
    term_id: str, payload: GlossaryTermCreate, request: Request
) -> GlossaryTerm:
    result = await _store(request).update(term_id, payload.term, payload.definition)
    if result is None:
        raise GlossaryNotFound(term_id)
    return _model(result)


@router.delete("/api/v1/glossary/{term_id}", status_code=204)
async def delete_glossary_term(term_id: str, request: Request) -> Response:
    deleted = await _store(request).delete(term_id)
    if not deleted:
        raise GlossaryNotFound(term_id)
    return Response(status_code=204)
