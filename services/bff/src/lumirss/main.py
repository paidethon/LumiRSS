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
from lumirss.adapters.freshrss_control import (
    CategoryLabelConflict,
    CategoryNotFound,
    DefaultCategoryImmutable,
    FeedRejectedError,
    FreshRSSControlAdapter,
    InvalidCategoryLabel,
    InvalidCategoryReference,
    InvalidFeedUrl,
    SubscriptionConflict,
    SubscriptionNotFound,
)
from lumirss.ai_settings import (
    AiSettingsStore,
    AiSettingsUpdate,
    InvalidAiSettings,
    KEY_BASE_URL,
    KEY_MODEL,
    KEY_PROVIDER,
    KEY_SUMMARY_LANGUAGE,
)
from lumirss.config import FreshRSSSettings, LumiSettings
from lumirss.cursor import InvalidCursor, decode_cursor, encode_cursor
from lumirss.entryref import InvalidEntryReference, decode_entry_ref
from lumirss.feed_preview import (
    FeedFetchError,
    FeedPreviewService,
    FeedTooLarge,
    NotAFeedError,
    UnsafeFeedUrl,
)
from lumirss.models import EntryDetail, EntryListResponse
from lumirss.opml import (
    MAX_OPML_BYTES,
    OpmlInvalid,
    OpmlService,
    OpmlTooLarge,
    OpmlTooManyFeeds,
)
from lumirss.rsshub import (
    RssHubFetchError,
    RssHubInvalidParameters,
    RssHubNotConfigured,
    RssHubRouteNotFound,
    RssHubService,
)
from lumirss.source_discovery import (
    InvalidSourceUrl,
    NoFeedDiscovered,
    SourceDiscoveryService,
)
from lumirss.storage import Database
from lumirss.subscriptionref import (
    InvalidSubscriptionReference,
    decode_subscription_ref,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the shared HTTP client; the FreshRSSAdapter is created lazily
    on the first /api/v1/feeds request (so /health/live works even when
    FreshRSS is not configured). The Lumi SQLite Database handle is created
    here too — cheap, no file I/O; migrations run lazily on the first
    storage use (0015)."""
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        trust_env=False,
    )
    app.state.db = Database(LumiSettings().LUMIRSS_DB_PATH)
    app.state.ai_settings_store = None
    app.state.freshrss_adapter = None
    app.state.freshrss_control_adapter = None
    app.state.feed_preview_service = None
    app.state.source_discovery_service = None
    app.state.rsshub_service = None
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
    # 0013 control plane
    InvalidSubscriptionReference: (400, "invalid_subscription_reference"),
    InvalidFeedUrl: (400, "invalid_feed_url"),
    FeedRejectedError: (400, "feed_rejected"),
    SubscriptionConflict: (409, "subscription_conflict"),
    SubscriptionNotFound: (404, "subscription_not_found"),
    InvalidCategoryReference: (400, "invalid_category_reference"),
    InvalidCategoryLabel: (400, "invalid_category_label"),
    CategoryNotFound: (404, "category_not_found"),
    CategoryLabelConflict: (409, "category_label_conflict"),
    DefaultCategoryImmutable: (409, "default_category_immutable"),
    # 0013 Gate 2 preview
    UnsafeFeedUrl: (400, "unsafe_feed_url"),
    FeedFetchError: (502, "feed_fetch_error"),
    FeedTooLarge: (413, "feed_too_large"),
    NotAFeedError: (400, "not_a_feed"),
    # 0013 Gate 4 OPML
    OpmlInvalid: (400, "opml_invalid"),
    OpmlTooLarge: (413, "opml_too_large"),
    OpmlTooManyFeeds: (400, "opml_too_many_feeds"),
    # 0014 source discovery
    InvalidSourceUrl: (400, "invalid_source_url"),
    NoFeedDiscovered: (404, "no_feed_discovered"),
    # 0014 RSSHub
    RssHubNotConfigured: (503, "rsshub_not_configured"),
    RssHubRouteNotFound: (404, "rsshub_route_not_found"),
    RssHubInvalidParameters: (400, "rsshub_invalid_parameters"),
    RssHubFetchError: (502, "rsshub_fetch_error"),
    # 0015 AI settings
    InvalidAiSettings: (400, "invalid_ai_settings"),
}


@app.exception_handler(ConfigError)
@app.exception_handler(AuthenticationError)
@app.exception_handler(UpstreamConnectionError)
@app.exception_handler(UpstreamError)
@app.exception_handler(InvalidEntryReference)
@app.exception_handler(EntryNotFound)
@app.exception_handler(InvalidCursor)
@app.exception_handler(InvalidSubscriptionReference)
@app.exception_handler(InvalidFeedUrl)
@app.exception_handler(FeedRejectedError)
@app.exception_handler(SubscriptionConflict)
@app.exception_handler(SubscriptionNotFound)
@app.exception_handler(InvalidCategoryReference)
@app.exception_handler(InvalidCategoryLabel)
@app.exception_handler(CategoryNotFound)
@app.exception_handler(CategoryLabelConflict)
@app.exception_handler(DefaultCategoryImmutable)
@app.exception_handler(UnsafeFeedUrl)
@app.exception_handler(FeedFetchError)
@app.exception_handler(FeedTooLarge)
@app.exception_handler(NotAFeedError)
@app.exception_handler(OpmlInvalid)
@app.exception_handler(OpmlTooLarge)
@app.exception_handler(OpmlTooManyFeeds)
@app.exception_handler(InvalidSourceUrl)
@app.exception_handler(NoFeedDiscovered)
@app.exception_handler(RssHubNotConfigured)
@app.exception_handler(RssHubRouteNotFound)
@app.exception_handler(RssHubInvalidParameters)
@app.exception_handler(RssHubFetchError)
@app.exception_handler(InvalidAiSettings)
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


def _get_control_adapter(request: Request) -> FreshRSSControlAdapter:
    """Control-plane adapter over the SAME session as the read adapter.

    Login / action-token state stays owned by the single FreshRSSAdapter
    instance (which is a FreshRSSSession); the control adapter only borrows
    it, so credentials and tokens are never duplicated.
    """
    control = request.app.state.freshrss_control_adapter
    if control is None:
        control = FreshRSSControlAdapter(_get_adapter(request))
        request.app.state.freshrss_control_adapter = control
    return control


class SubscriptionCreate(BaseModel):
    """POST /api/v1/subscriptions body.

    feedUrl must be an absolute http(s) URL (validated before FreshRSS);
    categoryId, when given, must exist (404 otherwise); title is optional
    (a blank title is treated as absent — the feed's own title is used).
    """

    feedUrl: str = Field(min_length=1)
    categoryId: str | None = None
    title: str | None = None


class FeedPreviewRequest(BaseModel):
    """POST /api/v1/feed-preview body (0013 Gate 2)."""

    feedUrl: str = Field(min_length=1)


class SubscriptionPatch(BaseModel):
    """PATCH /api/v1/subscriptions/{ref} body: move to another category.

    Exactly one target: categoryId (an existing category, 404 when unknown)
    or newCategoryLabel (a new category created by the move itself — the
    only FreshRSS control path that creates categories; conflict-checked
    before any write).
    """

    categoryId: str | None = Field(default=None, min_length=1)
    newCategoryLabel: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def exactly_one_target(self) -> "SubscriptionPatch":
        if (self.categoryId is None) == (self.newCategoryLabel is None):
            raise ValueError(
                "Provide exactly one of 'categoryId' or 'newCategoryLabel'."
            )
        return self


class CategoryPatch(BaseModel):
    """PATCH /api/v1/categories/{categoryId} body: rename the category."""

    label: str = Field(min_length=1)


@app.get("/api/v1/subscriptions")
async def subscriptions(request: Request) -> list[dict[str, object]]:
    """Management view of all subscriptions (0013).

    Each item carries the Lumi-owned opaque subscriptionRef (built from
    FreshRSS's feed/<N> stream id — clients never assemble ids themselves)
    plus title/feedUrl/category. The read path (GET /api/v1/feeds) stays
    untouched and compatible.
    """
    control = _get_control_adapter(request)
    return [
        _subscription_json(subscription)
        for subscription in await control.list_subscriptions()
    ]


@app.get("/api/v1/categories")
async def categories(request: Request) -> list[dict[str, str]]:
    """All categories including empty ones (tag/list folders).

    Same id/label contract as the category objects on /api/v1/feeds —
    there is exactly one category model in Lumi.
    """
    control = _get_control_adapter(request)
    return [
        {"id": category.id, "label": category.label}
        for category in await control.list_categories()
    ]


@app.post("/api/v1/subscriptions", status_code=201)
async def create_subscription(
    subscription: SubscriptionCreate, request: Request
) -> dict[str, object]:
    """Subscribe to a feed URL; returns the server-confirmed subscription.

    409 when already subscribed (checked before any write); 400 feed_rejected
    when FreshRSS cannot add the feed. The write is attempted exactly once
    (no retry on timeout — clients re-read and reconcile).
    """
    control = _get_control_adapter(request)
    created = await control.subscribe(
        subscription.feedUrl,
        category_id=subscription.categoryId,
        title=subscription.title,
    )
    return _subscription_json(created)


def _get_preview_service(request: Request) -> FeedPreviewService:
    """Preview service over the shared HTTP client + control adapter.

    Built lazily like the adapters (tests may inject a fake onto
    app.state.feed_preview_service).
    """
    service = request.app.state.feed_preview_service
    if service is None:
        service = FeedPreviewService(
            request.app.state.http_client, _get_control_adapter(request)
        )
        request.app.state.feed_preview_service = service
    return service


@app.post("/api/v1/feed-preview")
async def preview_feed(
    body: FeedPreviewRequest, request: Request
) -> dict[str, object]:
    """Preview a direct RSS/Atom URL — strictly NON-MUTATING.

    safe fetch → bounded bytes → offline parse. Reads the FreshRSS
    subscription list (alreadySubscribed) but never writes anything:
    subscribing is POST /api/v1/subscriptions. Only reliable metadata is
    returned — no entries, no scraping, no feed discovery.
    """
    service = _get_preview_service(request)
    preview = await service.preview(body.feedUrl)
    return {
        "title": preview.title,
        "feedUrl": preview.feed_url,
        "siteUrl": preview.site_url,
        "description": preview.description,
        "format": preview.format,
        "alreadySubscribed": preview.already_subscribed,
    }


class SourceDiscoveryRequest(BaseModel):
    """POST /api/v1/source-discovery body (0014): a public website URL."""

    url: str = Field(min_length=1)


def _get_discovery_service(request: Request) -> SourceDiscoveryService:
    """SourceDiscoveryService over the shared HTTP client (lazy, cached).

    Holds NO FreshRSS reference by design — discovery is read-only against
    the discovered website.
    """
    service = request.app.state.source_discovery_service
    if service is None:
        service = SourceDiscoveryService(request.app.state.http_client)
        request.app.state.source_discovery_service = service
    return service


@app.post("/api/v1/source-discovery")
async def source_discovery(
    body: SourceDiscoveryRequest, request: Request
) -> dict[str, object]:
    """Discover RSS/Atom feed candidates for a website — NON-MUTATING.

    Safe-fetches ONE page (never crawls), extracts explicit rel=alternate
    declarations, and only when there are none probes a bounded set of
    common feed endpoints. Candidates are not subscribed here — preview is
    POST /api/v1/feed-preview, subscribing is POST /api/v1/subscriptions.
    """
    service = _get_discovery_service(request)
    candidates = await service.discover(body.url)
    return {
        "candidates": [
            {
                "feedUrl": candidate.feed_url,
                "title": candidate.title,
                "source": candidate.source,
                "format": candidate.format,
            }
            for candidate in candidates
        ]
    }


class RssHubPreviewRequest(BaseModel):
    """POST /api/v1/rsshub/preview body (0014): route + parameter values."""

    routeId: str = Field(min_length=1)
    params: dict[str, str] = Field(default_factory=dict)


def _get_rsshub_service(request: Request) -> RssHubService:
    """RssHubService over the shared HTTP client + control adapter.

    Built lazily like the other services; the control adapter is only
    READ (alreadySubscribed) — preview never mutates subscriptions.
    """
    service = request.app.state.rsshub_service
    if service is None:
        service = RssHubService(
            request.app.state.http_client, _get_control_adapter(request)
        )
        request.app.state.rsshub_service = service
    return service


@app.get("/api/v1/rsshub/routes")
async def rsshub_routes(request: Request) -> dict[str, object]:
    """Lumi-owned RSSHub route catalog (static, always available).

    ``configured`` reports whether the server has an RSSHUB_BASE_URL —
    the catalog itself is independent of the instance. Route descriptors
    carry enough metadata for the Web to render parameter forms; path
    construction happens server-side on preview.
    """
    service = _get_rsshub_service(request)
    try:
        service.load_settings()
        configured = True
    except RssHubNotConfigured:
        configured = False
    return {
        "configured": configured,
        "routes": [
            {
                "id": route.id,
                "title": route.title,
                "description": route.description,
                "pathTemplate": route.path_template,
                "parameters": [
                    {
                        "key": parameter.key,
                        "label": parameter.label,
                        "required": parameter.required,
                        "pattern": parameter.pattern,
                        "example": parameter.example,
                        "help": parameter.help,
                    }
                    for parameter in route.parameters
                ],
            }
            for route in service.list_routes()
        ],
    }


@app.post("/api/v1/rsshub/preview")
async def rsshub_preview(
    body: RssHubPreviewRequest, request: Request
) -> dict[str, object]:
    """Preview one configured RSSHub route — NON-MUTATING.

    Constructs the path server-side (validated + encoded parameters),
    fetches the generated feed from the server-configured RSSHub
    instance, parses offline and reads the subscription list for
    alreadySubscribed. The returned feedUrl is the FreshRSS-facing
    subscription URL; subscribing is POST /api/v1/subscriptions (0013).
    """
    service = _get_rsshub_service(request)
    preview = await service.preview(body.routeId, body.params)
    return {
        "title": preview.title,
        "feedUrl": preview.feed_url,
        "siteUrl": preview.site_url,
        "description": preview.description,
        "format": preview.format,
        "alreadySubscribed": preview.already_subscribed,
    }


@app.patch("/api/v1/subscriptions/{subscription_ref}", status_code=204)
async def update_subscription(
    subscription_ref: str,
    update: SubscriptionPatch,
    request: Request,
) -> Response:
    """Move one subscription to another category (single-category model).

    Invalid refs and invalid bodies are rejected before any FreshRSS call.
    With newCategoryLabel the move creates the target category (explicit
    create-category path, 0013 Gate 3); with categoryId the target must
    already exist (404 otherwise).
    """
    stream_id = decode_subscription_ref(subscription_ref)  # raises → 400
    control = _get_control_adapter(request)
    if update.newCategoryLabel is not None:
        await control.move_to_new_category(stream_id, update.newCategoryLabel)
    else:
        assert update.categoryId is not None  # exactly-one validator
        await control.move_category(stream_id, update.categoryId)
    return Response(status_code=204)


@app.delete("/api/v1/subscriptions/{subscription_ref}", status_code=204)
async def delete_subscription(
    subscription_ref: str, request: Request
) -> Response:
    """Unsubscribe (destructive; confirmation belongs to the Web UI)."""
    stream_id = decode_subscription_ref(subscription_ref)  # raises → 400
    control = _get_control_adapter(request)
    await control.unsubscribe(stream_id)
    return Response(status_code=204)


@app.patch("/api/v1/categories/{category_id:path}", status_code=204)
async def rename_category(
    category_id: str, update: CategoryPatch, request: Request
) -> Response:
    """Rename one category.

    categoryId is a user/-/label/<名> reference (path converter: slashes in
    the id are fine). 409 category_label_conflict for taken/reserved labels;
    409 default_category_immutable — the FreshRSS default category cannot be
    renamed through the greader API (display name is always re-localized).
    """
    control = _get_control_adapter(request)
    await control.rename_category(category_id, update.label)
    return Response(status_code=204)


async def _read_bounded_opml(request: Request) -> bytes:
    """Read the raw OPML upload with a hard size cap (never buffers more
    than MAX_OPML_BYTES + one chunk before rejecting)."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_OPML_BYTES:
            raise OpmlTooLarge("OPML file exceeds the 2 MiB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


@app.get("/api/v1/opml/export")
async def opml_export(request: Request) -> Response:
    """Download the FreshRSS OPML export (subscriptions + categories only).

    Proxied through the BFF so the browser never learns FreshRSS
    credentials. The document contains no settings dump, no API keys, no
    read history and no favorites — only the subscription outline tree
    FreshRSS itself produces.
    """
    control = _get_control_adapter(request)
    xml = await control.export_opml()
    return Response(
        content=xml,
        media_type="text/x-opml; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="LumiRSS-subscriptions.opml"'
        },
    )


@app.post("/api/v1/opml/import/preview")
async def opml_import_preview(request: Request) -> dict[str, object]:
    """Parse an uploaded OPML and report what an import WOULD do.

    Strictly non-mutating: bounded read → defusedxml parse → counts
    (new / duplicates / invalid / per-category). Duplicates are only the
    reliably detectable kind: exact feed-URL matches against the current
    FreshRSS subscriptions (plus repeats inside the file). Importing is
    POST /api/v1/opml/import.
    """
    data = await _read_bounded_opml(request)
    service = OpmlService(_get_control_adapter(request))
    return await service.preview(data)


@app.post("/api/v1/opml/import")
async def opml_import(request: Request) -> dict[str, object]:
    """Merge-import an OPML: subscribe each NEW feed, categorize it, report.

    Merge-only — existing subscriptions are reported as duplicates and
    never modified, nothing is unsubscribed or overwritten (destructive
    restore is out of 0013 scope). Per-feed failures (rejected feeds,
    upstream timeouts) are reported honestly in the result; the file is
    re-parsed and the subscription list re-read at import time, so the
    preview is advisory, never a stale contract.
    """
    data = await _read_bounded_opml(request)
    service = OpmlService(_get_control_adapter(request))
    return await service.import_opml(data)


@app.get("/api/v1/freshrss-ui")
async def freshrss_ui(request: Request) -> dict[str, str | None]:
    """Browser-safe public URL of the FreshRSS web UI, or null.

    The advanced escape hatch ("在 FreshRSS 中管理") is only offered when
    the operator explicitly configured FRESHRSS_PUBLIC_URL. The internal
    FRESHRSS_BASE_URL (possibly a Docker hostname or loopback address) is
    never exposed to the browser, and no URL ever carries credentials.
    """
    try:
        settings = FreshRSSSettings()
    except ValidationError:
        return {"url": None}
    return {"url": settings.FRESHRSS_PUBLIC_URL or None}


def _subscription_json(subscription) -> dict[str, object]:
    return {
        "subscriptionRef": subscription.subscription_ref,
        "title": subscription.title,
        "feedUrl": subscription.feed_url,
        "category": (
            {"id": subscription.category_id, "label": subscription.category_label}
            if subscription.category_id is not None
            and subscription.category_label is not None
            else None
        ),
    }


def _get_ai_settings_store(request: Request) -> AiSettingsStore:
    """Persistent AI settings store over the Lumi SQLite database (lazy)."""
    store = request.app.state.ai_settings_store
    if store is None:
        store = AiSettingsStore(request.app.state.db)
        request.app.state.ai_settings_store = store
    return store


def _ai_settings_json(values: dict[str, str]) -> dict[str, object]:
    """Browser-safe AI settings view — NEVER contains the API key."""
    return {
        "provider": values[KEY_PROVIDER],
        "baseUrl": values[KEY_BASE_URL],
        "model": values[KEY_MODEL],
        "summaryLanguage": values[KEY_SUMMARY_LANGUAGE],
        "configured": LumiSettings().ai_configured,
    }


@app.get("/api/v1/settings/ai")
async def get_ai_settings(request: Request) -> dict[str, object]:
    """Current AI settings. ``configured`` only reports whether the server
    has an API key — the key itself never leaves the BFF."""
    store = _get_ai_settings_store(request)
    return _ai_settings_json(await store.load())


@app.put("/api/v1/settings/ai")
async def put_ai_settings(
    update: AiSettingsUpdate, request: Request
) -> dict[str, object]:
    """Persist non-secret AI settings (each provided field validated).

    There is deliberately no API-key field here: the key is server
    environment only, and this endpoint can never read or write it.
    """
    store = _get_ai_settings_store(request)
    return _ai_settings_json(await store.save(update))
