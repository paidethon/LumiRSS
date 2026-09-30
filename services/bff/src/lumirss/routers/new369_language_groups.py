"""NEW-369 个人资料语言筛选路由。

GET /api/v1/search/by-language —— 与 GET /search 同链命中的显式语言
分组（entry 更正 → 源更正 → 源记录 → unknown 单独呈现）。分组仅供
筛选；条目列表复用 GET /search。
"""

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from lumirss.new369_language_groups import language_groups
from lumirss.search_index import SearchQueryError

router = APIRouter()


@router.get("/api/v1/search/by-language", response_model=None)
async def search_by_language(
    request: Request,
    q: str,
    feedUrl: str | None = None,
    categoryId: str | None = None,
    state: str | None = None,
    favorite: bool | None = None,
    author: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    intitle: str | None = None,
    phrase: str | None = None,
    exclude: str | None = None,
    hasSummary: bool | None = None,
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
    params: dict[str, Any] = {
        "query": query,
        "feed_url": feedUrl,
        "category_id": categoryId,
        "unread_only": state == "unread",
        "starred_only": bool(favorite),
        "published_from": from_,
        "published_to": to,
        "intitle": intitle,
        "phrase": phrase,
        "exclude": exclude,
        "has_summary": hasSummary,
        "author": author,
    }
    # request.app.state.db 与 service 同库（per-user 路由）。
    result = await language_groups(service, request.app.state.db, params=params)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
