"""Web clip routes (phase2 M2, recovery P0-03) — server-side pipeline.

POST /fetch performs the ONLY network hop (bounded, anonymous,
SSRF-pinned) AND derives the article server-side: extract
(readability-style) + sanitize (allow-list). The browser no longer
extracts or cleans anything; POST / re-derives content from the URL
itself, so client-supplied HTML is never trusted and never stored —
deprecated client fields (title/byline/contentHtml/contentText/
fetchedAt) are accepted for wire-shape compatibility and IGNORED. The
browser DOMPurify pass remains the final render boundary, but the
stored bytes are already server-sanitized. The search projection
updates in the same transaction as the clip rows.
"""

from fastapi import APIRouter, Request, Response

from lumirss.clip_fetch import ClipFetchError, fetch_extract_sanitize
from lumirss.library_clips import (
    ClipInvalid,
    ClipNotFound,
    ClipStore,
    ClipView,
)
from lumirss.models import (
    Clip,
    ClipCreateRequest,
    ClipDetail,
    ClipFetchArticleResult,
    ClipFetchRequest,
    ClipListResponse,
)

from ..deps import _get_clip_store

router = APIRouter()

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _clip_model(view: ClipView):
    return Clip(
        ref=view.ref,
        url=view.url,
        title=view.title,
        byline=view.byline,
        fetchedAt=view.fetched_at,
        createdAt=view.created_at,
    )


@router.post("/api/v1/library/clips/fetch", response_model=ClipFetchArticleResult)
async def fetch_for_clip(payload: ClipFetchRequest) -> ClipFetchArticleResult:
    """Server fetch (SSRF-pinned) + extraction + sanitization preview."""
    article = await fetch_extract_sanitize(payload.url)
    return ClipFetchArticleResult(
        url=payload.url,
        finalUrl=article.final_url,
        title=article.title,
        byline=article.byline,
        contentHtml=article.content_html,
        contentText=article.content_text,
    )


@router.post("/api/v1/library/clips", response_model=ClipDetail, status_code=201)
async def create_clip(payload: ClipCreateRequest, request: Request) -> ClipDetail:
    """Create a clip from a URL confirmation.

    Security contract (P0-03): ALL content is re-derived server-side by
    fetching ``finalUrl`` (the page the user confirmed in the preview)
    or ``url``. Client-supplied title/byline/contentHtml/contentText/
    fetchedAt are ignored by design; what gets stored comes only from
    the server's own fetch → extract → sanitize pipeline, and the URL
    recorded is the FINAL url after redirects.
    """
    store: ClipStore = _get_clip_store(request)
    target = payload.finalUrl or payload.url
    article = await fetch_extract_sanitize(target)
    view, _created = await store.create_clip(
        url=article.final_url,
        title=article.title,
        content_html=article.content_html,
        content_text=article.content_text,
        byline=article.byline,
        fetched_at=None,
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
