"""LumiRSS BFF application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, model_validator

from lumirss.adapters.freshrss import (
    AuthenticationError,
    ConfigError,
    EntryNotFound,
    FreshRSSAdapter,
    UpstreamConnectionError,
    UpstreamError,
)
from lumirss.config import FreshRSSSettings
from lumirss.cursor import InvalidCursor, decode_cursor, encode_cursor
from lumirss.entryref import InvalidEntryReference, decode_entry_ref
from lumirss.models import EntryDetail, EntryListResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the shared HTTP client; the FreshRSSAdapter is created lazily
    on the first /api/v1/feeds request (so /health/live works even when
    FreshRSS is not configured)."""
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        trust_env=False,
    )
    app.state.freshrss_adapter = None
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="LumiRSS BFF", lifespan=lifespan)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """Liveness: only proves this process is alive, never touches FreshRSS."""
    return {"status": "ok"}


_ERROR_RESPONSES = {
    ConfigError: (503, "configuration_error"),
    AuthenticationError: (502, "authentication_error"),
    UpstreamConnectionError: (502, "connection_error"),
    UpstreamError: (502, "upstream_error"),
    InvalidEntryReference: (400, "invalid_entry_reference"),
    EntryNotFound: (404, "entry_not_found"),
    InvalidCursor: (400, "invalid_cursor"),
}


@app.exception_handler(ConfigError)
@app.exception_handler(AuthenticationError)
@app.exception_handler(UpstreamConnectionError)
@app.exception_handler(UpstreamError)
@app.exception_handler(InvalidEntryReference)
@app.exception_handler(EntryNotFound)
@app.exception_handler(InvalidCursor)
async def adapter_error_handler(request: Request, exc: Exception) -> JSONResponse:
    status, error_type = _ERROR_RESPONSES[type(exc)]
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": str(exc)}},
    )


@app.get("/api/v1/feeds")
async def feeds(request: Request) -> list[dict[str, object]]:
    """List feeds from FreshRSS through the FreshRSSAdapter.

    The adapter is created lazily on the first request (settings are only
    read/validated here, never at startup) and then cached on app.state so
    later requests reuse it and its in-memory auth token.

    0011: 每项附带 FreshRSS 真实分类（categoryId 为稳定 key，label 为
    展示名）；无分类的 feed category 为 null（前端归入「未分组」）。
    """
    adapter = _get_adapter(request)
    feeds = await adapter.list_feeds()
    return [
        {
            "title": feed.title,
            "feedUrl": feed.feed_url,
            "category": (
                {"id": feed.category_id, "label": feed.category_label}
                if feed.category_id is not None and feed.category_label is not None
                else None
            ),
        }
        for feed in feeds
    ]


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


@app.get("/api/v1/entries", response_model=EntryListResponse)
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


@app.get("/api/v1/entries/{entry_ref}", response_model=EntryDetail)
async def entry_detail(entry_ref: str, request: Request) -> EntryDetail:
    """One entry as plain text. Invalid refs are rejected before FreshRSS;
    reading a detail never marks anything as read (read-only milestone)."""
    item_id = decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    adapter = _get_adapter(request)
    return await adapter.get_entry(item_id)


@app.patch("/api/v1/entries/{entry_ref}/state", status_code=204)
async def entry_state(entry_ref: str, update: EntryStateUpdate, request: Request) -> Response:
    """Set the read/starred state of one entry (set semantics, not toggle).

    204 means FreshRSS accepted the write; it does not re-confirm that the
    entry exists. Invalid refs and invalid bodies are rejected before any
    FreshRSS call.
    """
    item_id = decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    adapter = _get_adapter(request)
    await adapter.set_entry_state(
        item_id, read=update.read, starred=update.starred
    )
    return Response(status_code=204)


def _get_adapter(request: Request) -> FreshRSSAdapter:
    """Lazily create and cache the FreshRSSAdapter on app.state."""
    adapter = request.app.state.freshrss_adapter
    if adapter is None:
        try:
            settings = FreshRSSSettings()
        except ValidationError as exc:
            raise ConfigError(
                "FreshRSS settings are missing or invalid. "
                "Set FRESHRSS_BASE_URL / FRESHRSS_USERNAME / FRESHRSS_API_PASSWORD."
            ) from exc
        adapter = FreshRSSAdapter(request.app.state.http_client, settings)
        request.app.state.freshrss_adapter = adapter
    return adapter
