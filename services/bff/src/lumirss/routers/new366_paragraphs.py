"""NEW-366 段落级搜索结果路由。

- GET    /api/v1/search/paragraphs?entryRef=&q=   命中段落列表
- POST   /api/v1/search/fragments                 保存选中片段
- GET    /api/v1/search/fragments                 已存片段（可按 ref 过滤）
- DELETE /api/v1/search/fragments/{id}            删除片段
"""

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new366_paragraphs import (
    FragmentEntryMissing,
    delete_fragment,
    list_fragments,
    paragraph_hits,
    save_fragment,
)
from lumirss.search_debug import SearchEntryNotFound
from lumirss.search_index import SearchQueryError

router = APIRouter()


@router.get("/api/v1/search/paragraphs", response_model=None)
async def get_paragraph_hits(
    request: Request,
    entryRef: str = Query(min_length=1, max_length=200),
    q: str = Query(min_length=1, max_length=200),
) -> JSONResponse:
    query = q.strip()
    if not query:
        raise SearchQueryError("Search query is empty.")
    result = await paragraph_hits(
        request.app.state.db, entry_ref=entryRef, query=query
    )
    if result is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "search_entry_not_found",
                    "message": "条目不在当前账户的搜索索引中。",
                }
            },
        )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


class FragmentBody(BaseModel):
    model_config = {"extra": "forbid"}

    entryRef: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=200)
    paragraphIndex: int = Field(ge=0, le=100000)
    text: str = Field(min_length=1, max_length=400)


@router.post("/api/v1/search/fragments", response_model=None)
async def post_fragment(payload: FragmentBody, request: Request) -> JSONResponse:
    try:
        result = await save_fragment(
            request.app.state.db,
            entry_ref=payload.entryRef,
            query=payload.query.strip(),
            paragraph_index=payload.paragraphIndex,
            text=payload.text,
        )
    except FragmentEntryMissing as exc:
        raise SearchEntryNotFound(
            "条目不在当前账户的搜索索引中，无法保存片段。"
        ) from exc
    except OverflowError as exc:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "fragment_cap", "message": str(exc)}},
        )
    return JSONResponse(result, status_code=201)


@router.get("/api/v1/search/fragments", response_model=None)
async def get_fragments(
    request: Request,
    entryRef: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=200),
) -> JSONResponse:
    result = await list_fragments(
        request.app.state.db, entry_ref=entryRef, limit=limit
    )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.delete("/api/v1/search/fragments/{fragment_id}", response_model=None)
async def delete_one_fragment(
    fragment_id: int, request: Request
) -> Response:
    if not await delete_fragment(request.app.state.db, fragment_id=fragment_id):
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "fragment_not_found", "message": "片段不存在。"}
            },
        )
    return Response(status_code=204)
