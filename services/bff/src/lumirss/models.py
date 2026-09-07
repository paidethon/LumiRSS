"""LumiRSS BFF API response models.

One definition point for the API response shapes: FastAPI serializes these
into the OpenAPI schema, making this module the single source of truth that
the web client's ``src/api/types.ts`` mirrors 1:1. Field names are
camelCase directly on the models (no alias generators) to match the wire
format. The entry-domain models (0003/0004) are built directly by the
adapter and returned by the routes, so there is no second mapping layer.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

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
    server-durable values.
    """

    stored: bool


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
