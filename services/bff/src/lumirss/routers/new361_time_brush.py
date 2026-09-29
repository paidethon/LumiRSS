"""NEW-361 时间范围刷选路由。

GET /api/v1/search/time-brush —— 与 GET /search 相同的权限与过滤作用
域（per-user DB 路由 + 同一过滤链），窗口内逐桶实际命中计数在 SQL
完成。分布只由实际命中数据生成；选定区间后的文章列表由客户端复用
GET /search 的 from/to（本路由不搬运正文，只回计数）。
"""

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from lumirss.new361_time_brush import (
    TimeBrushInvalid,
    brush_buckets,
    resolve_window,
)
from lumirss.search_index import SearchQueryError, split_terms

router = APIRouter()


@router.get("/api/v1/search/time-brush", response_model=None)
async def search_time_brush(
    request: Request,
    q: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    feedUrl: str | None = None,
    categoryId: str | None = None,
    state: str | None = None,
    favorite: bool | None = None,
    intitle: str | None = None,
    phrase: str | None = None,
    exclude: str | None = None,
    hasSummary: bool | None = None,
) -> JSONResponse:
    """窗口内逐桶实际命中计数（≤92 天按日、更长按月；空桶补 0 仅
    为渲染，绝不伪造命中）。区间非法 / 超窗 → 400；查询为空 → 400。"""
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
    try:
        day_from, day_to, granularity = resolve_window(
            day_from_str=from_, day_to_str=to
        )
    except TimeBrushInvalid as exc:
        raise SearchQueryError(str(exc)) from exc

    service = _service(request)
    store = service.store
    await store.ensure_migrated()
    result: dict[str, Any] = await brush_buckets(
        store,
        terms=split_terms(query),
        day_from=day_from,
        day_to=day_to,
        granularity=granularity,
        intitle_terms=split_terms(intitle or "")[:2] or None,
        phrase=(phrase or "").strip() or None,
        exclude_terms=split_terms(exclude or "")[:2] or None,
        feed_url=feedUrl,
        category_id=categoryId,
        unread_only=state == "unread",
        starred_only=bool(favorite),
        # 区间本身即刷选窗口（SQL 里已按日/月分桶），不再叠加 from/to。
        published_from=None,
        published_to=None,
        has_summary=hasSummary,
    )
    return JSONResponse(
        {**result, "hint": "查看该区间文章请以 from/to 调用 GET /api/v1/search。"},
        headers={"Cache-Control": "no-store"},
    )


def _service(request: Request) -> Any:
    from lumirss.deps import _get_search_service

    return _get_search_service(request)
