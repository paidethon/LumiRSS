"""F023 跨来源作者聚合 routes。

- GET /api/v1/authors：按作者精确值聚合条目数（空 author 排除；
  别名经用户显式声明后并入 canonical 计数）；
- GET /api/v1/authors/items?author=：某作者（含别名）的条目分页；
- POST/GET/DELETE /api/v1/authors/aliases：显式别名管理。

规范名展示 = 分组 key（canonical）；撤销合并 = 删除别名行。
"""

from fastapi import APIRouter, Request, Response

from lumirss.author_aggregates import (
    AuthorAggregateStore,
    AuthorAliasInvalid,
    AuthorAliasNotFound,
)
from lumirss.models import (
    AuthorAlias,
    AuthorAliasCreate,
    AuthorAliasList,
    AuthorItemsResponse,
    AuthorList,
    AuthorSummary,
    EntryListItem,
)
from lumirss.search_index import SearchQueryError

router = APIRouter()


def _store(request: Request) -> AuthorAggregateStore:
    from lumirss.deps import _cached_on_app_state

    return _cached_on_app_state(
        request,
        "author_alias_store",
        lambda: AuthorAggregateStore(request.app.state.db),
    )


def _item_model(row) -> EntryListItem:
    return EntryListItem(
        entryRef=str(row["entry_ref"]),
        title=str(row["title"]),
        feedTitle=str(row["feed_title"]),
        author=str(row["author"]) if row["author"] else None,
        url=str(row["url"]) if row["url"] else None,
        publishedAt=str(row["published_at"]),
        read=bool(row["read"]),
        starred=bool(row["starred"]),
        feedUrl=str(row["feed_url"]),
        snippet=str(row["content_text"] or "")[:160],
    )


@router.get("/api/v1/authors", response_model=AuthorList)
async def list_authors(request: Request, limit: int = 50, offset: int = 0) -> AuthorList:
    items = await _store(request).list_authors(limit=limit, offset=offset)
    return AuthorList(items=[AuthorSummary(**item) for item in items])


@router.get("/api/v1/authors/items", response_model=AuthorItemsResponse)
async def author_items(
    request: Request, author: str, limit: int = 20, offset: int = 0
) -> AuthorItemsResponse:
    clean = author.strip()
    if not clean:
        raise SearchQueryError("author 不能为空。")
    rows = await _store(request).author_items(clean, limit=limit, offset=offset)
    return AuthorItemsResponse(
        author=clean,
        items=[_item_model(row) for row in rows],
        hasMore=len(rows) >= max(1, min(limit, 100)),
    )


@router.post("/api/v1/authors/aliases", response_model=AuthorAlias, status_code=201)
async def create_author_alias(payload: AuthorAliasCreate, request: Request) -> AuthorAlias:
    created = await _store(request).create_alias(payload.alias, payload.canonical)
    return AuthorAlias(**created)


@router.get("/api/v1/authors/aliases", response_model=AuthorAliasList)
async def list_author_aliases(request: Request) -> AuthorAliasList:
    return AuthorAliasList(
        items=[AuthorAlias(**item) for item in await _store(request).list_aliases()]
    )


@router.delete("/api/v1/authors/aliases/{alias}", status_code=204)
async def delete_author_alias(alias: str, request: Request) -> Response:
    from urllib.parse import unquote

    deleted = await _store(request).delete_alias(unquote(alias))
    if not deleted:
        raise AuthorAliasNotFound(alias)
    return Response(status_code=204)


_ = (AuthorAliasInvalid,)  # mapped in errors.py
