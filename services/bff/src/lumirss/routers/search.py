"""Global search routes (0022).

GET /api/v1/search — one page of hits over the derived projection.
POST /api/v1/search/rebuild — explicit bounded rebuild (admin op).

Every parameter is validated here; the projection query itself is a
single static statement (see search_store.py). Snippets are plain text
extracted from the sanitized content text — the web client renders
them as text, never as HTML.
"""

import time

from fastapi import APIRouter, Request

from lumirss.models import SearchRebuildResult, SearchResponse
from lumirss.search_index import (
    SearchQueryError,
    decode_search_cursor,
    encode_search_cursor,
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
    keyset = None
    if cursor is not None:
        keyset = decode_search_cursor(cursor)
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
        next_cursor = encode_search_cursor(*result["nextKeyset"])
    index = await service.index_info()
    # phase2 G6 unified view: the library leg runs beside the RSS leg and
    # fails independently (partial failure stays honest, never silent).
    library_items = None
    library_error = None
    try:
        from lumirss.deps import _get_library_search_writer
        from lumirss.models import LibrarySearchItem

        writer = _get_library_search_writer(request)
        hits = await writer.search(query, limit=_MAX_LIMIT)
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
