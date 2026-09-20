"""F078 检索同义词路由 — CRUD + preview + 搜索参数并入。"""

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.search_index import split_terms
from lumirss.search_synonyms import (
    SynonymInvalid,
    SynonymStore,
    expand_terms,
)

router = APIRouter()


class SynonymBody(BaseModel):
    term: str = Field(min_length=1, max_length=50)
    expansions: list[str] = Field(min_length=1, max_length=8)
    enabled: bool = True


class SynonymPatch(BaseModel):
    expansions: list[str] | None = Field(default=None, min_length=1, max_length=8)
    enabled: bool | None = None


class SynonymPreviewBody(BaseModel):
    q: str = Field(min_length=1, max_length=200)


def _invalid(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_synonym", "message": str(exc)}},
    )


@router.get("/api/v1/search/synonyms")
async def list_synonyms(request: Request) -> dict[str, Any]:
    store = SynonymStore(request.app.state.db)
    return {"items": await store.list_synonyms()}


@router.post("/api/v1/search/synonyms")
async def create_synonym(payload: SynonymBody, request: Request) -> Any:
    store = SynonymStore(request.app.state.db)
    try:
        return await store.create(payload.term, payload.expansions, payload.enabled)
    except SynonymInvalid as exc:
        return _invalid(exc)


@router.patch("/api/v1/search/synonyms/{synonym_id}")
async def update_synonym(synonym_id: str, payload: SynonymPatch, request: Request) -> Any:
    store = SynonymStore(request.app.state.db)
    try:
        result = await store.update(synonym_id, expansions=payload.expansions, enabled=payload.enabled)
    except SynonymInvalid as exc:
        return _invalid(exc)
    if result is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "synonym_not_found", "message": "同义词不存在。"}},
        )
    return result


@router.delete("/api/v1/search/synonyms/{synonym_id}", status_code=204)
async def delete_synonym(synonym_id: str, request: Request) -> Response:
    deleted = await SynonymStore(request.app.state.db).delete(synonym_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "synonym_not_found", "message": "同义词不存在。"}},
        )
    return Response(status_code=204)


@router.post("/api/v1/search/synonyms/preview")
async def preview_synonyms(payload: SynonymPreviewBody, request: Request) -> dict[str, Any]:
    """与实际搜索同一扩展口径：返回命中同义词与扩展后的有效词表。"""
    from lumirss.search_synonyms import MAX_EFFECTIVE_TERMS

    store = SynonymStore(request.app.state.db)
    synonym_map = await store.load_enabled_map()
    terms = split_terms(payload.q.strip())
    matched = [
        {"term": term_folded, "expansions": expansions}
        for term_folded, expansions in synonym_map.items()
        if term_folded in [t.casefold() for t in terms]
    ]
    effective = expand_terms(terms, synonym_map)[:MAX_EFFECTIVE_TERMS]
    return {"matched": matched, "effectiveTerms": effective}
