"""NEW-365 搜索排除词建议审批路由。

- POST   /api/v1/search/exclusion-candidates   从标记为不相关的结果
         提取候选词（纯计数可解释；不落库、不自动生效）
- GET    /api/v1/search/exclusion-words?q=     本人已确认词（该查询）
- POST   /api/v1/search/exclusion-words        用户确认 → 写入（幂等）
- DELETE /api/v1/search/exclusion-words/{id}   撤销确认

确认词由客户端并进该查询的 exclude 参数（GET /search 既有能力）；
未确认的候选绝不进入任何查询。
"""

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new365_exclusion_words import (
    ExclusionWordInvalid,
    approve_word,
    approved_words,
    delete_word,
    exclusion_candidates,
)

router = APIRouter()


class CandidatesBody(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1, max_length=200)
    markedRefs: list[str] = Field(min_length=1, max_length=50)


@router.post("/api/v1/search/exclusion-candidates", response_model=None)
async def post_exclusion_candidates(
    payload: CandidatesBody, request: Request
) -> JSONResponse:
    result = await exclusion_candidates(
        request.app.state.db,
        query=payload.query.strip(),
        marked_refs=payload.markedRefs,
    )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/api/v1/search/exclusion-words", response_model=None)
async def get_exclusion_words(
    request: Request, q: str = Query(min_length=1, max_length=200)
) -> JSONResponse:
    result = await approved_words(
        request.app.state.db, query=q.strip()
    )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


class ApproveBody(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1, max_length=200)
    word: str = Field(min_length=1, max_length=24)


@router.post("/api/v1/search/exclusion-words", response_model=None)
async def post_exclusion_word(
    payload: ApproveBody, request: Request
) -> JSONResponse:
    try:
        result = await approve_word(
            request.app.state.db,
            query=payload.query.strip(),
            word=payload.word,
        )
    except ExclusionWordInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "word_invalid", "message": str(exc)}},
        )
    return JSONResponse(result, status_code=201)


@router.delete("/api/v1/search/exclusion-words/{word_id}", response_model=None)
async def delete_exclusion_word(word_id: int, request: Request) -> Response:
    if not await delete_word(request.app.state.db, word_id=word_id):
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "word_not_found", "message": "已确认词不存在。"}
            },
        )
    return Response(status_code=204)
