"""Workspace routes (phase2 M1) — ref collections + unified resolve.

Workspaces hold typed ItemRefs only; resolving them to unified ViewModels
goes through the Source Registry (:mod:`lumirss.sources`). The reserved
``read-later`` workspace cannot be deleted or renamed.
"""

import asyncio
import logging

from fastapi import APIRouter, Request, Response

from lumirss.itemref import InvalidItemRef
from lumirss.models import (
    ReadLaterItem,
    ReadLaterSnoozedList,
    ReadLaterSnoozeRequest,
    ReadLaterSnoozeResult,
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
from lumirss.sources import (
    ItemRefUnresolvable,
    ensure_resolvable,
    resolve_item,
    stale_placeholder,
)
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
# Pool #44: resolve fan-out is bounded — one page must not start one
# upstream round trip per ref with no ceiling. 16 concurrent resolves
# keeps worst-case page latency at ceil(refs/16) round trips while a
# slow FreshRSS cannot pin hundreds of event-loop tasks.
_RESOLVE_CONCURRENCY = 16
_RESOLVE_TIMEOUT_S = 15.0
_resolve_semaphore: asyncio.Semaphore = asyncio.Semaphore(_RESOLVE_CONCURRENCY)

_logger = logging.getLogger("lumirss.sources")


async def _resolve_bounded(registry: dict, ref: str) -> ResolvedItem:
    """One ref resolve under the shared concurrency cap and a per-item
    deadline; upstream failures become distinguishable stale cards
    (pool #13/#44), never a whole-page 500 and never a silent fake
    success. A malformed ref stays a client error (400), as before."""
    try:
        async with _resolve_semaphore:
            return await asyncio.wait_for(
                resolve_item(registry, ref), timeout=_RESOLVE_TIMEOUT_S
            )
    except TimeoutError:
        return stale_placeholder(ref, "timeout", title="解析超时，请稍后重试")
    except InvalidItemRef:
        raise
    except Exception:
        _logger.exception("resolve failed for ref %s", ref)
        return stale_placeholder(ref, "error", title="暂时无法解析，请稍后重试")


def _workspace_model(summary) -> Workspace:
    return Workspace(
        id=summary.id,
        name=summary.name,
        position=summary.position,
        itemCount=summary.item_count,
        reserved=summary.reserved,
        description=summary.description,
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
            staleReason=view.staleReason,
            payload=view.payload,
        )
        for view in views
    ]


@router.post("/api/v1/workspaces", response_model=Workspace, status_code=201)
async def create_workspace(payload: WorkspaceCreate, request: Request) -> Workspace:
    store: WorkspaceStore = _get_workspace_store(request)
    return _workspace_model(
        await store.create_workspace(payload.name, payload.description or "")
    )


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
    return _workspace_model(
        await store.rename_workspace(workspace_id, payload.name, payload.description)
    )


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

    # Refs resolve independently (rss hits FreshRSS, library stays local)
    # under the shared concurrency cap (pool #44); one broken ref degrades
    # to its own stale card instead of 500ing the page.
    resolved = list(
        await asyncio.gather(
            *(_resolve_bounded(registry, item.item_ref) for item in items)
        )
    )
    return WorkspaceItemsResolvedResponse(items=_resolved_models(resolved))


@router.post(
    "/api/v1/workspaces/read-later/items/{item_ref}/snooze",
    response_model=ReadLaterSnoozeResult,
)
async def snooze_read_later_item(
    item_ref: str, payload: ReadLaterSnoozeRequest, request: Request
) -> ReadLaterSnoozeResult:
    """F19：延后一个稍后读项目到指定时刻（ISO；到期自动回到时间线）。

    只影响时间线可见性：行保留、成员关系与已读/收藏状态不变。
    until 必须是未来时刻（防止「延后到过去」造成假消失）。"""
    from datetime import datetime

    try:
        until_dt = datetime.fromisoformat(payload.until.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkspaceInvalid("until must be an ISO timestamp.") from exc
    now = datetime.now(until_dt.tzinfo) if until_dt.tzinfo else datetime.now()
    if until_dt <= now:
        raise WorkspaceInvalid("until must be in the future.")
    store: WorkspaceStore = _get_workspace_store(request)
    ok = await store.snooze_item(RESERVED_WORKSPACE_ID, item_ref, payload.until)
    if not ok:
        raise WorkspaceNotFound(f"read-later item {item_ref}")
    return ReadLaterSnoozeResult(itemRef=item_ref, snoozedUntil=payload.until)


@router.delete(
    "/api/v1/workspaces/read-later/items/{item_ref}/snooze",
    status_code=204,
)
async def unsnooze_read_later_item(item_ref: str, request: Request) -> Response:
    """F19：取消延后——项目立即回到时间线。"""
    store: WorkspaceStore = _get_workspace_store(request)
    ok = await store.snooze_item(RESERVED_WORKSPACE_ID, item_ref, None)
    if not ok:
        raise WorkspaceNotFound(f"read-later item {item_ref}")
    return Response(status_code=204)


@router.get(
    "/api/v1/workspaces/read-later/snoozed",
    response_model=ReadLaterSnoozedList,
)
async def list_snoozed_read_later(request: Request) -> ReadLaterSnoozedList:
    """当前处于延后状态的项目（供「已延后」视图展示）。"""
    store: WorkspaceStore = _get_workspace_store(request)
    rows = await store.list_snoozed(RESERVED_WORKSPACE_ID)
    return ReadLaterSnoozedList(
        items=[
            ReadLaterSnoozeResult(itemRef=ref, snoozedUntil=until) for ref, until in rows
        ]
    )


@router.get(
    "/api/v1/workspaces/read-later/timeline",
    response_model=ReadLaterTimelineResponse,
)
async def read_later_timeline(
    request: Request,
    limit: int = 25,
    cursor: str | None = None,
    order: str = "newest",
) -> ReadLaterTimelineResponse:
    """Server-driven read-later timeline (P0-01): keyset-paged over the
    reserved workspace's members by add time. ``order`` is ``newest``
    (default) or ``oldest`` (pool #14); cursors are bound to the order
    they were issued under. Cards come from the derived projection; a
    projection miss falls back to the FreshRSS adapter; a ref that
    resolves nowhere stays visible as ``stale`` instead of vanishing
    (ADR 0004)."""
    if limit < 1 or limit > 100:
        raise WorkspaceInvalid("limit must be between 1 and 100.")
    store: WorkspaceStore = _get_workspace_store(request)
    members, next_cursor = await store.list_items_desc(
        RESERVED_WORKSPACE_ID, cursor=cursor, limit=limit, order=order
    )
    # Q-P2-05: cards resolve concurrently (same gather pattern as
    # workspace_contents below) — the serial comprehension paid one
    # projection query or FreshRSS round-trip per card, back to back.
    # return_exceptions + stale-card mapping: one broken ref must not
    # 500 the whole timeline (same contract as the favorites view).
    views = await asyncio.gather(
        *(_read_later_card(request, member) for member in members),
        return_exceptions=True,
    )
    items = [
        view
        if not isinstance(view, BaseException)
        else ReadLaterItem(
            itemRef=member.item_ref, addedAt=member.added_at, stale=True
        )
        for view, member in zip(views, members, strict=True)
    ]
    return ReadLaterTimelineResponse(items=items, nextCursor=next_cursor)


async def _read_later_card(request: Request, member: WorkspaceItem) -> ReadLaterItem:
    from lumirss.deps import _get_source_registry
    from lumirss.entryref import InvalidEntryReference, decode_entry_ref
    from lumirss.models import SearchItem

    item_ref = member.item_ref
    stale_card = ReadLaterItem(
        itemRef=item_ref, addedAt=member.added_at, stale=True, entry=None
    )
    if not item_ref.startswith("rss:"):
        # Library refs (inbox api_item, clips, …) are first-class members:
        # render the unified registry view instead of a fake-stale row
        # (Q-P1-05 — the inbox save path legitimately adds these).
        if item_ref.startswith("library:"):
            registry = _get_source_registry(request)
            # Shared resolve cap + per-item deadline (pool #44); failures
            # degrade to this row's stale card, not a page-wide 500.
            view = await _resolve_bounded(registry, item_ref)
            if view.stale:
                return stale_card
            return ReadLaterItem(
                itemRef=item_ref,
                addedAt=member.added_at,
                stale=False,
                resolved=ResolvedItem(**view.to_dict()),
            )
        return stale_card
    try:
        item_id = decode_entry_ref(item_ref[len("rss:") :])
    except InvalidEntryReference:
        return stale_card
    from lumirss.search_store import SearchStore

    row = await SearchStore(request.app.state.db).entry_row_by_ref(item_ref)
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
        await asyncio.gather(
            *(_resolve_bounded(registry, ref) for ref in payload.refs)
        )
    )
    return WorkspaceItemsResolvedResponse(items=_resolved_models(resolved))
