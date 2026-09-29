"""NEW-245 引文出处补全路由 — 登记 / 查看 / 逐项补充 / 撤销补充。

- POST   /api/v1/citations                                     登记（原始值；重复 → 409）；
- GET    /api/v1/citations                                     列表（原始/补充/生效三分）；
- GET    /api/v1/citations/{citation_ref}                      单条详情；
- PUT    /api/v1/citations/{citation_ref}/supplements/{field}   补充 author/date；
- DELETE /api/v1/citations/{citation_ref}/supplements/{field}   撤销补充（原始值不动）。

负载非法 → 422 citation_invalid；未登记 → 404 citation_not_found；
重复登记 → 409 citation_conflict（保原始值不被覆盖）。per-user 库天然隔离。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new245_citation_fields import (
    CitationConflict,
    CitationFieldStore,
    CitationInvalid,
    CitationNotFound,
)

router = APIRouter()


class CitationRegister(BaseModel):
    model_config = {"extra": "forbid"}

    citationRef: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    dateValue: str | None = Field(default=None, max_length=500)


class CitationSupplementPut(BaseModel):
    model_config = {"extra": "forbid"}

    value: str = Field(min_length=1, max_length=500)


def _store(request: Request) -> CitationFieldStore:
    return CitationFieldStore(request.app.state.db)


def _error(status: int, kind: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"type": kind, "message": message}})


@router.post("/api/v1/citations", status_code=201)
async def register_citation(payload: CitationRegister, request: Request) -> Response:
    try:
        item = await _store(request).register(
            payload.citationRef, payload.title, payload.author, payload.dateValue
        )
    except CitationInvalid as exc:
        return _error(422, "citation_invalid", str(exc))
    except CitationConflict:
        return _error(409, "citation_conflict", "该引用已登记过；原始值不会被覆盖。")
    return JSONResponse(status_code=201, content=item)


@router.get("/api/v1/citations")
async def list_citations(request: Request) -> Response:
    return JSONResponse(await _store(request).list_all())


@router.get("/api/v1/citations/{citation_ref}")
async def get_citation(citation_ref: str, request: Request) -> Response:
    try:
        item = await _store(request).get(citation_ref)
    except CitationNotFound:
        return _error(404, "citation_not_found", "该引用没有登记记录。")
    return JSONResponse(item)


@router.put("/api/v1/citations/{citation_ref}/supplements/{field}")
async def put_supplement(
    citation_ref: str, field: str, payload: CitationSupplementPut, request: Request
) -> Response:
    try:
        item = await _store(request).put_supplement(citation_ref, field, payload.value)
    except CitationInvalid as exc:
        return _error(422, "citation_invalid", str(exc))
    except CitationNotFound:
        return _error(404, "citation_not_found", "该引用没有登记记录，先登记再补充。")
    return JSONResponse(item)


@router.delete("/api/v1/citations/{citation_ref}/supplements/{field}", status_code=204)
async def delete_supplement(citation_ref: str, field: str, request: Request) -> Response:
    try:
        await _store(request).delete_supplement(citation_ref, field)
    except CitationInvalid as exc:
        return _error(422, "citation_invalid", str(exc))
    return Response(status_code=204)
