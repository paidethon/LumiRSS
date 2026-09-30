"""NEW-364 作者与来源交叉筛选路由。

GET /api/v1/search/author-source —— 与 GET /search 相同的过滤链上的
facet 计数（标准 facet 语义，每个计数都可解释）：

- authors：在当前链（含 feedUrl/category 等全部条件、不含 author）
  下按作者分组的实际命中数——每个值展示「选它再加进组合会剩多少」；
- sources：在当前链（含 author、不含 feedUrl）下按来源分组的实际
  命中数；
- total：当前链（含 author 与 feedUrl 两者）的真实总数。

计数全部 SQL GROUP BY（正文不出站）；候选 ≤20 条 + 超界 honest 标注
（limit 取 n+1 探测，与 N145 同一口径）。
"""

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from lumirss.search_index import SearchQueryError, split_terms

router = APIRouter()

_FACET_LIMIT = 21  # n+1 探测截断；回 20 + complete 标注


def _common(
    *,
    terms: list[str],
    intitle: str | None,
    phrase: str | None,
    exclude: str | None,
    category_id: str | None,
    state: str | None,
    favorite: bool | None,
    from_: str | None,
    to: str | None,
    has_summary: bool | None,
) -> dict[str, Any]:
    return dict(
        terms=terms,
        intitle_terms=split_terms(intitle or "")[:2] or None,
        phrase=(phrase or "").strip() or None,
        exclude_terms=split_terms(exclude or "")[:2] or None,
        category_id=category_id,
        unread_only=state == "unread",
        starred_only=bool(favorite),
        published_from=from_,
        published_to=to,
        has_summary=has_summary,
    )


@router.get("/api/v1/search/author-source", response_model=None)
async def search_author_source(
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

    store = _service(request).store
    await store.ensure_migrated()
    common = _common(
        terms=split_terms(query),
        intitle=intitle,
        phrase=phrase,
        exclude=exclude,
        category_id=categoryId,
        state=state,
        favorite=favorite,
        from_=from_,
        to=to,
        has_summary=hasSummary,
    )
    # authors facet：不含 author（每个候选 = 加上它之后的真实数量）。
    author_rows = await store.distribution_authors(
        **common, feed_url=feedUrl, author=None, limit=_FACET_LIMIT
    )
    # sources facet：不含 feedUrl（含 author——交叉组合的另一半）。
    source_rows = await store.distribution_sources(
        **common, feed_url=None, author=author, limit=_FACET_LIMIT
    )
    total = await store.distribution_total(
        **common, feed_url=feedUrl, author=author
    )
    return JSONResponse(
        {
            "total": total,
            "authors": [
                {"author": str(row["author"]), "count": int(row["n"])}
                for row in author_rows[:20]
            ],
            "authorsComplete": len(author_rows) <= 20,
            "sources": [
                {
                    "feedUrl": str(row["feed_url"]),
                    "feedTitle": str(row["feed_title"]),
                    "count": int(row["n"]),
                }
                for row in source_rows[:20]
            ],
            "sourcesComplete": len(source_rows) <= 20,
            "selected": {"author": author, "feedUrl": feedUrl},
            "note": (
                "作者计数不含当前作者过滤、来源计数不含当前来源过滤："
                "每个数字 = 勾选该项后组合的真实命中数。"
            ),
        },
        headers={"Cache-Control": "no-store"},
    )


def _service(request: Request) -> Any:
    from lumirss.deps import _get_search_service

    return _get_search_service(request)
