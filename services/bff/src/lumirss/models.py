"""LumiRSS BFF API response models.

One definition point for the API response shapes: FastAPI serializes these
into the OpenAPI schema, making this module the single source of truth that
the web client's ``src/api/types.ts`` mirrors 1:1. Field names are
camelCase directly on the models (no alias generators) to match the wire
format. The entry-domain models (0003/0004) are built directly by the
adapter and returned by the routes, so there is no second mapping layer.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lumirss.app_settings import PortableSettings

# ---------------------------------------------------------------------------
# Entries (0003/0004) — list, detail
# ---------------------------------------------------------------------------


class EntryListItem(BaseModel):
    """One article in the entry list — never contains the body."""

    entryRef: str
    title: str
    feedTitle: str
    author: str | None = None
    url: str | None = None
    publishedAt: str | None = None
    read: bool
    starred: bool


class EntryPage(BaseModel):
    """Adapter-level page: items + the raw FreshRSS continuation.

    The adapter understands upstream continuations only; turning them into
    public nextCursor values (and back) is the route layer's job.
    """

    items: list[EntryListItem]
    upstreamContinuation: str | None


class EntryListResponse(BaseModel):
    """Envelope for GET /api/v1/entries."""

    items: list[EntryListItem]
    nextCursor: str | None


class EntryDetail(BaseModel):
    """One article with its body.

    contentText is the safe plain-text rendering (always present);
    contentHtml is the raw upstream HTML from FreshRSS. contentHtml is
    UNTRUSTED upstream HTML (it comes from external RSS feeds) — the BFF
    only transports it; sanitizing before rendering is the web client's
    responsibility. Missing/empty upstream HTML is normalized to None.
    """

    entryRef: str
    title: str
    feedTitle: str
    author: str | None = None
    url: str | None = None
    publishedAt: str | None = None
    read: bool
    starred: bool
    contentText: str
    contentHtml: str | None = None


# ---------------------------------------------------------------------------
# AI article artifacts (0015/0016) — summary, translation, conversation
# ---------------------------------------------------------------------------


class EntrySummary(BaseModel):
    """GET/POST /api/v1/entries/{entryRef}/summary (browser-safe view)."""

    status: Literal["not_generated", "generating", "success", "failed"]
    summary: str | None = None
    provider: str | None = None
    model: str | None = None
    promptVersion: str | None = None
    language: str | None = None
    generatedAt: str | None = None
    failureType: str | None = None
    cached: bool


class EntryTranslation(BaseModel):
    """GET/POST /api/v1/entries/{entryRef}/translation (plain-text output)."""

    status: Literal["not_generated", "generating", "success", "failed"]
    translatedTitle: str | None = None
    translatedText: str | None = None
    provider: str | None = None
    model: str | None = None
    promptVersion: str | None = None
    targetLanguage: str | None = None
    generatedAt: str | None = None
    failureType: str | None = None
    cached: bool


class ConversationMessage(BaseModel):
    """One article-scoped conversation message (plain text only)."""

    id: int
    role: Literal["user", "assistant"]
    content: str
    createdAt: str


class EntryConversation(BaseModel):
    """GET/POST /api/v1/entries/{entryRef}/conversation(+ /messages)."""

    status: Literal["empty", "active"]
    messages: list[ConversationMessage]


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------


class HealthStatus(BaseModel):
    """GET /health/live — liveness only."""

    status: str


class ComponentError(BaseModel):
    """Redacted component error detail (only ``type`` ever leaves the BFF)."""

    type: str


class ReadinessComponentDetail(BaseModel):
    """One probed component in the readiness payload.

    Superset of the two real shapes (the full status entry with
    latency/error, or the compact healthy SQLite entry with
    schemaVersion) — every optional key stays optional so both shapes
    validate.
    """

    status: str
    latencyMs: int | None = None
    lastCheckedAt: str | None = None
    error: ComponentError | None = None
    schemaVersion: int | None = None


class ReadinessLumi(BaseModel):
    """The lumi component entry (core storage health only)."""

    status: str


class ReadinessComponents(BaseModel):
    """Per-dependency readiness (failure isolation: only sqlite is core)."""

    lumi: ReadinessLumi
    sqlite: ReadinessComponentDetail
    freshrss: str
    rsshub: str


class ReadinessResponse(BaseModel):
    """GET /health/ready (503 with the same shape when sqlite is unusable)."""

    status: Literal["ok", "unavailable"]
    components: ReadinessComponents


# ---------------------------------------------------------------------------
# Feeds, categories, subscriptions (0011/0013)
# ---------------------------------------------------------------------------


class FeedCategory(BaseModel):
    """FreshRSS category (stable id + display label, single-category model)."""

    id: str
    label: str


class Feed(BaseModel):
    """One item of GET /api/v1/feeds (read path; uncategorized → null)."""

    title: str
    feedUrl: str
    category: FeedCategory | None = None


class Category(BaseModel):
    """One item of GET /api/v1/categories (includes empty categories)."""

    id: str
    label: str


class Subscription(BaseModel):
    """GET/POST /api/v1/subscriptions item (0013 management view).

    subscriptionRef is Lumi-owned and opaque; clients never assemble ids.
    """

    subscriptionRef: str
    title: str
    feedUrl: str
    category: FeedCategory | None = None


# ---------------------------------------------------------------------------
# Feed preview, source discovery, RSSHub catalog (0013 Gate 2 / 0014)
# ---------------------------------------------------------------------------


class FeedPreviewResult(BaseModel):
    """POST /api/v1/feed-preview and POST /api/v1/rsshub/preview.

    Only reliable metadata — no entries, no scraping.
    """

    title: str
    feedUrl: str
    siteUrl: str | None = None
    description: str | None = None
    format: Literal["rss", "atom"]
    alreadySubscribed: bool


class DiscoveryCandidate(BaseModel):
    """One discovered feed candidate (declared = not prefetched)."""

    feedUrl: str
    title: str | None = None
    source: Literal["declared", "probed"]
    format: Literal["rss", "atom"] | None = None


class SourceDiscoveryResponse(BaseModel):
    """POST /api/v1/source-discovery (strictly non-mutating)."""

    candidates: list[DiscoveryCandidate]


class RssHubParameter(BaseModel):
    """One RSSHub route parameter descriptor (form-renderable)."""

    key: str
    label: str
    required: bool
    pattern: str
    example: str
    help: str


class RssHubRoute(BaseModel):
    """One Lumi-owned RSSHub route descriptor (path built server-side)."""

    id: str
    title: str
    description: str
    pathTemplate: str
    parameters: list[RssHubParameter]


class RssHubCatalog(BaseModel):
    """GET /api/v1/rsshub/routes (static catalog; configured = instance set)."""

    configured: bool
    routes: list[RssHubRoute]


# ---------------------------------------------------------------------------
# OPML import (0013 Gate 4)
# ---------------------------------------------------------------------------


class OpmlImportPreviewCategory(BaseModel):
    """Per-category feed count in the import preview."""

    label: str
    feedCount: int


class OpmlImportPreview(BaseModel):
    """POST /api/v1/opml/import/preview (strictly non-mutating)."""

    totalFeeds: int
    newFeeds: int
    duplicates: int
    invalidEntries: int
    categories: list[OpmlImportPreviewCategory]


class OpmlImportAdded(BaseModel):
    """One successfully subscribed OPML feed."""

    feedUrl: str
    title: str
    categoryLabel: str | None = None
    categoryApplied: bool


class OpmlImportDuplicate(BaseModel):
    """One feed reported as an existing or in-file repeated subscription."""

    feedUrl: str
    title: str


class OpmlImportFailed(BaseModel):
    """One feed whose subscription failed (stable error code in ``error``)."""

    feedUrl: str
    title: str
    error: str


class OpmlImportResult(BaseModel):
    """POST /api/v1/opml/import (merge-only: duplicates are never touched)."""

    added: list[OpmlImportAdded]
    duplicates: list[OpmlImportDuplicate]
    failed: list[OpmlImportFailed]
    categoriesCreated: list[str]


# ---------------------------------------------------------------------------
# Misc: FreshRSS UI escape hatch, version provenance
# ---------------------------------------------------------------------------


class FreshRssUiInfo(BaseModel):
    """GET /api/v1/freshrss-ui (null url = not configured, UI hides it)."""

    url: str | None = None


# ---------------------------------------------------------------------------
# Session authentication (LUMIRSS_AUTH_MODE=session)
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """POST /api/v1/auth/login — single user, password only."""

    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    """POST /api/v1/auth/password — current + new password."""

    currentPassword: str = Field(min_length=1, max_length=256)
    newPassword: str = Field(min_length=1, max_length=256)


class AuthStatus(BaseModel):
    """Login / session-status payload; expiresAt is an ISO-8601 instant.

    mode tells the web app WHICH auth layer is active: "basic" = proxy
    Basic Auth (the app must not render its own login gate), "session" =
    BFF sessions (gate on ``authenticated``)."""

    authenticated: bool
    mode: Literal["basic", "session"] = "session"
    expiresAt: str | None = None


class ApiVersionInfo(BaseModel):
    """GET /api/v1/version (build provenance for Web/BFF skew diagnosis)."""

    version: str
    commit: str
    apiVersion: int


# ---------------------------------------------------------------------------
# AI settings + profiles (0015/0016) — never carries API key material
# ---------------------------------------------------------------------------


class AiPurposeStatus(BaseModel):
    """Effective, secret-free resolution of one AI purpose."""

    profileId: str
    source: Literal["default", "profile"]
    profileLabel: str | None = None
    baseUrl: str
    model: str
    keyConfigured: bool
    keySource: Literal["profile_secret", "default_secret", "env", "missing"]
    configured: bool


class AiSettingsView(BaseModel):
    """GET/PUT /api/v1/settings/ai (key presence is booleans only)."""

    provider: Literal["openai_compatible"]
    baseUrl: str
    model: str
    summaryLanguage: Literal["zh-CN", "en"]
    translationLanguage: Literal["zh-CN", "en"]
    translationEngine: Literal["ai", "libretranslate", "browser"]
    libretranslateUrl: str
    libretranslateKeyConfigured: bool
    configured: bool
    envKeyConfigured: bool
    defaultKeyConfigured: bool
    purposes: dict[str, str]
    purposeStatus: dict[str, AiPurposeStatus]


class AiProfile(BaseModel):
    """One AI profile (keys surface only as ``keyConfigured``)."""

    id: str
    label: str
    provider: Literal["openai_compatible"]
    baseUrl: str
    model: str
    enabled: bool
    keyConfigured: bool
    createdAt: str
    updatedAt: str


# ---------------------------------------------------------------------------
# Portable app settings (0017)
# ---------------------------------------------------------------------------


class AppSettingsView(PortableSettings):
    """GET/PATCH /api/v1/settings — the portable document + ``stored`` flag.

    ``stored=false`` means the server holds no explicit document yet (the
    client may seed it from local values); otherwise the fields are the
    server-durable values. ``revision`` (0021) is a content-hash of the
    stored document for optimistic concurrency: a PATCH may carry
    ``baseRevision`` and is refused with a stable 409 when it no longer
    matches.
    """

    stored: bool
    revision: int


# ---------------------------------------------------------------------------
# WebDAV, backup jobs, remote listing, restore (0018)
# ---------------------------------------------------------------------------


class WebDavSettingsView(BaseModel):
    """GET/PUT /api/v1/backups/webdav (password is write-only, never read)."""

    configured: bool
    serverUrl: str
    username: str
    remoteDir: str
    tlsVerify: bool
    passwordConfigured: bool


class WebDavTestResult(BaseModel):
    """POST /api/v1/backups/webdav/test (``message`` only when failed)."""

    status: Literal["ok", "failed"]
    message: str | None = None


class BackupJobSummary(BaseModel):
    """Backup job summary payload.

    Declares the keys a full/safety backup writes; ``extra="allow"``
    honestly passes through what restore jobs record
    (lumiRestored / freshrss / safetyBackupId) without inventing keys.
    """

    model_config = ConfigDict(extra="allow")

    filename: str | None = None
    target: str | None = None
    sizeBytes: int | None = None
    components: list[str] | None = None
    fileCount: int | None = None
    remotePath: str | None = None
    localPath: str | None = None


class BackupJob(BaseModel):
    """One backup/restore job (GET/POST /api/v1/backups, GET …/{job_id})."""

    id: str
    type: Literal["full", "safety", "restore"]
    status: Literal["queued", "running", "succeeded", "failed", "interrupted"]
    stage: str | None = None
    target: str | None = None
    createdAt: str
    startedAt: str | None = None
    finishedAt: str | None = None
    summary: BackupJobSummary | None = None
    safeError: str | None = None


class RemoteBackup(BaseModel):
    """One backup archive on WebDAV (flat name + size, no secret values)."""

    fileName: str
    sizeBytes: int


class RemoteBackupsResponse(BaseModel):
    """GET /api/v1/backups/remote."""

    backups: list[RemoteBackup]


class FreshrssDataBackupCapability(BaseModel):
    """FreshRSS component preflight — safe diagnostics only (no paths
    beyond the configured root, no credentials)."""

    available: bool
    reasonCode: str | None = None
    reason: str | None = None
    fileCount: int | None = None
    sqliteFileCount: int | None = None
    dbType: str | None = None


class BackupCapabilities(BaseModel):
    """GET /api/v1/backups/capabilities — what a full backup can honestly
    include right now, shown to the user BEFORE they click."""

    fullBackupReady: bool
    includes: list[str]
    lumiDatabaseAvailable: bool
    freshrssData: FreshrssDataBackupCapability


class TranslationSegmentState(BaseModel):
    """Per-block translation state (lookup = cache only; generate explicit)."""

    index: int
    status: Literal["success", "failed", "not_generated"]
    translatedText: str | None = None
    failureType: str | None = None
    cached: bool = False


class TranslationSegmentsView(BaseModel):
    """POST …/translation/segments/lookup | /generate."""

    engine: str
    targetLanguage: str
    segments: list[TranslationSegmentState] = []


class RestorePreviewFile(BaseModel):
    """One declared archive member (checksum declared by the manifest)."""

    model_config = ConfigDict(extra="allow")

    path: str
    size: int
    sha256: str


class RestorePreview(BaseModel):
    """POST /api/v1/restore/preview (validate + session id, no writes)."""

    restoreSessionId: str
    fileName: str | None = None
    createdAt: str | None = None
    lumiVersion: str | None = None
    lumiDbSchemaVersion: int
    currentDbSchemaVersion: int
    compatible: bool
    components: list[str] = []
    files: list[RestorePreviewFile] = []
    excludedSecrets: list[str] = []
    secretConfigured: bool


class RestoreHealth(BaseModel):
    """Post-restore storage health."""

    sqlite: Literal["healthy", "unavailable"]


class RestoreResult(BaseModel):
    """POST /api/v1/restore (destructive, explicitly confirmed)."""

    lumiRestored: bool
    freshrss: Literal["not_included", "offline_restore_required"]
    safetyBackupId: str | None = None
    freshrssStagedAt: str | None = None
    health: RestoreHealth


# ---------------------------------------------------------------------------
# Operations status (0018)
# ---------------------------------------------------------------------------


class OperationsLumiStatus(BaseModel):
    """Core storage status (degraded when sqlite is unavailable)."""

    status: str
    version: str


class OperationsSqliteStatus(BaseModel):
    """SQLite entry: compact healthy shape or full status entry (superset)."""

    status: str
    schemaVersion: int | None = None
    latencyMs: int | None = None
    lastCheckedAt: str | None = None
    error: ComponentError | None = None


class OperationsComponentStatus(BaseModel):
    """One probed upstream (FreshRSS / RSSHub) plus its configured flag."""

    status: str
    configured: bool
    latencyMs: int | None = None
    lastCheckedAt: str | None = None
    error: ComponentError | None = None


class OperationsRssHubStatus(OperationsComponentStatus):
    """RSSHub entry plus the pending config-change counters."""

    restartRequired: bool
    pendingConfigCount: int


class OperationsBackupStatus(BaseModel):
    """Backup capability summary for the operations view."""

    webdavConfigured: bool
    lastBackup: BackupJob | None = None


class OperationsStatus(BaseModel):
    """GET /api/v1/operations/status (redacted, real probes, no metrics)."""

    lumi: OperationsLumiStatus
    sqlite: OperationsSqliteStatus
    freshrss: OperationsComponentStatus
    rsshub: OperationsRssHubStatus
    backup: OperationsBackupStatus


# ---------------------------------------------------------------------------
# RSSHub Control Center (0018)
# ---------------------------------------------------------------------------


class RssHubConfigItem(BaseModel):
    """One allow-listed RSSHub setting (secrets surface only ``configured``).

    ``value`` is present only for non-secret items and ``configured`` only
    for secret items (the route serializes with exclude_unset to match the
    historical wire format); ``options`` is null for non-enum items.
    """

    key: str
    label: str
    description: str
    group: str
    type: Literal["int", "bool", "string", "enum", "secret"]
    default: int | str | bool
    editable: bool
    secret: bool
    restartRequired: bool
    options: list[str] | None = None
    value: int | str | bool | None = None
    configured: bool | None = None


class RssHubConfigGroup(BaseModel):
    """Grouped config items for the Control Center UI."""

    id: str
    label: str
    items: list[RssHubConfigItem]


class RssHubConfigView(BaseModel):
    """GET/PATCH /api/v1/rsshub/config (secrets never echoed)."""

    schemaVersion: int
    configured: bool
    pendingCount: int
    pendingSecrets: bool
    groups: list[RssHubConfigGroup]


# ---------------------------------------------------------------------------
# Global search (0022) — derived FTS projection over FreshRSS entries
# ---------------------------------------------------------------------------


class EntryDocument(BaseModel):
    """Adapter-level harvest item: list fields + the plain-text body.

    Used ONLY to build the derived search projection (search_index.py);
    it never appears in an API response.
    """

    item_id: str
    entryRef: str
    feedUrl: str
    feedTitle: str
    title: str
    author: str | None = None
    url: str | None = None
    publishedAt: str
    read: bool
    starred: bool
    contentText: str


class EntryDocumentPage(BaseModel):
    """Adapter-level harvest page (search projection input only)."""

    documents: list[EntryDocument]
    upstreamContinuation: str | None


class SearchItem(BaseModel):
    """One search hit — list metadata plus a safe plain-text snippet.

    ``snippet`` is plain text extracted from the sanitized content text
    (never HTML); the web client renders it as text only.
    """

    entryRef: str
    title: str
    feedTitle: str
    feedUrl: str
    author: str | None = None
    url: str | None = None
    publishedAt: str
    read: bool
    starred: bool
    snippet: str
    matchedFields: list[str]


class SearchIndexInfo(BaseModel):
    """Honest state of the derived projection behind this response."""

    entryCount: int
    lastSyncedAt: str | None = None
    partial: bool = False


class SearchResponse(BaseModel):
    """Envelope for GET /api/v1/search (phase2 G6: + optional library
    leg — additive fields, wire-compatible with older clients)."""

    items: list[SearchItem]
    nextCursor: str | None
    hasMore: bool
    elapsedMs: int
    index: SearchIndexInfo
    library: list["LibrarySearchItem"] | None = None
    libraryError: str | None = None


class SearchRebuildResult(BaseModel):
    """Envelope for POST /api/v1/search/rebuild."""

    entryCount: int
    pages: int
    partial: bool
    elapsedMs: int


# ---------------------------------------------------------------------------
# Library domain (phase2 M1) — bookmarks + workspaces + unified resolve
# ---------------------------------------------------------------------------


class BookmarkCreate(BaseModel):
    """POST /api/v1/library/bookmarks — exactly one of url | rssItemRef."""

    model_config = {"extra": "forbid"}

    url: str | None = None
    rssItemRef: str | None = None
    title: str
    note: str = ""


class BookmarkUpdate(BaseModel):
    """PATCH /api/v1/library/bookmarks/{uuid} — both fields optional."""

    model_config = {"extra": "forbid"}

    title: str | None = None
    note: str | None = None


class Bookmark(BaseModel):
    """One bookmark in the library domain (never carries RSS bodies)."""

    ref: str
    itemType: str
    url: str | None = None
    rssItemRef: str | None = None
    title: str
    note: str
    createdAt: str


class BookmarkListResponse(BaseModel):
    """Envelope for GET /api/v1/library/bookmarks."""

    items: list[Bookmark]
    nextCursor: str | None


class BookmarkImportFailedItem(BaseModel):
    """One per-item import failure: index, reason, and the offending URL."""

    index: int
    url: str
    reason: str


class BookmarkImportResult(BaseModel):
    """Envelope for POST /api/v1/library/bookmarks/import."""

    imported: int
    skipped: int
    failed: list[BookmarkImportFailedItem]


class WorkspaceCreate(BaseModel):
    """POST /api/v1/workspaces."""

    model_config = {"extra": "forbid"}

    name: str


class WorkspaceRename(BaseModel):
    """PATCH /api/v1/workspaces/{id}."""

    model_config = {"extra": "forbid"}

    name: str


class Workspace(BaseModel):
    """One workspace summary (read-later reports reserved=true)."""

    id: str
    name: str
    position: int
    itemCount: int
    reserved: bool


class WorkspaceListResponse(BaseModel):
    """Envelope for GET /api/v1/workspaces."""

    items: list[Workspace]


class WorkspaceItemAddRequest(BaseModel):
    """POST /api/v1/workspaces/{id}/items — one typed ItemRef."""

    model_config = {"extra": "forbid"}

    itemRef: str


class WorkspaceItem(BaseModel):
    """One workspace member (ref + ordering; content resolves separately)."""

    itemRef: str
    position: int
    addedAt: str


class WorkspaceItemsResponse(BaseModel):
    """Envelope for GET /api/v1/workspaces/{id}/items."""

    items: list[WorkspaceItem]


class WorkspaceReorderRequest(BaseModel):
    """PATCH /api/v1/workspaces/{id}/items — refs in their new order."""

    model_config = {"extra": "forbid"}

    itemRefs: list[str]


class ResolvedItem(BaseModel):
    """Unified ViewModel for UnifiedContentCard (report 12 §3)."""

    ref: str
    domain: str
    kind: str
    title: str
    source: str
    datetime: str | None = None
    excerpt: str | None = None
    url: str | None = None
    stale: bool = False
    payload: dict[str, object] = {}


class WorkspaceItemsResolvedResponse(BaseModel):
    """Envelope for GET /api/v1/workspaces/{id}/contents (resolved views)."""

    items: list[ResolvedItem]


class ResolveRequest(BaseModel):
    """POST /api/v1/resolve — resolve one or more ItemRefs."""

    model_config = {"extra": "forbid"}

    refs: list[str]


# ---------------------------------------------------------------------------
# Library domain (phase2 M2) — web clips + offline snapshots
# ---------------------------------------------------------------------------


class ClipFetchRequest(BaseModel):
    """POST /api/v1/library/clips/fetch — server-side bounded fetch."""

    model_config = {"extra": "forbid"}

    url: str


class ClipFetchResult(BaseModel):
    """Raw fetched page handed to the browser extractor."""

    url: str
    finalUrl: str
    html: str


class ClipCreate(BaseModel):
    """POST /api/v1/library/clips — extracted content from the client."""

    model_config = {"extra": "forbid"}

    url: str
    title: str
    byline: str | None = None
    contentHtml: str
    contentText: str
    fetchedAt: str | None = None


class Clip(BaseModel):
    """One clip in the library domain."""

    ref: str
    url: str
    title: str
    byline: str | None = None
    fetchedAt: str
    createdAt: str


class ClipDetail(Clip):
    """Clip with its (sanitized-at-origin) content."""

    contentHtml: str
    contentText: str


class ClipListResponse(BaseModel):
    """Envelope for GET /api/v1/library/clips."""

    items: list[Clip]
    nextCursor: str | None


class SnapshotCreate(BaseModel):
    """POST /api/v1/library/snapshots."""

    model_config = {"extra": "forbid"}

    url: str


class SnapshotView(BaseModel):
    """One stored snapshot asset."""

    uuid: str
    itemRef: str
    url: str
    bytes: int
    sha256: str
    deduplicated: bool = False
    createdAt: str


class SnapshotUsage(BaseModel):
    """Honest quota accounting for saved snapshots."""

    count: int
    bytes: int
    quotaBytes: int


# ---------------------------------------------------------------------------
# Library domain (phase2 M3) — API sources v1
# ---------------------------------------------------------------------------


class ApiSourceCreate(BaseModel):
    """POST /api/v1/api-sources."""

    model_config = {"extra": "forbid"}

    name: str
    endpoint: str
    itemsExpr: str
    fieldMap: dict[str, str]
    subscribe: bool = True


class ApiSourceUpdate(BaseModel):
    """PATCH /api/v1/api-sources/{uuid} — all fields optional."""

    model_config = {"extra": "forbid"}

    name: str | None = None
    endpoint: str | None = None
    itemsExpr: str | None = None
    fieldMap: dict[str, str] | None = None
    enabled: bool | None = None


class ApiSource(BaseModel):
    """One API source config (secret/atomPath only on create)."""

    uuid: str
    name: str
    endpoint: str
    itemsExpr: str
    fieldMap: dict[str, str]
    enabled: bool
    lastStatus: str | None = None
    lastSuccessAt: str | None = None
    lastError: str | None = None
    createdAt: str
    secret: str | None = None
    atomPath: str | None = None
    subscribeError: str | None = None


class ApiSourceListResponse(BaseModel):
    """Envelope for GET /api/v1/api-sources."""

    items: list[ApiSource]


class ApiSourcePreviewRequest(BaseModel):
    """POST /api/v1/api-sources/preview — nothing is saved."""

    model_config = {"extra": "forbid"}

    endpoint: str
    itemsExpr: str
    fieldMap: dict[str, str]


class ApiSourcePreviewResult(BaseModel):
    """Bounded preview (≤5 mapped items)."""

    items: list[dict[str, object]]
    totalAvailable: int


# ---------------------------------------------------------------------------
# Library domain (phase2 G5) — mail bridge + digest
# ---------------------------------------------------------------------------


class MailBridgeList(BaseModel):
    """One bridge list (secret never echoed after creation)."""

    uuid: str
    name: str
    createdAt: str


class MailBridgeListCreated(MailBridgeList):
    """Creation response — the only time the bearer secret is visible."""

    secret: str


class MailBridgeListCreate(BaseModel):
    """POST /api/v1/mail/bridge-lists."""

    model_config = {"extra": "forbid"}

    name: str


class MailBridgeListResponse(BaseModel):
    """Envelope for GET /api/v1/mail/bridge-lists."""

    items: list[MailBridgeList]


class MailIngestResult(BaseModel):
    """Honest ingest/send report."""

    status: str
    messageId: str = ""
    subject: str | None = None
    attachments: int = 0


class DigestSettings(BaseModel):
    """Outbound digest configuration (password never returned)."""

    enabled: bool
    hour: int
    source: str
    limitCount: int
    smtpHost: str
    smtpPort: int
    smtpUser: str
    fromAddr: str
    toAddr: str
    lastSentAt: str | None = None
    lastError: str | None = None
    passwordConfigured: bool = False


class DigestSettingsUpdate(BaseModel):
    """PUT /api/v1/digest/settings — partial; password write-only."""

    model_config = {"extra": "forbid"}

    enabled: bool | None = None
    hour: int | None = None
    source: str | None = None
    limitCount: int | None = None
    smtpHost: str | None = None
    smtpPort: int | None = None
    smtpUser: str | None = None
    fromAddr: str | None = None
    toAddr: str | None = None
    smtpPassword: str | None = None


class DigestSendNowRequest(BaseModel):
    """POST /api/v1/digest/send-now — explicit item selection."""

    model_config = {"extra": "forbid"}

    entryRefs: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Library domain (phase2 G6) — Obsidian projection + unified views
# ---------------------------------------------------------------------------


class ObsidianNoteSetting(BaseModel):
    """PUT /api/v1/obsidian/settings."""

    model_config = {"extra": "forbid"}

    vaultPath: str


class ObsidianSettings(BaseModel):
    """Vault root (canonicalized) + honest note count."""

    vaultPath: str
    noteCount: int


class ObsidianStatus(BaseModel):
    """Honest scanner status (error keeps the old index visible)."""

    vaultPath: str
    lastScanAt: str | None = None
    lastError: str | None = None
    noteCount: int = 0


class ObsidianRescanResult(BaseModel):
    """Bounded scan report with rename detection."""

    added: int
    changed: int
    removed: int
    renames: int
    unchanged: int
    skipped: int
    elapsedMs: int
    vaultPath: str = ""


class NoteView(BaseModel):
    """One projected note; contentHtml only on detail (client sanitizes)."""

    ref: str
    relPath: str
    title: str
    tags: list[str] = []
    indexedAt: str
    wikilinks: list[str] | None = None
    contentHtml: str | None = None


class NoteListResponse(BaseModel):
    """Envelope for GET /api/v1/obsidian/notes."""

    items: list[NoteView]


class LibrarySearchItem(BaseModel):
    """Library leg of unified search (same shape philosophy as SearchItem)."""

    ref: str
    kind: str
    title: str
    url: str | None = None
    snippet: str = ""
    updatedAt: str


class FavoritesResponse(BaseModel):
    """Federated favorites: rss star + library favorite, merged for
    display only — each stays owned by its own domain."""

    rss: list[SearchItem]
    library: list[LibrarySearchItem]
    libraryError: str | None = None


class LibraryFavoriteRequest(BaseModel):
    """POST/DELETE /api/v1/favorites/library — one ItemRef."""

    model_config = {"extra": "forbid"}

    ref: str


class SnapshotListResponse(BaseModel):
    """Envelope for GET /api/v1/library/snapshots."""

    items: list[SnapshotView]
    usage: SnapshotUsage


# ---------------------------------------------------------------------------
# Library domain (phase2 G7/G8) — RAG + Agent workbench
# ---------------------------------------------------------------------------


class AgentThread(BaseModel):
    """One conversation thread."""

    id: str
    title: str
    createdAt: str


class AgentThreadListResponse(BaseModel):
    """Envelope for GET /api/v1/agent/threads."""

    items: list[AgentThread]


class AgentMessageCreate(BaseModel):
    """POST /api/v1/agent/threads/{id}/messages."""

    model_config = {"extra": "forbid"}

    text: str


class AgentApprovalDecision(BaseModel):
    """POST /api/v1/agent/threads/{id}/approvals."""

    model_config = {"extra": "forbid"}

    approvalId: str
    decision: str


class RagSearchItem(BaseModel):
    """One fused retrieval hit (ref resolves to real content)."""

    ref: str
    kind: str
    text: str
    score: float


class RagSearchResponse(BaseModel):
    """Envelope for GET /api/v1/rag/search (honest degradation flags)."""

    items: list[RagSearchItem]
    semanticUsed: bool
    semanticError: str | None = None


class RagRebuildResult(BaseModel):
    """Bounded rebuild report."""

    chunks: int
    elapsedMs: int


class RagEnableResult(BaseModel):
    """Explicit model-enable acknowledgement."""

    enabled: bool
