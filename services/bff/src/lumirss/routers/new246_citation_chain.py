"""NEW-246 资料来源链路由 — 手工引用边登记 / 链条追踪 / 解除。

- POST   /api/v1/citation-edges        登记「fromRef 引用了 toRef」（重复 → 409）；
- GET    /api/v1/citation-edges        边台账（?fromRef= 过滤可选）；
- GET    /api/v1/citation-chain        ?ref= 起点链条：只走显式登记的边，
       出边缺失 = 中间环节缺失（诚实标注，不推断未验证关系）；
- DELETE /api/v1/citation-edges/{id}   解除一条边。

负载非法 → 422 chain_invalid；重复边 → 409 chain_conflict。
per-user 库天然隔离。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new246_citation_chain import (
    ChainConflict,
    ChainInvalid,
    CitationChainStore,
)

router = APIRouter()


class CitationEdgeCreate(BaseModel):
    model_config = {"extra": "forbid"}

    fromRef: str = Field(min_length=1, max_length=300)
    toRef: str = Field(min_length=1, max_length=300)
    note: str = Field(default="", max_length=500)


def _store(request: Request) -> CitationChainStore:
    return CitationChainStore(request.app.state.db)


@router.post("/api/v1/citation-edges", status_code=201)
async def create_citation_edge(payload: CitationEdgeCreate, request: Request) -> Response:
    try:
        item = await _store(request).add_edge(payload.fromRef, payload.toRef, payload.note)
    except ChainInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "chain_invalid", "message": str(exc)}},
        )
    except ChainConflict:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "chain_conflict", "message": "这对引用关系已经登记过。"}},
        )
    return JSONResponse(status_code=201, content=item)


@router.get("/api/v1/citation-edges")
async def list_citation_edges(
    request: Request,
    fromRef: str | None = Query(default=None),
) -> Response:
    return JSONResponse({"items": await _store(request).list_edges(from_ref=fromRef)})


@router.delete("/api/v1/citation-edges/{edge_id}", status_code=204)
async def delete_citation_edge(edge_id: str, request: Request) -> Response:
    await _store(request).delete_edge(edge_id)
    return Response(status_code=204)


@router.get("/api/v1/citation-chain")
async def trace_citation_chain(
    request: Request,
    ref: str = Query(..., max_length=300),
) -> Response:
    try:
        result = await _store(request).trace_chain(ref)
    except ChainInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "chain_invalid", "message": str(exc)}},
        )
    return JSONResponse(result)
