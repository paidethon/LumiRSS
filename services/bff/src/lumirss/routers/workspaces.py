"""Workspace routes (phase2 M1) — ref collections + unified resolve.

Workspaces hold typed ItemRefs only; resolving them to unified ViewModels
goes through the Source Registry (:mod:`lumirss.sources`). The reserved
``read-later`` workspace cannot be deleted or renamed.
"""

import asyncio

from fastapi import APIRouter, Request, Response

from lumirss.models import (
    ReadLaterItem,
    ReadLaterTimelineResponse,
    ResolvedItem,
    ResolveRequest,
    Workspace,
    WorkspaceCreate,
    WorkspaceItem,
    WorkspaceItemAddRequest,
    WorkspaceItemsResolvedResponse,
    WorkspaceItemsResponse,
    WorkspaceListResponse,
    WorkspaceRename,
    WorkspaceReorderRequest,
)
from lumirss.sources import ItemRefUnresolvable, ensure_resolvable, resolve_item
from lumirss.workspaces import (
    RESERVED_WORKSPACE_ID,
    WorkspaceInvalid,
    WorkspaceNotFound,
    WorkspaceStore,
)

from ..deps import _get_source_registry, _get_workspace_store

router = APIRouter()

_DEFAULT_ITEM_LIMIT = 200
_MAX_ITEM_LIMIT = 500
_MAX_RESOLVE_REFS = 100


def _workspace_model(summary) -> Workspace:
    return Workspace(
        id=summary.id,
        name=summary.name,
        position=summary.position,
        itemCount=summary.item_count,
        reserved=summary.reserved,
    )


def _item_model(item) -> WorkspaceItem:
    return WorkspaceItem(
        itemRef=item.item_ref,
        position=item.position,
        addedAt=item.added_at,
    )


def _resolved_models(views) -> list[ResolvedItem]:
    return [
        ResolvedItem(
            ref=view.ref,
            domain=view.domain,
            kind=view.kind,
            title=view.title,
            source=view.source,
            datetime=view.datetime,
            excerpt=view.excerpt,
            url=view.url,
            stale=view.stale,
            payload=view.payload,
        )
        for view in views
    ]


@router.post("/api/v1/workspaces", response_model=Workspace, status_code=201)
async def create_workspace(payload: WorkspaceCreate, request: Request) -> Workspace:
    store: WorkspaceStore = _get_workspace_store(request)
    return _workspace_model(await store.create_workspace(payload.name))


@router.get("/api/v1/workspaces", response_model=WorkspaceListResponse)
async def list_workspaces(request: Request) -> WorkspaceListResponse:
    store: WorkspaceStore = _get_workspace_store(request)
    summaries = await store.list_workspaces()
    return WorkspaceListResponse(
        items=[_workspace_model(summary) for summary in summaries]
    )


@router.get("/api/v1/workspaces/{workspace_id}", response_model=Workspace)
async def get_workspace(workspace_id: str, request: Request) -> Workspace:
    store: WorkspaceStore = _get_workspace_store(request)
    summary = await store.get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    return _workspace_model(summary)


@router.patch("/api/v1/workspaces/{workspace_id}", response_model=Workspace)
async def rename_workspace(
    workspace_id: str, payload: WorkspaceRename, request: Request
) -> Workspace:
    store: WorkspaceStore = _get_workspace_store(request)
    return _workspace_model(await store.rename_workspace(workspace_id, payload.name))


@router.delete("/api/v1/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, request: Request) -> Response:
    store: WorkspaceStore = _get_workspace_store(request)
    deleted = await store.delete_workspace(workspace_id)
    if not deleted:
        raise WorkspaceNotFound(workspace_id)
    return Response(status_code=204)


@router.post(
    "/api/v1/workspaces/{workspace_id}/items",
    response_model=WorkspaceItem,
    status_code=201,
)
async def add_workspace_item(
    workspace_id: str, payload: WorkspaceItemAddRequest, request: Request
) -> WorkspaceItem:
    """Idempotent add of one typed ItemRef (returns 201 with current slot).

    The ref must resolve (ADR 0004): writes never create dangling
    membership. A known-but-stale domain (FreshRSS unconfigured) passes.
    """
    registry = _get_source_registry(request)

    try:
        await ensure_resolvable(registry, payload.itemRef)
    except ItemRefUnresolvable as exc:
        raise WorkspaceInvalid("引用的内容不存在，无法加入工作区。") from exc
    store: WorkspaceStore = _get_workspace_store(request)
    item = await store.add_item(workspace_id, payload.itemRef)
    return _item_model(item)


@router.get(
    "/api/v1/workspaces/{workspace_id}/items",
    response_model=WorkspaceItemsResponse,
)
async def list_workspace_items(
    workspace_id: str, request: Request, limit: int = _DEFAULT_ITEM_LIMIT
) -> WorkspaceItemsResponse:
    if limit < 1 or limit > _MAX_ITEM_LIMIT:
        raise WorkspaceInvalid(f"limit must be between 1 and {_MAX_ITEM_LIMIT}.")
    store: WorkspaceStore = _get_workspace_store(request)
    items = await store.list_items(workspace_id, limit=limit)
    return WorkspaceItemsResponse(items=[_item_model(item) for item in items])


@router.patch(
    "/api/v1/workspaces/{workspace_id}/items",
    response_model=WorkspaceItemsResponse,
)
async def reorder_workspace_items(
    workspace_id: str, payload: WorkspaceReorderRequest, request: Request
) -> WorkspaceItemsResponse:
    store: WorkspaceStore = _get_workspace_store(request)
    await store.reorder_items(workspace_id, payload.itemRefs)
    items = await store.list_items(workspace_id)
    return WorkspaceItemsResponse(items=[_item_model(item) for item in items])


@router.delete(
    "/api/v1/workspaces/{workspace_id}/items/{item_ref}", status_code=204
)
async def remove_workspace_item(
    workspace_id: str, item_ref: str, request: Request
) -> Response:
    store: WorkspaceStore = _get_workspace_store(request)
    removed = await store.remove_item(workspace_id, item_ref)
    if not removed:
        raise WorkspaceInvalid("Item is not a member of this workspace.")
    return Response(status_code=204)


@router.get(
    "/api/v1/workspaces/{workspace_id}/contents",
    response_model=WorkspaceItemsResolvedResponse,
)
async def workspace_contents(
    workspace_id: str, request: Request, limit: int = _DEFAULT_ITEM_LIMIT
) -> WorkspaceItemsResolvedResponse:
    """Ordered membership with each ref resolved to a unified ViewModel.

    Stale rss refs (entry gone from FreshRSS) resolve to ``stale=True``
    views — rows are never auto-deleted.
    """
    if limit < 1 or limit > _MAX_ITEM_LIMIT:
        raise WorkspaceInvalid(f"limit must be between 1 and {_MAX_ITEM_LIMIT}.")
    store: WorkspaceStore = _get_workspace_store(request)
    items = await store.list_items(workspace_id, limit=limit)
    registry = _get_source_registry(request)

    # Refs resolve independently (rss hits FreshRSS, library stays local);
    # gather keeps worst-case latency at one round trip, not N.
    resolved = list(
        await asyncio.gather(
            *(resolve_item(registry, item.item_ref) for item in items)
        )
    )
    return WorkspaceItemsResolvedResponse(items=_resolved_models(resolved))


@router.get(
    "/api/v1/workspaces/read-later/timeline",
    response_model=ReadLaterTimelineResponse,
)
async def read_later_timeline(
    request: Request,
    limit: int = 25,
    cursor: str | None = None,
) -> ReadLaterTimelineResponse:
    """Server-driven read-later timeline (P0-01): newest-added-first,
    keyset-paged over the reserved workspace's rss members. Cards come
    from the derived projection; a projection miss falls back to the
    FreshRSS adapter; a ref that resolves nowhere stays visible as
    ``stale`` instead of vanishing (ADR 0004)."""
    if limit < 1 or limit > 100:
        raise WorkspaceInvalid("limit must be between 1 and 100.")
    store: WorkspaceStore = _get_workspace_store(request)
    members, next_cursor = await store.list_items_desc(
        RESERVED_WORKSPACE_ID, cursor=cursor, limit=limit
    )
    items = [await _read_later_card(request, member) for member in members]
    return ReadLaterTimelineResponse(items=items, nextCursor=next_cursor)


async def _read_later_card(request: Request, member: WorkspaceItem) -> ReadLaterItem:
    from lumirss.entryref import InvalidEntryReference, decode_entry_ref
    from lumirss.models import SearchItem

    item_ref = member.item_ref
    stale_card = ReadLaterItem(
        itemRef=item_ref, addedAt=member.added_at, stale=True, entry=None
    )
    if not item_ref.startswith("rss:"):
        # Reserved workspace is rss-only by contract of the save path;
        # anything else would never render as an entry card.
        return stale_card
    try:
        item_id = decode_entry_ref(item_ref[len("rss:") :])
    except InvalidEntryReference:
        return stale_card
    row = await request.app.state.db.fetch_one(
        "SELECT entry_ref, title, feed_title, feed_url, author, url, published_at, read, starred, content_text FROM search_entries WHERE entry_ref = ?",
        (item_ref,),
    )
    if row is not None:
        return ReadLaterItem(
            itemRef=item_ref,
            addedAt=member.added_at,
            entry=SearchItem(
                entryRef=str(row["entry_ref"]),
                title=str(row["title"]),
                feedTitle=str(row["feed_title"]),
                feedUrl=str(row["feed_url"]),
                author=row["author"] or None,
                url=row["url"] or None,
                publishedAt=str(row["published_at"]),
                read=bool(row["read"]),
                starred=bool(row["starred"]),
                snippet=(row["content_text"] or "")[:160],
                matchedFields=[],
            ),
        )
    # Projection miss: ask FreshRSS once before declaring the ref stale.
    adapter = request.app.state.freshrss_adapter
    if adapter is not None:
        from lumirss.adapters.freshrss import EntryNotFound

        try:
            detail = await adapter.get_entry(item_id)
        except (EntryNotFound, InvalidEntryReference):
            return stale_card
        except Exception:  # noqa: BLE001 — upstream failure ≠ stale content
            return ReadLaterItem(
                itemRef=item_ref,
                addedAt=member.added_at,
                stale=True,
                entry=None,
            )
        return ReadLaterItem(
            itemRef=item_ref,
            addedAt=member.added_at,
            entry=SearchItem(
                entryRef=item_ref,
                title=detail.title,
                feedTitle=detail.feedTitle,
                feedUrl="",
                author=detail.author,
                url=detail.url,
                publishedAt=detail.publishedAt or "",
                read=detail.read,
                starred=detail.starred,
                snippet=(detail.contentText or "")[:160],
                matchedFields=[],
            ),
        )
    return ReadLaterItem(itemRef=item_ref, addedAt=member.added_at, stale=True, entry=None)


@router.post("/api/v1/resolve", response_model=WorkspaceItemsResolvedResponse)
async def resolve_refs(payload: ResolveRequest, request: Request) -> WorkspaceItemsResolvedResponse:
    """Resolve one batch of ItemRefs to unified ViewModels (≤100 refs)."""
    if not payload.refs or len(payload.refs) > _MAX_RESOLVE_REFS:
        raise WorkspaceInvalid(
            f"refs must contain between 1 and {_MAX_RESOLVE_REFS} items."
        )
    registry = _get_source_registry(request)

    resolved = list(
        await asyncio.gather(*(resolve_item(registry, ref) for ref in payload.refs))
    )
    return WorkspaceItemsResolvedResponse(items=_resolved_models(resolved))
