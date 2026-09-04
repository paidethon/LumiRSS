"""LumiRSS BFF application entry point."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

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
    KEY_TRANSLATION_LANGUAGE,
)
from lumirss.app_settings import (
    AppSettingsStore,
    InvalidAppSettings,
    PortableSettingsPatch,
)
from lumirss.ai_provider import (
    AiAuthError,
    AiInvalidResponse,
    AiModelError,
    AiNotConfigured,
    AiRateLimited,
    AiTimeout,
    AiUpstreamError,
    provider_from_settings,
)
from lumirss.ai_summary import AiContentUnavailable, SummaryService
from lumirss.ai_translation import TranslationService
from lumirss.ai_conversation import ConversationService, MAX_QUESTION_CHARS
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
from lumirss.secrets_store import SecretsStore, SecretsStoreError
from lumirss.operations import OperationsService
from lumirss.rsshub_control import (
    RssHubControlError,
    RssHubControlStore,
    RssHubInvalidValue,
    RssHubUnknownKey,
    config_view,
)
from lumirss.backup import (
    BackupBusy,
    BackupChecksumMismatch,
    BackupEngine,
    BackupFreshrssUnavailable,
    BackupInvalid,
    BackupJobStore,
    BackupNotFound,
    BackupUnsupportedVersion,
    WebDavSettingsStore,
    _job_json,
)
from lumirss.restore import (
    RestoreConfirmationRequired,
    RestoreFailed,
    RestorePreviewRequired,
    RestoreService,
)
from lumirss.webdav import WebDavError, WebDavNotConfigured


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
    app.state.secrets_store = SecretsStore(LumiSettings().secrets_path)
    app.state.ai_settings_store = None
    app.state.app_settings_store = None
    app.state.summary_service = None
    app.state.translation_service = None
    app.state.conversation_service = None
    app.state.freshrss_adapter = None
    app.state.freshrss_control_adapter = None
    app.state.feed_preview_service = None
    app.state.source_discovery_service = None
    app.state.rsshub_service = None
    app.state.operations_service = None
    app.state.rsshub_control_store = None
    app.state.backup_jobs = None
    app.state.webdav_settings = None
    app.state.backup_engine = None
    app.state.restore_service = None
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="LumiRSS BFF", lifespan=lifespan)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """Liveness: only proves this process is alive, never touches FreshRSS."""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready(request: Request) -> JSONResponse:
    """Readiness: core dependency (lumi.sqlite) must be usable.

    FreshRSS / RSSHub are reported but NEVER fail readiness — RSSHub being
    down must not make already-fetched reading unavailable (0018 failure
    isolation, AD-0018-3).
    """
    service = _get_operations_service(request)
    ready, payload = await service.ready()
    return JSONResponse(status_code=200 if ready else 503, content=payload)


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
    # 0017 portable app settings
    InvalidAppSettings: (400, "invalid_app_settings"),
    # 0015 AI summary
    AiNotConfigured: (503, "ai_not_configured"),
    AiAuthError: (502, "ai_auth_error"),
    AiModelError: (502, "ai_model_error"),
    AiRateLimited: (429, "ai_rate_limited"),
    AiTimeout: (504, "ai_timeout"),
    AiInvalidResponse: (502, "ai_invalid_response"),
    AiUpstreamError: (502, "ai_upstream_error"),
    AiContentUnavailable: (422, "ai_content_unavailable"),
    # 0018 RSSHub control（spec 稳定错误类型：unknown_key / invalid_value）
    RssHubControlError: (400, "rsshub_invalid_value"),
    RssHubUnknownKey: (400, "rsshub_unknown_key"),
    RssHubInvalidValue: (400, "rsshub_invalid_value"),
    # 0018 backup / WebDAV / restore
    BackupBusy: (409, "backup_busy"),
    BackupNotFound: (404, "backup_not_found"),
    BackupInvalid: (400, "backup_invalid"),
    BackupChecksumMismatch: (400, "backup_checksum_mismatch"),
    BackupUnsupportedVersion: (409, "backup_unsupported_version"),
    BackupFreshrssUnavailable: (503, "backup_freshrss_unavailable"),
    WebDavNotConfigured: (503, "webdav_not_configured"),
    WebDavError: (502, "webdav_error"),
    RestoreConfirmationRequired: (400, "backup_restore_confirmation_required"),
    RestorePreviewRequired: (400, "backup_restore_preview_required"),
    RestoreFailed: (500, "restore_failed"),
    SecretsStoreError: (500, "secret_store_error"),
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
@app.exception_handler(InvalidAppSettings)
@app.exception_handler(InvalidAiSettings)
@app.exception_handler(AiNotConfigured)
@app.exception_handler(AiAuthError)
@app.exception_handler(AiModelError)
@app.exception_handler(AiRateLimited)
@app.exception_handler(AiTimeout)
@app.exception_handler(AiInvalidResponse)
@app.exception_handler(AiUpstreamError)
@app.exception_handler(AiContentUnavailable)
@app.exception_handler(RssHubControlError)
@app.exception_handler(RssHubUnknownKey)
@app.exception_handler(RssHubInvalidValue)
@app.exception_handler(BackupBusy)
@app.exception_handler(BackupNotFound)
@app.exception_handler(BackupInvalid)
@app.exception_handler(BackupChecksumMismatch)
@app.exception_handler(BackupUnsupportedVersion)
@app.exception_handler(BackupFreshrssUnavailable)
@app.exception_handler(WebDavNotConfigured)
@app.exception_handler(WebDavError)
@app.exception_handler(RestoreConfirmationRequired)
@app.exception_handler(RestorePreviewRequired)
@app.exception_handler(RestoreFailed)
@app.exception_handler(SecretsStoreError)
async def adapter_error_handler(request: Request, exc: Exception) -> JSONResponse:
    status, error_type = _ERROR_RESPONSES[type(exc)]
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": str(exc)}},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic validation failures join the stable error envelope.

    Keeps the 422 status (existing contract) but never echoes request
    details back — the message is a static string."""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "type": "invalid_request",
                "message": "The request body failed validation.",
            }
        },
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
        "translationLanguage": values[KEY_TRANSLATION_LANGUAGE],
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


def _get_app_settings_store(request: Request) -> AppSettingsStore:
    """Persistent portable settings store over the Lumi SQLite database."""
    store = request.app.state.app_settings_store
    if store is None:
        store = AppSettingsStore(request.app.state.db)
        request.app.state.app_settings_store = store
    return store


def _reject_nonfinite(value: str) -> float:
    """Refuse NaN/Infinity/… JSON number tokens before pydantic sees them."""
    raise InvalidAppSettings(f"non-finite number '{value}' is not allowed")


def _parse_settings_patch(raw: bytes) -> PortableSettingsPatch:
    """Strict body parsing: every invalid payload becomes a stable 400."""
    import json as _json

    try:
        parsed = _json.loads(raw, parse_constant=_reject_nonfinite)
    except (_json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidAppSettings("request body must be a valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise InvalidAppSettings("request body must be a JSON object")
    try:
        return PortableSettingsPatch.model_validate(parsed)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        raise InvalidAppSettings(
            f"Invalid {location}: {first.get('msg', 'value rejected')}"
        ) from exc


def _app_settings_json(document, stored: bool) -> dict[str, object]:
    """Browser-safe portable settings view — no secrets exist by design."""
    payload = document.model_dump()
    return {"schemaVersion": payload["schemaVersion"], "stored": stored, **payload}


@app.get("/api/v1/settings")
async def get_app_settings(request: Request) -> dict[str, object]:
    """Current portable settings (defaults when nothing was ever stored).

    ``stored`` reports whether the server holds an explicit document — the
    client seeds it from its local values on first visit (migration) and
    treats it as authoritative afterwards. GET never mutates anything.
    """
    store = _get_app_settings_store(request)
    document, stored = await store.load()
    return _app_settings_json(document, stored)


@app.patch("/api/v1/settings")
async def patch_app_settings(request: Request) -> dict[str, object]:
    """Persist a partial portable settings update (strictly validated).

    The body is parsed manually so that EVERY invalid payload — unknown
    key, wrong type, out-of-range, NaN/Infinity, malformed JSON — is
    rejected with the stable 400 invalid_app_settings error (FastAPI's
    default 422 serialization crashes on non-finite numbers). There is
    deliberately no field that can carry any secret.
    """
    update = _parse_settings_patch(await request.body())
    store = _get_app_settings_store(request)
    try:
        merged = await store.save(update)
    except ValueError as exc:
        raise InvalidAppSettings(str(exc)) from exc
    return _app_settings_json(merged, True)


@app.delete("/api/v1/settings", status_code=204)
async def delete_app_settings(request: Request) -> Response:
    """Reset portable settings to defaults (removes the stored document).

    The next GET reports stored=false again; the client may re-seed from
    its local values afterwards.
    """
    store = _get_app_settings_store(request)
    await store.reset()
    return Response(status_code=204)


def _get_summary_service(request: Request) -> SummaryService:
    """Cached summary service over the shared DB / adapter / settings.

    The provider factory injects the env API key (server-side only) at
    generation time; reading cache state never builds a provider.
    """
    service = request.app.state.summary_service
    if service is None:
        service = SummaryService(
            db=request.app.state.db,
            adapter=_get_adapter(request),
            settings_store=_get_ai_settings_store(request),
            provider_factory=_provider_factory_for(request),
        )
        request.app.state.summary_service = service
    return service


def _provider_factory_for(request: Request):
    """Provider factory shared by all AI services (0015 + 0016).

    Injects the env API key at call time — server-side only, never built
    for read-only cache lookups.
    """

    def factory(base_url: str, model: str):
        return provider_from_settings(
            request.app.state.http_client,
            LumiSettings(),
            base_url=base_url,
            model=model,
        )

    return factory


def _get_translation_service(request: Request) -> TranslationService:
    """Cached translation service (0016) — same wiring as summaries."""
    service = request.app.state.translation_service
    if service is None:
        service = TranslationService(
            db=request.app.state.db,
            adapter=_get_adapter(request),
            settings_store=_get_ai_settings_store(request),
            provider_factory=_provider_factory_for(request),
        )
        request.app.state.translation_service = service
    return service


def _get_conversation_service(request: Request) -> ConversationService:
    """Article-scoped conversation service (0016) — same wiring."""
    service = request.app.state.conversation_service
    if service is None:
        service = ConversationService(
            db=request.app.state.db,
            adapter=_get_adapter(request),
            settings_store=_get_ai_settings_store(request),
            provider_factory=_provider_factory_for(request),
        )
        request.app.state.conversation_service = service
    return service


def _summary_json(state) -> dict[str, object]:
    """Browser-safe summary view — no secrets, no raw provider output."""
    return {
        "status": state.status,
        "summary": state.summary,
        "provider": state.provider,
        "model": state.model,
        "promptVersion": state.prompt_version,
        "language": state.language,
        "generatedAt": state.generated_at,
        "failureType": state.failure_type,
        "cached": state.cached,
    }


@app.get("/api/v1/entries/{entry_ref}/summary")
async def get_entry_summary(entry_ref: str, request: Request) -> dict[str, object]:
    """Read-only summary state. NEVER calls the AI provider (no cost):
    only FreshRSS read + the Lumi cache are consulted."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_summary_service(request)
    return _summary_json(await service.get_summary(entry_ref))


@app.post("/api/v1/entries/{entry_ref}/summary")
async def generate_entry_summary(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """Explicit summary generation. An exact cache hit costs nothing;
    otherwise exactly one bounded provider call is made (synchronously)."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_summary_service(request)
    return _summary_json(await service.generate_summary(entry_ref))


def _translation_json(state) -> dict[str, object]:
    """Browser-safe translation view — no secrets, plain text output."""
    return {
        "status": state.status,
        "translatedTitle": state.translated_title,
        "translatedText": state.translated_text,
        "provider": state.provider,
        "model": state.model,
        "promptVersion": state.prompt_version,
        "targetLanguage": state.target_language,
        "generatedAt": state.generated_at,
        "failureType": state.failure_type,
        "cached": state.cached,
    }


@app.get("/api/v1/entries/{entry_ref}/translation")
async def get_entry_translation(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """Read-only translation state. NEVER calls the AI provider (no cost):
    only FreshRSS read + the Lumi cache are consulted."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_translation_service(request)
    return _translation_json(await service.get_translation(entry_ref))


@app.post("/api/v1/entries/{entry_ref}/translation")
async def generate_entry_translation(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """Explicit translation generation. An exact cache hit costs nothing;
    otherwise exactly one bounded provider call is made (synchronously).
    The original article is never modified or written back to FreshRSS."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_translation_service(request)
    return _translation_json(await service.generate_translation(entry_ref))


class ConversationQuestion(BaseModel):
    """POST /api/v1/entries/{entryRef}/conversation/messages body (0016).

    Bounded question; blank-after-strip is rejected before any provider
    work (422 via FastAPI validation).
    """

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


def _conversation_json(state) -> dict[str, object]:
    """Browser-safe conversation view — plain text messages only."""
    return {
        "status": state.status,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "createdAt": message.created_at,
            }
            for message in state.messages
        ],
    }


@app.get("/api/v1/entries/{entry_ref}/conversation")
async def get_entry_conversation(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """Read-only conversation state for this article. NEVER calls the
    provider: only FreshRSS read + the Lumi message store."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_conversation_service(request)
    return _conversation_json(await service.get_conversation(entry_ref))


@app.post("/api/v1/entries/{entry_ref}/conversation/messages")
async def send_conversation_message(
    entry_ref: str, body: ConversationQuestion, request: Request
) -> dict[str, object]:
    """Ask one article-scoped question. Exactly one bounded provider call
    (synchronously); on success the question and the reply are persisted
    and the full conversation is returned."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_conversation_service(request)
    return _conversation_json(
        await service.send_message(entry_ref, body.question)
    )


# ---------------------------------------------------------------------------
# 0018 — Operations, RSSHub Control Center, Backup / WebDAV / Restore
# ---------------------------------------------------------------------------

def _get_operations_service(request: Request) -> OperationsService:
    service = request.app.state.operations_service
    if service is None:
        service = OperationsService(request.app.state.http_client, request.app.state.db)
        request.app.state.operations_service = service
    return service


def _get_rsshub_control_store(request: Request) -> RssHubControlStore:
    store = request.app.state.rsshub_control_store
    if store is None:
        store = RssHubControlStore(request.app.state.db, request.app.state.secrets_store)
        request.app.state.rsshub_control_store = store
    return store


def _get_backup_jobs(request: Request) -> BackupJobStore:
    jobs = request.app.state.backup_jobs
    if jobs is None:
        jobs = BackupJobStore(request.app.state.db)
        request.app.state.backup_jobs = jobs
    return jobs


def _get_webdav_settings(request: Request) -> WebDavSettingsStore:
    store = request.app.state.webdav_settings
    if store is None:
        store = WebDavSettingsStore(request.app.state.db, request.app.state.secrets_store)
        request.app.state.webdav_settings = store
    return store


def _get_backup_engine(request: Request) -> BackupEngine:
    engine = request.app.state.backup_engine
    if engine is None:
        jobs = _get_backup_jobs(request)
        webdav = _get_webdav_settings(request)

        async def webdav_factory():
            doc = await webdav.load()
            return await webdav.build_client(doc)

        engine = BackupEngine(request.app.state.db, jobs, webdav, webdav_factory)
        request.app.state.backup_engine = engine
    return engine


def _get_restore_service(request: Request) -> RestoreService:
    service = request.app.state.restore_service
    if service is None:
        engine = _get_backup_engine(request)
        service = RestoreService(
            request.app.state.db,
            LumiSettings(),
            engine.create_safety_backup,
        )
        request.app.state.restore_service = service
    return service


def _rsshub_runtime_configured() -> bool:
    from lumirss.config import RssHubSettings

    from pydantic import ValidationError as _ValidationError

    try:
        return bool(RssHubSettings().RSSHUB_BASE_URL)
    except _ValidationError:
        return False


@app.get("/api/v1/operations/status")
async def operations_status(request: Request) -> dict[str, object]:
    """Redacted, real dependency status for the operations UI (no fake metrics)."""
    service = _get_operations_service(request)
    status = await service.full_status()
    rsshub_store = _get_rsshub_control_store(request)
    flags = await rsshub_store.restart_required_flags()
    status["rsshub"]["restartRequired"] = flags["count"] > 0
    status["rsshub"]["pendingConfigCount"] = flags["count"]
    webdav = _get_webdav_settings(request)
    doc = await webdav.load()
    jobs = _get_backup_jobs(request)
    last = await jobs.last_succeeded()
    status["backup"] = {
        "webdavConfigured": webdav.configured(doc),
        "lastBackup": _job_json(last) if last else None,
    }
    return status


class RssHubConfigPatch(BaseModel):
    """PATCH /api/v1/rsshub/config body: allow-listed non-secret values."""

    values: dict[str, object] = Field(default_factory=dict)


async def _rsshub_config_view_async(request: Request) -> dict[str, object]:
    store = _get_rsshub_control_store(request)
    desired = await store.desired()
    flags = await store.restart_required_flags()
    return {
        "schemaVersion": 1,
        "configured": _rsshub_runtime_configured(),
        "pendingCount": flags["count"],
        "pendingSecrets": flags["pendingSecrets"],
        "groups": config_view(store, desired, flags),
    }


@app.get("/api/v1/rsshub/config")
async def get_rsshub_config(request: Request) -> dict[str, object]:
    return await _rsshub_config_view_async(request)


@app.patch("/api/v1/rsshub/config")
async def patch_rsshub_config(
    body: RssHubConfigPatch, request: Request
) -> dict[str, object]:
    """Update allow-listed non-secret desired values (validated + typed).

    Secrets are never accepted here — use the secret endpoints. Saving only
    updates the DESIRED config; the UI reports restartRequired honestly.
    """
    store = _get_rsshub_control_store(request)
    await store.patch_desired({k: v for k, v in body.values.items()})
    return await _rsshub_config_view_async(request)


@app.get("/api/v1/rsshub/config/export")
async def export_rsshub_config(request: Request) -> Response:
    """Render the desired config as an env fragment (secrets never echoed)."""
    from lumirss.rsshub_control import export_env

    store = _get_rsshub_control_store(request)
    desired = await store.desired()
    return Response(
        content=export_env(store, desired),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rsshub.env"'},
    )


class RssHubSecretPut(BaseModel):
    value: str = Field(min_length=1)


@app.put("/api/v1/rsshub/config/secrets/{key}", status_code=204)
async def put_rsshub_secret(
    key: str, body: RssHubSecretPut, request: Request
) -> Response:
    """Write one route credential / secret (write-only, never read back)."""
    store = _get_rsshub_control_store(request)
    await store.set_secret(key, body.value)
    return Response(status_code=204)


@app.delete("/api/v1/rsshub/config/secrets/{key}", status_code=204)
async def delete_rsshub_secret(key: str, request: Request) -> Response:
    """Clear one secret (explicit action)."""
    store = _get_rsshub_control_store(request)
    await store.delete_secret(key)
    return Response(status_code=204)


@app.post("/api/v1/rsshub/config/apply", status_code=204)
async def apply_rsshub_config(request: Request) -> Response:
    """Operator confirms the desired config has been applied after restart."""
    store = _get_rsshub_control_store(request)
    await store.mark_applied()
    return Response(status_code=204)


class WebDavSettingsPut(BaseModel):
    """PUT /api/v1/backups/webdav body.

    password omitted/None = keep existing; non-empty = set; clearPassword
    is the ONLY way to clear it (empty-string password never clears)."""

    serverUrl: str | None = None
    username: str | None = None
    password: str | None = None
    remoteDir: str | None = None
    tlsVerify: bool | None = None
    clearPassword: bool = False

    @model_validator(mode="after")
    def password_semantics(self) -> "WebDavSettingsPut":
        if self.password is not None and not self.password and not self.clearPassword:
            raise ValueError("use clearPassword=true to clear (empty string does not clear)")
        if self.password is not None and self.clearPassword:
            raise ValueError("provide either password or clearPassword, not both")
        return self


def _webdav_json(doc: dict, password_configured: bool) -> dict[str, object]:
    return {
        "configured": bool(doc.get("serverUrl")) and password_configured,
        "serverUrl": doc.get("serverUrl", ""),
        "username": doc.get("username", ""),
        "remoteDir": doc.get("remoteDir", ""),
        "tlsVerify": bool(doc.get("tlsVerify", True)),
        "passwordConfigured": password_configured,
    }


@app.get("/api/v1/backups/webdav")
async def get_webdav_settings(request: Request) -> dict[str, object]:
    store = _get_webdav_settings(request)
    doc = await store.load()
    return _webdav_json(doc, store.password_configured())


@app.put("/api/v1/backups/webdav")
async def put_webdav_settings(
    body: WebDavSettingsPut, request: Request
) -> dict[str, object]:
    """Update WebDAV settings (password write-only, never read back)."""
    store = _get_webdav_settings(request)
    update: dict[str, object] = {}
    if body.serverUrl is not None:
        update["serverUrl"] = body.serverUrl
    if body.username is not None:
        update["username"] = body.username
    if body.remoteDir is not None:
        update["remoteDir"] = body.remoteDir
    if body.tlsVerify is not None:
        update["tlsVerify"] = body.tlsVerify
    doc = await store.save(update)
    if body.clearPassword:
        store.clear_password()
    elif body.password:
        store.set_password(body.password)
    return _webdav_json(doc, store.password_configured())


@app.post("/api/v1/backups/webdav/test")
async def test_webdav(request: Request) -> dict[str, object]:
    """Test the WebDAV connection: create + list the backup root."""
    from lumirss.webdav import backup_root_path

    store = _get_webdav_settings(request)
    doc = await store.load()
    if not doc.get("serverUrl"):
        raise WebDavNotConfigured("WebDAV is not configured.")
    client = await store.build_client(doc)
    try:
        root = backup_root_path(doc.get("remoteDir", ""))
        await client.ensure_dir(root)
        await client.list_dir(root)
        return {"status": "ok"}
    except WebDavError as exc:
        return {"status": "failed", "message": str(exc)}
    finally:
        await client.aclose()


class BackupCreate(BaseModel):
    target: Literal["local", "webdav"] = "local"


@app.get("/api/v1/backups")
async def list_backups(request: Request) -> list[dict[str, object]]:
    jobs = _get_backup_jobs(request)
    return [_job_json(job) for job in await jobs.list()]


@app.post("/api/v1/backups", status_code=202)
async def create_backup(
    body: BackupCreate, request: Request
) -> dict[str, object]:
    """Create a full backup job (runs in the background; poll the job)."""
    engine = _get_backup_engine(request)
    job = await engine.submit_full_backup(body.target)
    return _job_json(job)


@app.get("/api/v1/backups/remote")
async def list_remote_backups(request: Request) -> dict[str, object]:
    """List backups stored on WebDAV (flat names + sizes, no secret values)."""
    from lumirss.webdav import backup_root_path

    store = _get_webdav_settings(request)
    doc = await store.load()
    if not doc.get("serverUrl"):
        raise WebDavNotConfigured("WebDAV is not configured.")
    client = await store.build_client(doc)
    try:
        entries = await client.list_dir(backup_root_path(doc.get("remoteDir", "")))
    except WebDavError as exc:
        raise exc
    finally:
        await client.aclose()
    return {
        "backups": [
            {"fileName": entry["name"], "sizeBytes": int(entry.get("size") or 0)}
            for entry in entries
            if entry["name"].endswith(".backup")
        ]
    }


@app.get("/api/v1/backups/{job_id}")
async def get_backup_job(job_id: str, request: Request) -> dict[str, object]:
    jobs = _get_backup_jobs(request)
    job = await jobs.get(job_id)
    if job is None:
        raise BackupNotFound("Backup job not found.")
    return _job_json(job)


class RestorePreviewBody(BaseModel):
    source: Literal["local", "remote"]
    jobId: str | None = None
    fileName: str | None = None


class RestoreExecuteBody(BaseModel):
    restoreSessionId: str = Field(min_length=1)
    confirmation: str = Field(min_length=1)


async def _locate_backup_package(
    body: RestorePreviewBody, request: Request
) -> tuple[Path, str]:
    """Return (local zip path, display name) for the requested source."""
    settings = LumiSettings()
    if body.source == "local":
        if not body.jobId:
            raise BackupNotFound("A jobId is required for local restore.")
        jobs = _get_backup_jobs(request)
        job = await jobs.get(body.jobId)
        if job is None:
            raise BackupNotFound("Backup job not found.")
        if job["status"] != "succeeded":
            raise BackupNotFound("Only succeeded backups can be restored.")
        summary = job.get("summary")
        local_path = None
        if isinstance(summary, str) and summary:
            try:
                local_path = json.loads(summary).get("localPath")
            except json.JSONDecodeError:
                local_path = None
        if not local_path:
            raise BackupNotFound("This backup has no local file.")
        path = Path(local_path)
        if not path.is_file():
            raise BackupNotFound("The local backup file is missing.")
        return path, path.name

    # remote
    from lumirss.webdav import backup_root_path, quote_path_segment

    if not body.fileName:
        raise BackupNotFound("A fileName is required for remote restore.")
    # 恶意 WebDAV 服务器可能构造带路径分隔符的 listing 名：本地落盘名
    # 只允许纯文件名（与远端同名文件的匹配仍按原始 fileName 精确比较）。
    if body.fileName != Path(body.fileName).name or body.fileName in ("", ".", ".."):
        raise BackupInvalid("The remote backup file name is not a plain file name.")
    store = _get_webdav_settings(request)
    doc = await store.load()
    if not doc.get("serverUrl"):
        raise WebDavNotConfigured("WebDAV is not configured.")
    client = await store.build_client(doc)
    try:
        root = backup_root_path(doc.get("remoteDir", ""))
        entries = await client.list_dir(root)
        match = next((e for e in entries if e["name"] == body.fileName), None)
        if match is None:
            raise BackupNotFound("Remote backup not found.")
        # Download into a temp file for verification.
        stage = settings.restore_staging_dir / "downloads"
        stage.mkdir(parents=True, exist_ok=True)
        data = await client.get(f"{root}/{quote_path_segment(body.fileName)}")
        dest = stage / body.fileName
        dest.write_bytes(data)
    finally:
        await client.aclose()
    return dest, body.fileName


@app.post("/api/v1/restore/preview")
async def restore_preview(
    body: RestorePreviewBody, request: Request
) -> dict[str, object]:
    """Validate a backup package and return a preview + restoreSessionId."""
    zip_path, name = await _locate_backup_package(body, request)
    service = _get_restore_service(request)
    preview = await service.preview(zip_path)
    preview["fileName"] = name
    return preview


@app.post("/api/v1/restore")
async def restore_execute(
    body: RestoreExecuteBody, request: Request
) -> dict[str, object]:
    """Execute a previously previewed restore (explicit confirmation).

    AD-0018-7: the destructive restore is serialized against backups via the
    engine flag plus a DB-level guard (the guard runs the interrupted sweep
    first, so rows left by a previous process never wedge new work), and is
    recorded in ``backup_jobs`` (type=restore) as a persisted audit trail.

    Subtlety: a successful lumi restore REPLACES the database file, so the
    job row recorded before the swap may vanish with the old file, and the
    restored snapshot may carry stale active rows. After execute the ledger
    is reconciled: stale rows are marked interrupted (nothing can legitimately
    be running once the exclusive restore finished) and the restore record is
    re-created when the swap erased it."""
    engine = _get_backup_engine(request)
    service = _get_restore_service(request)
    jobs = _get_backup_jobs(request)
    if engine.running or await jobs.has_running():
        raise BackupBusy("Another job is already in progress.")
    job = await jobs.create("restore", "restore")
    await jobs.start(job["id"])
    try:
        result = await engine.run_restore(service, body.restoreSessionId, body.confirmation)
    except Exception as exc:
        # run_restore / service.execute 只抛出脱敏后的安全消息（静态文本或
        # RestoreFailed 包装），截断兜底防止异常长的内容进入 job 历史。
        safe = (str(exc).strip() or "The restore failed.")[:300]
        if await jobs.get(job["id"]) is None:
            # 替换后的数据库里已经没有这一行：补一条终态记录
            replacement = await jobs.create("restore", "restore")
            await jobs.start(replacement["id"])
            await jobs.fail(replacement["id"], safe)
        else:
            await jobs.fail(job["id"], safe)
        raise
    # 成功：快照残影的 running/queued 行全部标记 interrupted（restore 互斥，
    # 此刻不可能有真正在跑的 job），然后确保审计记录存在于当前数据库。
    await jobs.mark_stale_active_interrupted(keep_id=job["id"])
    summary = {
        "lumiRestored": result.get("lumiRestored", False),
        "freshrss": result.get("freshrss", "not_included"),
        "safetyBackupId": result.get("safetyBackupId"),
        "filename": body.restoreSessionId,
    }
    if await jobs.get(job["id"]) is None:
        replacement = await jobs.create("restore", "restore")
        await jobs.start(replacement["id"])
        await jobs.succeed(replacement["id"], summary)
    else:
        await jobs.succeed(job["id"], summary)
    return result
