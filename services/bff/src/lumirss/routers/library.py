"""Library bookmark routes (phase2 M1).

CRUD plus Netscape import/export over the Lumi-owned library domain.
RSS-entry bookmarks store the ``rss:<entryRef>`` reference and snapshot
metadata only — bodies stay in FreshRSS. The import endpoint reads the
raw request body with a hard size cap (OPML style) and reports per-item
failures honestly.
"""

from fastapi import APIRouter, Request, Response

from lumirss.bookmarks_io import (
    NetscapeBookmark,
    NetscapeParseError,
    export_netscape,
    parse_netscape,
)
from lumirss.library import (
    _MAX_TITLE_LENGTH,
    _MAX_URL_LENGTH,
    BookmarkInvalid,
    BookmarkNotFound,
    BookmarkView,
    LibraryStore,
)
from lumirss.models import (
    Bookmark,
    BookmarkCreate,
    BookmarkImportFailedItem,
    BookmarkImportResult,
    BookmarkListResponse,
    BookmarkUpdate,
)

from ..deps import _get_library_store

router = APIRouter()

_MAX_IMPORT_BYTES = 10 * 1024 * 1024
_MAX_IMPORT_ITEMS = 5000
_MAX_EXPORT_ITEMS = 20000
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _bookmark_model(view: BookmarkView) -> Bookmark:
    return Bookmark(
        ref=view.ref,
        itemType=view.item_type,
        url=view.url,
        rssItemRef=view.rss_item_ref,
        title=view.title,
        note=view.note,
        createdAt=view.created_at,
    )


@router.post(
    "/api/v1/library/bookmarks",
    response_model=Bookmark,
    status_code=201,
)
async def create_bookmark(payload: BookmarkCreate, request: Request) -> Bookmark:
    """Create a url bookmark or an rss-ref bookmark (idempotent on url/ref)."""
    store: LibraryStore = _get_library_store(request)
    if (payload.url is None) == (payload.rssItemRef is None):
        raise BookmarkInvalid(
            "Provide exactly one of url or rssItemRef."
        )
    if payload.rssItemRef is not None:
        view, _created = await store.create_rss_bookmark(
            payload.rssItemRef, payload.title, payload.note
        )
    else:
        view, _created = await store.create_url_bookmark(
            payload.url or "", payload.title, payload.note
        )
    return _bookmark_model(view)


@router.get("/api/v1/library/bookmarks", response_model=BookmarkListResponse)
async def list_bookmarks(
    request: Request,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    q: str | None = None,
) -> BookmarkListResponse:
    """Keyset-paged bookmark list, newest first."""
    if limit < 1 or limit > _MAX_LIMIT:
        raise BookmarkInvalid(f"limit must be between 1 and {_MAX_LIMIT}.")
    store: LibraryStore = _get_library_store(request)
    items, next_cursor = await store.list_bookmarks(
        cursor=cursor, limit=limit, q=q
    )
    return BookmarkListResponse(
        items=[_bookmark_model(view) for view in items],
        nextCursor=next_cursor,
    )


@router.patch("/api/v1/library/bookmarks/{item_uuid}", response_model=Bookmark)
async def update_bookmark(
    item_uuid: str, payload: BookmarkUpdate, request: Request
) -> Bookmark:
    store: LibraryStore = _get_library_store(request)
    try:
        view = await store.update_bookmark(
            item_uuid, payload.title, payload.note
        )
    except BookmarkNotFound:
        raise
    return _bookmark_model(view)


@router.delete("/api/v1/library/bookmarks/{item_uuid}", status_code=204)
async def delete_bookmark(item_uuid: str, request: Request) -> Response:
    store: LibraryStore = _get_library_store(request)
    deleted = await store.delete_bookmark(item_uuid)
    if not deleted:
        raise BookmarkNotFound(item_uuid)
    from ..deps import _rag_mark_stale

    await _rag_mark_stale(request, [f"library:{item_uuid}"])
    return Response(status_code=204)


@router.post("/api/v1/library/bookmarks/import", response_model=BookmarkImportResult)
async def import_bookmarks(request: Request) -> BookmarkImportResult:
    """Merge-import a Netscape bookmarks.html (merge-only, per-item errors).

    Existing urls converge on the unique index (counted as skipped);
    invalid entries (scheme, length) are reported item by item and never
    abort the whole import.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_IMPORT_BYTES:
            raise NetscapeParseError("Import file exceeds the 10 MiB limit.")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NetscapeParseError("Import file is not valid UTF-8.") from exc
    parsed_items = parse_netscape(text)
    if len(parsed_items) > _MAX_IMPORT_ITEMS:
        raise NetscapeParseError(
            f"Import file contains too many items (max {_MAX_IMPORT_ITEMS})."
        )
    store: LibraryStore = _get_library_store(request)
    imported = 0
    skipped = 0
    failed: list[BookmarkImportFailedItem] = []
    for index, item in enumerate(parsed_items):
        try:
            _view, created = await store.create_url_bookmark(
                item.url, item.title[:_MAX_TITLE_LENGTH]
            )
        except BookmarkInvalid as exc:
            failed.append(
                BookmarkImportFailedItem(
                    index=index, url=item.url[:_MAX_URL_LENGTH], reason=str(exc)
                )
            )
            continue
        if created:
            imported += 1
        else:
            skipped += 1
    return BookmarkImportResult(
        imported=imported, skipped=skipped, failed=failed
    )


@router.get("/api/v1/library/bookmarks/export.html")
async def export_bookmarks(request: Request) -> Response:
    """Export all url bookmarks as a Netscape bookmarks.html download."""
    store: LibraryStore = _get_library_store(request)
    count = await store.count_bookmarks()
    if count > _MAX_EXPORT_ITEMS:
        raise BookmarkInvalid(
            f"Too many bookmarks to export (max {_MAX_EXPORT_ITEMS})."
        )
    views = await store.list_all_bookmarks()
    items = [
        NetscapeBookmark(
            url=view.url or "",
            title=view.title,
            folders=[],
            tags=[],
            added_at=None,
        )
        for view in views
        if view.item_type == "url"
    ]
    content = export_netscape(items)
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="bookmarks.html"'},
    )
