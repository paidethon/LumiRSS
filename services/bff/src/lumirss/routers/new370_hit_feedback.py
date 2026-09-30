"""NEW-370 搜索结果评注路由。

- POST /api/v1/search/feedback            标记某命中「有用/无关」+ 原因
- GET  /api/v1/search/feedback?q=         本查询的本人评注清单
- GET  /api/v1/search/ranking-scheme      排序方案状态（默认关闭）
- POST /api/v1/search/ranking-scheme      显式启用/停用（本人）
- GET  /api/v1/search/reranked?q=         启用后才有内容的有用优先顺序
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new370_hit_feedback import (
    FeedbackEntryMissing,
    list_feedback,
    record_feedback,
    reranked_hits,
    scheme_state,
    set_scheme,
)

router = APIRouter()


class FeedbackBody(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1, max_length=200)
    entryRef: str = Field(min_length=1, max_length=200)
    verdict: str = Field(pattern="^(useful|irrelevant)$")
    reason: str | None = Field(default=None, max_length=200)


@router.post("/api/v1/search/feedback", response_model=None)
async def post_feedback(payload: FeedbackBody, request: Request) -> JSONResponse:
    try:
        result = await record_feedback(
            request.app.state.db,
            query=payload.query.strip(),
            entry_ref=payload.entryRef,
            verdict=payload.verdict,
            reason=payload.reason,
        )
    except FeedbackEntryMissing:
        # own-scope 校验：不在本人投影的条目不可评注（404 同语义）。
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "search_entry_not_found",
                    "message": "条目不在当前账户的搜索索引中，无法评注。",
                }
            },
        )
    return JSONResponse(result, status_code=201)


@router.get("/api/v1/search/feedback", response_model=None)
async def get_feedback(
    request: Request, q: str = Query(min_length=1, max_length=200)
) -> JSONResponse:
    result = await list_feedback(request.app.state.db, query=q.strip())
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/api/v1/search/ranking-scheme", response_model=None)
async def get_ranking_scheme(request: Request) -> JSONResponse:
    result = await scheme_state(request.app.state.db)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


class SchemeBody(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool


@router.post("/api/v1/search/ranking-scheme", response_model=None)
async def post_ranking_scheme(
    payload: SchemeBody, request: Request
) -> JSONResponse:
    result = await set_scheme(request.app.state.db, enabled=payload.enabled)
    return JSONResponse(result)


@router.get("/api/v1/search/reranked", response_model=None)
async def get_reranked(
    request: Request, q: str = Query(min_length=1, max_length=200)
) -> JSONResponse:
    from lumirss.deps import _get_search_service

    service = _get_search_service(request)
    result = await reranked_hits(
        service, request.app.state.db, query=q.strip()
    )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
