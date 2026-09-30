"""NEW-368 相近拼写搜索提示路由。

GET /api/v1/search/spell-suggestions?q= —— 同链真实命中为 0 时给出
可选拼写候选（编辑距离 ≤2，来自本人索引标题词表）；有命中时候选
恒为空。只建议、不自动替换用户查询。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from lumirss.new368_spell import spell_suggestions
from lumirss.search_index import SearchQueryError

router = APIRouter()


@router.get("/api/v1/search/spell-suggestions", response_model=None)
async def get_spell_suggestions(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    feedUrl: str | None = None,
    categoryId: str | None = None,
    state: str | None = None,
    favorite: bool | None = None,
) -> JSONResponse:
    query = q.strip()
    if not query:
        raise SearchQueryError("Search query is empty.")
    if len(query) > 200:
        raise SearchQueryError("Search query is too long.")
    if feedUrl is not None and categoryId is not None:
        raise SearchQueryError(
            "feedUrl and categoryId are mutually exclusive."
        )
    if state is not None and state != "unread":
        raise SearchQueryError('state only supports "unread".')

    from lumirss.deps import _get_search_service

    service = _get_search_service(request)
    result = await spell_suggestions(
        service.store,
        query=query,
        feed_url=feedUrl,
        category_id=categoryId,
        unread_only=state == "unread",
        starred_only=bool(favorite),
    )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
