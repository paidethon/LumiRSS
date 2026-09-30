"""NEW-363 跨字段命中说明路由。

POST /api/v1/search/field-hits —— 对一页结果（≤50 ref）逐条归位命中
字段：标题 / 正文 / 作者 / 来源 / 本人笔记。本人笔记列读 per-user
annotations；missing（不在本账户投影）如实返回，不泄露存在性。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new363_field_hits import field_hits
from lumirss.search_index import SearchQueryError

router = APIRouter()


class FieldHitsBody(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1, max_length=200)
    entryRefs: list[str] = Field(min_length=1, max_length=50)


@router.post("/api/v1/search/field-hits", response_model=None)
async def post_field_hits(payload: FieldHitsBody, request: Request) -> JSONResponse:
    query = payload.query.strip()
    if not query:
        raise SearchQueryError("Search query is empty.")
    result = await field_hits(
        request.app.state.db,
        query=query,
        entry_refs=payload.entryRefs,
    )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
