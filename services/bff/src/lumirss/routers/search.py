"""Global search routes (0022).

GET /api/v1/search — one page of hits over the derived projection.
POST /api/v1/search/rebuild — explicit bounded rebuild (admin op).

Every parameter is validated here; the projection query itself is a
single static statement (see search_store.py). Snippets are plain text
extracted from the sanitized content text — the web client renders
them as text, never as HTML.
"""

import time
from typing import Any

from fastapi import APIRouter, Request, Response

from lumirss.models import (
    SavedSearchCreate,
    SavedSearchList,
    SavedSearchRename,
    SavedSearchView,
    SearchRebuildResult,
    SearchResponse,
)
from lumirss.saved_search_store import (
    SavedSearchNotFound,
    SavedSearchStore,
)
from lumirss.search_index import (
    SearchQueryError,
    decode_search_cursor,
    encode_search_cursor,
)
from lumirss.search_library import (
    decode_library_search_cursor,
    encode_library_search_cursor,
)

from ..deps import _get_search_service

router = APIRouter()

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50


@router.get(
    "/api/v1/search",
    response_model=SearchResponse,
    response_model_exclude_none=False,
)
async def search(
    request: Request,
    q: str,
    cursor: str | None = None,
    libraryCursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    feedUrl: str | None = None,
    categoryId: str | None = None,
    state: str | None = None,
    favorite: bool | None = None,
    from_: str | None = None,
    to: str | None = None,
) -> SearchResponse:
    """Global search over the derived projection.

    ``q`` is required (1-200 chars, at most 4 whitespace-split terms).
    ``state`` accepts "unread" (default: all); ``favorite`` filters
    starred entries; ``from``/``to`` are inclusive/exclusive ISO dates
    (YYYY-MM-DD). ``categoryId``/``feedUrl`` scope the search; the two
    are mutually exclusive.

    Each leg paginates independently: ``cursor`` keys the RSS leg,
    ``libraryCursor`` the library leg; both cursors are bound to the
    query scope and rejected (400) on mismatch. A ``null`` cursor next
    to a non-null ``libraryCursor`` means the RSS leg is exhausted.
    """
    service = _get_search_service(request)
    query = q.strip()
    if not query:
        raise SearchQueryError("Search query is empty.")
    if len(query) > 200:
        raise SearchQueryError("Search query is too long.")
    if limit < 1 or limit > _MAX_LIMIT:
        raise SearchQueryError(
            f"limit must be between 1 and {_MAX_LIMIT}."
        )
    if feedUrl is not None and categoryId is not None:
        raise SearchQueryError(
            "feedUrl and categoryId are mutually exclusive."
        )
    unread_only = False
    if state is not None:
        if state != "unread":
            raise SearchQueryError('state only supports "unread".')
        unread_only = True
    started = time.time()
    rss_scope: dict[str, Any] = {
        "q": query,
        "feedUrl": feedUrl,
        "categoryId": categoryId,
        "unread": unread_only,
        "favorite": bool(favorite),
        "from": from_,
        "to": to,
    }
    library_scope: dict[str, Any] = {"q": query, "favorite": bool(favorite)}
    # Cursor decoding happens outside the per-leg try blocks: a bad or
    # scope-mismatched cursor is a client error (400), never a silent
    # "library temporarily unavailable" string.
    keyset = (
        decode_search_cursor(cursor, scope=rss_scope)
        if cursor is not None
        else None
    )
    library_keyset = (
        decode_library_search_cursor(libraryCursor, scope=library_scope)
        if libraryCursor is not None
        else None
    )
    result: dict[str, Any]
    if cursor is None and libraryCursor is not None:
        # Page contract: only the library leg continues.
        result = {
            "rows": [],
            "hasMore": False,
            "nextKeyset": None,
        }
    else:
        result = await service.search(
            query=query,
            limit=limit,
            keyset=keyset,
            feed_url=feedUrl,
            category_id=categoryId,
            unread_only=unread_only,
            starred_only=bool(favorite),
            published_from=from_,
            published_to=to,
        )
    next_cursor = None
    if result["hasMore"] and result["nextKeyset"] is not None:
        next_cursor = encode_search_cursor(
            *result["nextKeyset"], scope=rss_scope
        )
    index = await service.index_info()
    # phase2 G6 unified view: the library leg runs beside the RSS leg and
    # fails independently (partial failure stays honest, never silent).
    # A starred (favorite) filter applies to BOTH legs (P0-10j) and is
    # pushed into SQL before LIMIT (pool #11), with its own keyset
    # cursor so hits beyond the first slice stay reachable (pool #10).
    library_items = None
    library_error = None
    library_next_cursor = None
    library_has_more = False
    try:
        from lumirss.deps import _get_library_search_writer
        from lumirss.models import LibrarySearchItem

        writer = _get_library_search_writer(request)
        hits, library_has_more = await writer.search_page(
            query,
            limit=limit,
            favorite_only=bool(favorite),
            keyset=library_keyset,
        )
        if library_has_more and hits:
            last = hits[-1]
            library_next_cursor = encode_library_search_cursor(
                str(last["updated_at"]),
                str(last["ref"]),
                scope=library_scope,
            )
        library_items = [
            LibrarySearchItem(
                ref=str(hit["ref"]),
                kind=str(hit["kind"]),
                title=str(hit["title"]),
                url=hit["url"],
                snippet=str(hit["body"])[:160],
                updatedAt=str(hit["updated_at"]),
            )
            for hit in hits
        ]
    except Exception:  # noqa: BLE001 — leg failure must not kill RSS
        library_error = "库搜索暂不可用，RSS 结果不受影响。"
    return SearchResponse(
        items=result["rows"],
        nextCursor=next_cursor,
        hasMore=result["hasMore"],
        elapsedMs=int((time.time() - started) * 1000),
        index=index,
        library=library_items,
        libraryError=library_error,
        libraryNextCursor=library_next_cursor,
        libraryHasMore=library_has_more,
    )


@router.post("/api/v1/search/rebuild", response_model=SearchRebuildResult)
async def rebuild_index(request: Request) -> SearchRebuildResult:
    """Rebuild the projection from FreshRSS (bounded, honest stats)."""
    service = _get_search_service(request)
    report = await service.rebuild()
    return SearchRebuildResult(
        entryCount=report["entryCount"],
        pages=report["pages"],
        partial=report["partial"],
        elapsedMs=report["elapsedMs"],
    )


# -- Saved search views (pool #09) ------------------------------------------


def _get_saved_search_store(request: Request) -> SavedSearchStore:
    from lumirss.deps import _cached_on_app_state

    return _cached_on_app_state(
        request,
        "saved_search_store",
        lambda: SavedSearchStore(request.app.state.db),
    )


def _saved_model(row: dict[str, Any]) -> SavedSearchView:
    return SavedSearchView(
        id=row["id"],
        name=row["name"],
        query=row["query"],
        view=row["params"].get("view", "all"),
        categoryKey=row["params"].get("categoryKey", ""),
        createdAt=row["createdAt"],
        updatedAt=row["updatedAt"],
    )


@router.get("/api/v1/search/views", response_model=SavedSearchList)
async def list_saved_search_views(request: Request) -> SavedSearchList:
    store = _get_saved_search_store(request)
    rows = await store.list()
    return SavedSearchList(items=[_saved_model(row) for row in rows])


@router.post(
    "/api/v1/search/views", response_model=SavedSearchView, status_code=201
)
async def create_saved_search_view(
    payload: SavedSearchCreate, request: Request
) -> SavedSearchView:
    """Save the current query + filter intent (not the result set)."""
    store = _get_saved_search_store(request)
    row = await store.create(
        payload.name, payload.query,
        {"view": payload.view, "categoryKey": payload.categoryKey},
    )
    return _saved_model(row)


@router.patch(
    "/api/v1/search/views/{view_id}", response_model=SavedSearchView
)
async def rename_saved_search_view(
    view_id: str, payload: SavedSearchRename, request: Request
) -> SavedSearchView:
    store = _get_saved_search_store(request)
    row = await store.rename(view_id, payload.name)
    if row is None:
        raise SavedSearchNotFound(view_id)
    return _saved_model(row)


@router.delete("/api/v1/search/views/{view_id}", status_code=204)
async def delete_saved_search_view(view_id: str, request: Request) -> Response:
    store = _get_saved_search_store(request)
    if not await store.delete(view_id):
        raise SavedSearchNotFound(view_id)
    return Response(status_code=204)
