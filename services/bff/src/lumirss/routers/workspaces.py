"""Workspace routes (phase2 M1) — ref collections + unified resolve.

Workspaces hold typed ItemRefs only; resolving them to unified ViewModels
goes through the Source Registry (:mod:`lumirss.sources`). The reserved
``read-later`` workspace cannot be deleted or renamed.
"""

from fastapi import APIRouter, Request, Response

from lumirss.models import (
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
from lumirss.workspaces import (
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
    """Idempotent add of one typed ItemRef (returns 201 with current slot)."""
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
    from lumirss.sources import resolve_item

    resolved = [await resolve_item(registry, item.item_ref) for item in items]
    return WorkspaceItemsResolvedResponse(items=_resolved_models(resolved))


@router.post("/api/v1/resolve", response_model=WorkspaceItemsResolvedResponse)
async def resolve_refs(payload: ResolveRequest, request: Request) -> WorkspaceItemsResolvedResponse:
    """Resolve one batch of ItemRefs to unified ViewModels (≤100 refs)."""
    if not payload.refs or len(payload.refs) > _MAX_RESOLVE_REFS:
        raise WorkspaceInvalid(
            f"refs must contain between 1 and {_MAX_RESOLVE_REFS} items."
        )
    registry = _get_source_registry(request)
    from lumirss.sources import resolve_item

    resolved = [await resolve_item(registry, ref) for ref in payload.refs]
    return WorkspaceItemsResolvedResponse(items=_resolved_models(resolved))
