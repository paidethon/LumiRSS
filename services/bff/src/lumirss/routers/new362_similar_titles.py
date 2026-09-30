"""NEW-362 相似标题候选审阅路由。

- GET  /api/v1/search/similar-title-candidates?entryRef=  候选重复稿
       （可解释相似度：score / 共有二元组 / 片段样例；只列不改）
- POST /api/v1/search/similar-title-candidates/confirm    用户显式确认
       后才写入 item_relations（duplicate | reprint）

候选扫描与确认都在 per-user 库完成；A 的候选与确认对 B 不可见。
entryRef 不在本账户投影 → 统一 404（不泄露他人条目存在性）。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new362_similar_titles import confirm_candidate, scan_candidates
from lumirss.search_debug import SearchEntryNotFound

router = APIRouter()


def _db(request: Request):
    return request.app.state.db


@router.get("/api/v1/search/similar-title-candidates", response_model=None)
async def get_similar_title_candidates(
    request: Request,
    entryRef: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=8, ge=1, le=20),
) -> JSONResponse:
    result = await scan_candidates(
        _db(request), entry_ref=entryRef, limit=limit
    )
    if result is None:
        raise SearchEntryNotFound("条目不在当前账户的搜索索引中。")
    return JSONResponse(
        result, headers={"Cache-Control": "no-store"}
    )


class ConfirmBody(BaseModel):
    model_config = {"extra": "forbid"}

    aRef: str = Field(min_length=1, max_length=200)
    bRef: str = Field(min_length=1, max_length=200)
    relation: str = Field(pattern="^(duplicate|reprint)$")
    note: str | None = Field(default=None, max_length=200)


@router.post("/api/v1/search/similar-title-candidates/confirm", response_model=None)
async def confirm_similar_title_candidate(
    payload: ConfirmBody, request: Request
) -> JSONResponse:
    if payload.aRef == payload.bRef:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "same_entry",
                    "message": "条目不能与自身组队。",
                }
            },
        )
    try:
        result = await confirm_candidate(
            _db(request),
            a_ref=payload.aRef,
            b_ref=payload.bRef,
            relation=payload.relation,
            note=payload.note,
        )
    except KeyError as exc:
        raise SearchEntryNotFound(
            "条目不在当前账户的搜索索引中，无法确认。"
        ) from exc
    return JSONResponse(result, status_code=201)
