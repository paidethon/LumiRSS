"""Web clip routes (phase2 M2).

POST /fetch performs the ONLY network hop — a bounded, anonymous,
SSRF-guarded server fetch. Extraction (Defuddle primary, Readability
fallback) and sanitization (DOMPurify — the architecture's final
boundary) run in the browser; POST / then stores the payload with
server-side structural/length validation. The search projection updates
synchronously on every write.
"""

from fastapi import APIRouter, Request, Response

from lumirss.clip_fetch import ClipFetchError, fetch_page
from lumirss.library_clips import (
    ClipInvalid,
    ClipNotFound,
    ClipStore,
    ClipView,
)
from lumirss.models import (
    Clip,
    ClipCreate,
    ClipDetail,
    ClipFetchRequest,
    ClipFetchResult,
    ClipListResponse,
)

from ..deps import _get_clip_store

router = APIRouter()

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _clip_model(view: ClipView) -> Clip:
    return Clip(
        ref=view.ref,
        url=view.url,
        title=view.title,
        byline=view.byline,
        fetchedAt=view.fetched_at,
        createdAt=view.created_at,
    )


@router.post("/api/v1/library/clips/fetch", response_model=ClipFetchResult)
async def fetch_for_clip(payload: ClipFetchRequest, request: Request) -> ClipFetchResult:
    """One bounded anonymous SSRF-guarded server fetch (no cookies)."""
    page = await fetch_page(request.app.state.http_client, payload.url)
    return ClipFetchResult(url=payload.url, finalUrl=page.final_url, html=page.html)


@router.post("/api/v1/library/clips", response_model=ClipDetail, status_code=201)
async def create_clip(payload: ClipCreate, request: Request) -> ClipDetail:
    store: ClipStore = _get_clip_store(request)
    view, _created = await store.create_clip(
        url=payload.url,
        title=payload.title,
        content_html=payload.contentHtml,
        content_text=payload.contentText,
        byline=payload.byline,
        fetched_at=payload.fetchedAt,
    )
    return ClipDetail(
        ref=view.ref,
        url=view.url,
        title=view.title,
        byline=view.byline,
        fetchedAt=view.fetched_at,
        createdAt=view.created_at,
        contentHtml=view.content_html,
        contentText=view.content_text,
    )


@router.get("/api/v1/library/clips", response_model=ClipListResponse)
async def list_clips(
    request: Request,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> ClipListResponse:
    if limit < 1 or limit > _MAX_LIMIT:
        raise ClipInvalid(f"limit must be between 1 and {_MAX_LIMIT}.")
    store: ClipStore = _get_clip_store(request)
    items, next_cursor = await store.list_clips(cursor=cursor, limit=limit)
    return ClipListResponse(
        items=[_clip_model(view) for view in items],
        nextCursor=next_cursor,
    )


@router.get("/api/v1/library/clips/{item_uuid}", response_model=ClipDetail)
async def get_clip(item_uuid: str, request: Request) -> ClipDetail:
    store: ClipStore = _get_clip_store(request)
    view = await store.get_clip(item_uuid)
    if view is None:
        raise ClipNotFound(item_uuid)
    return ClipDetail(
        ref=view.ref,
        url=view.url,
        title=view.title,
        byline=view.byline,
        fetchedAt=view.fetched_at,
        createdAt=view.created_at,
        contentHtml=view.content_html,
        contentText=view.content_text,
    )


@router.delete("/api/v1/library/clips/{item_uuid}", status_code=204)
async def delete_clip(item_uuid: str, request: Request) -> Response:
    store: ClipStore = _get_clip_store(request)
    deleted = await store.delete_clip(item_uuid)
    if not deleted:
        raise ClipNotFound(item_uuid)
    return Response(status_code=204)


_ = ClipFetchError  # referenced by the error envelope table
