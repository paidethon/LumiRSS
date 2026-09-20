"""F21 个人术语本路由（CRUD + 搜索）。"""

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.glossary import GlossaryInvalid, GlossaryNotFound, GlossaryStore
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


# -- F028 术语表批量导入导出 --------------------------------------------------


class GlossaryImportTerm(BaseModel):
    term: str = Field(min_length=1, max_length=100)
    translation: str = Field(min_length=1, max_length=500)


class GlossaryImportBody(BaseModel):
    """POST /api/v1/glossary/import body。"""

    model_config = {"extra": "forbid"}

    # 逐条结构校验在 glossary_io._clean_pair：坏条目进 errors[]，不整体 422。
    terms: list[object] = Field(max_length=500)
    mode: Literal["skip", "overwrite"] = "skip"


class GlossaryImportTermError(BaseModel):
    index: int
    reason: str


class GlossaryImportResult(BaseModel):
    imported: int
    skipped: int
    overwritten: int
    errors: list[GlossaryImportTermError]


@router.post("/api/v1/glossary/import", response_model=GlossaryImportResult)
async def import_glossary(payload: GlossaryImportBody, request: Request) -> GlossaryImportResult:
    """批量导入（skip/overwrite；非法条目逐条 errors，不整体失败）。"""
    from lumirss.glossary_io import GlossaryImportInvalid, import_terms

    try:
        result = await import_terms(
            request.app.state.db,
            list(payload.terms),
            payload.mode,
        )
    except GlossaryImportInvalid as exc:
        raise GlossaryInvalid(str(exc)) from exc
    return GlossaryImportResult(
        imported=result["imported"],
        skipped=result["skipped"],
        overwritten=result["overwritten"],
        errors=[GlossaryImportTermError(**err) for err in result["errors"]],
    )


@router.get("/api/v1/glossary/export")
async def export_glossary(request: Request) -> Response:
    """JSON 文件下载（application/json；Content-Disposition attachment）。"""
    import json as _json

    from lumirss.glossary_io import export_terms

    payload = await export_terms(request.app.state.db)
    content = _json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="lumirss-glossary.json"'},
    )


# -- F029 术语命中预览 --------------------------------------------------------


@router.post("/api/v1/entries/{entry_ref}/glossary-hits")
async def glossary_hits_for_entry(entry_ref: str, request: Request) -> dict:
    """现役 glossary 在本文正文的命中（预览与生成 prompt 同一函数产出）。"""
    from lumirss.deps import _get_adapter
    from lumirss.entryref import decode_entry_ref
    from lumirss.glossary_hits import (
        compute_hits,
        format_glossary_prompt_block,
        load_glossary_terms,
    )

    decode_entry_ref(entry_ref)  # 400 on malformed refs
    adapter = _get_adapter(request)
    detail = await adapter.get_entry(decode_entry_ref(entry_ref))
    terms = await load_glossary_terms(request.app.state.db)
    hits = compute_hits(detail.contentText, terms)
    return {
        "hits": hits,
        "promptBlock": format_glossary_prompt_block(hits),
    }
