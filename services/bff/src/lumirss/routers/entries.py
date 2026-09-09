"""Entries routes (moved verbatim from main.py)."""


from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, model_validator

from lumirss.cursor import InvalidCursor, decode_cursor, encode_cursor
from lumirss.deps import _get_adapter, _get_search_service
from lumirss.entryref import InvalidEntryReference, decode_entry_ref
from lumirss.models import (
    EntryDetail,
    EntryListResponse,
)

router = APIRouter()


class EntryStateUpdate(BaseModel):
    """PATCH body: set (never toggle) read/starred; one bool is required.

    Strict bools: Pydantic does not coerce 1/0/"true" into bool.
    """

    read: bool | None = Field(default=None, strict=True)
    starred: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def at_least_one_bool(self) -> "EntryStateUpdate":
        if self.read is None and self.starred is None:
            raise ValueError("At least one of 'read' or 'starred' must be provided.")
        return self


@router.get(
    "/api/v1/entries",
    response_model=EntryListResponse,
    response_model_exclude_none=False,
)
async def entries(
    request: Request,
    view: Literal["all", "unread", "starred"] | None = None,
    feedUrl: str | None = None,
    sourceType: str | None = None,
    categoryId: str | None = None,
    cursor: str | None = None,
) -> EntryListResponse:
    """One filtered page of entries — list fields only, never bodies.

    Filtering happens upstream (FreshRSS). Cursor rules: without a cursor,
    a missing view means "all"; with a cursor, a missing view/feedUrl/
    sourceType/categoryId adopts the cursor's scope, while an explicit
    view/feedUrl/sourceType/categoryId must match the cursor's scope
    exactly (else 400, before touching FreshRSS).

    0011 scope 扩展（§6/§13，全部服务端过滤，不用已加载页假筛选）：
    - sourceType：当前唯一合法值 "rss"（全部条目都是 RSS；契约上独立
      于“全部”，未来新增来源后有真实过滤行为）；
    - categoryId：FreshRSS 分类（greader label stream，适配器含默认
      分类本地化名 fallback）；
    - feedUrl 与 categoryId 互斥（两者同时出现 → 400）。
    """
    if sourceType is not None and sourceType != "rss":
        raise InvalidEntryReference("sourceType must be 'rss' (only source type today).")
    if feedUrl is not None and categoryId is not None:
        raise InvalidEntryReference("feedUrl and categoryId are mutually exclusive.")
    effective_view = view or "all"
    continuation: str | None = None
    if cursor is not None:
        scope = decode_cursor(cursor)  # raises InvalidCursor → 400
        if view is not None and scope.view != view:
            raise InvalidCursor("cursor scope does not match the requested view.")
        if feedUrl is not None and scope.feed_url != feedUrl:
            raise InvalidCursor("cursor scope does not match the requested feedUrl.")
        if sourceType is not None and scope.source_type != sourceType:
            raise InvalidCursor("cursor scope does not match the requested sourceType.")
        if categoryId is not None and scope.category_id != categoryId:
            raise InvalidCursor("cursor scope does not match the requested categoryId.")
        effective_view = scope.view
        feedUrl = scope.feed_url
        sourceType = scope.source_type
        categoryId = scope.category_id
        continuation = scope.continuation
    adapter = _get_adapter(request)
    page = await adapter.list_entries(
        view=effective_view,
        feed_url=feedUrl,
        category_id=categoryId,
        source_type=sourceType,
        continuation=continuation,
    )
    next_cursor = (
        encode_cursor(
            page.upstreamContinuation,
            effective_view,
            feedUrl,
            source_type=sourceType,
            category_id=categoryId,
        )
        if page.upstreamContinuation is not None
        else None
    )
    return EntryListResponse(items=page.items, nextCursor=next_cursor)


@router.get(
    "/api/v1/entries/{entry_ref}",
    response_model=EntryDetail,
    response_model_exclude_none=False,
)
async def entry_detail(entry_ref: str, request: Request) -> EntryDetail:
    """One entry as plain text. Invalid refs are rejected before FreshRSS;
    reading a detail never marks anything as read (read-only milestone)."""
    item_id = decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    adapter = _get_adapter(request)
    return await adapter.get_entry(item_id)


@router.patch("/api/v1/entries/{entry_ref}/state", status_code=204)
async def entry_state(entry_ref: str, update: EntryStateUpdate, request: Request) -> Response:
    """Set the read/starred state of one entry (set semantics, not toggle).

    204 means FreshRSS accepted the write; it does not re-confirm that the
    entry exists. Invalid refs and invalid bodies are rejected before any
    FreshRSS call. The accepted state is mirrored into the derived search
    projection so its unread/starred filters stay fresh between syncs.
    """
    item_id = decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    adapter = _get_adapter(request)
    await adapter.set_entry_state(
        item_id, read=update.read, starred=update.starred
    )
    search = _get_search_service(request)
    if update.read is not None:
        await search.set_entry_read(entry_ref, update.read)
    if update.starred is not None:
        await search.set_entry_starred(entry_ref, update.starred)
    return Response(status_code=204)


