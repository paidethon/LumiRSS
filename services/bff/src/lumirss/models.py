"""LumiRSS BFF API response models.

One definition point for the API response shapes: FastAPI serializes these
into the OpenAPI schema, making this module the single source of truth that
the web client's ``src/api/types.ts`` mirrors 1:1. Field names are
camelCase directly on the models (no alias generators) to match the wire
format. The entry-domain models (0003/0004) are built directly by the
adapter and returned by the routes, so there is no second mapping layer.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lumirss.app_settings import PortableSettings

# ---------------------------------------------------------------------------
# Entries (0003/0004) — list, detail
# ---------------------------------------------------------------------------


class EntryHiddenByRule(BaseModel):
    """F045：命中并屏蔽本条的服务端规则（include_hidden 时附带）。"""

    ruleId: str
    reason: str


class EntryListItem(BaseModel):
    """One article in the entry list — never contains the body.

    2026-09 移动端专项 P2/F02/F03 enrich（列表级元数据，非正文）：
    - feedUrl：来源真实订阅 URL（标题→URL 映射解析；解析不到保持
      None，前端该来源不可点击，诚实降级）；
    - snippet：列表摘要（html_to_text 前 160 字符，纯文本）；
    - coverUrl：封面图（正文首个 http(s) <img src>；仅元数据，是否
      加载由前端图片模式控制）。
    """

    entryRef: str
    title: str
    feedTitle: str
    author: str | None = None
    url: str | None = None
    publishedAt: str | None = None
    read: bool
    starred: bool
    feedUrl: str | None = None
    snippet: str | None = None
    # F045：includeHidden=true 时附带的服务端屏蔽标记（其余情况为 None）。
    hiddenByRule: EntryHiddenByRule | None = None
    coverUrl: str | None = None
    # N034：发布时间可信度（异常代码逗号连接，如 "future" /
    # "missing,no_timezone"；无异常或投影未覆盖 → None，不冒充正常）。
    timeCredibility: str | None = None


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
    # F045：本页被屏蔽未返回的条数（include_hidden=false 时如实上报）。
    filteredCount: int | None = None


class FeedFilterRule(BaseModel):
    """F045：一条服务端屏蔽规则。"""

    id: str
    feedUrl: str
    field: str
    op: str
    value: str
    enabled: bool
    createdAt: str


class FeedFilterRuleList(BaseModel):
    items: list[FeedFilterRule]


class FeedFilterRuleCreate(BaseModel):
    """POST /api/v1/feed-filter-rules body."""

    model_config = {"extra": "forbid"}

    feedUrl: str
    field: str
    op: str
    value: str
    enabled: bool = True


class FeedFilterRuleTrial(BaseModel):
    """POST /api/v1/feed-filter-rules/trial —— 试跑（不写库）。"""

    model_config = {"extra": "forbid"}

    feedUrl: str | None = None
    sampleTitle: str = Field(min_length=1, max_length=2000)
    sampleAuthor: str | None = None


class FeedFilterRuleTrialResult(BaseModel):
    matched: bool
    ruleId: str | None = None
    reason: str | None = None


class EntryEnclosure(BaseModel):
    """F011：一个媒体附件（原样来自 FreshRSS 响应，仅取 href/type）。"""

    href: str
    type: str | None = None


class ContentVariantOption(BaseModel):
    """N032：一个可选的正文版本（经同一净化边界渲染）。

    kind: "current"（上游当前）| "last_known_full"（保留的上一个更长
    版本；仅在该版本仍被保留时出现——有界 side table，keep_latest=1）。
    contentHtml 仍是不可信上游 HTML：Web 端必须经同一 DOMPurify 边界
    渲染，BFF 不做净化（与正文同一安全模型）。
    """

    kind: str
    label: str
    capturedAt: str | None = None
    contentHtml: str | None = None
    lengthChars: int = 0


class ContentVariantsBlock(BaseModel):
    """N032：正文明显变短时的版本选择块（未触发 → None）。

    triggered 条件（服务端判定）：当前 contentHtml 长度 < 投影行记录的
    历史最大内容长度（content_max_len）的 40%。真实阈值事实，不猜测
    内容是否「完整」。
    """

    triggered: bool
    currentLength: int
    maxLength: int
    variants: list[ContentVariantOption] = Field(default_factory=list)


class EntryRevision(BaseModel):
    """N031：一条有界的文章修订记录（元数据，绝不含全文副本）。

    summary 为服务端计算的结构差异摘要：basis 说明比较基准
    （retained_variant = 与保留的长版本比较；hash_only = 仅知哈希变化，
    无保留版本可比，不臆造差异）；excerpts ≤200 字符每侧。
    """

    id: int
    capturedAt: str
    titleChanged: bool
    prevTitle: str | None = None
    newTitle: str | None = None
    summary: dict = Field(default_factory=dict)
    prevHash: str
    newHash: str


class EntryRevisionsResponse(BaseModel):
    """GET /api/v1/entries/{entry_ref}/revisions。"""

    entryRef: str
    revisions: list[EntryRevision]


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
    # F30 溯源：FreshRSS 首次收录时刻（发布时间缺失时也不冒充发布时间）。
    crawledAt: str | None = None
    read: bool
    starred: bool
    contentText: str
    contentHtml: str | None = None
    # P2：来源真实订阅 URL（解析不到为 None；阅读页来源点击用）。
    feedUrl: str | None = None
    # F048：per-source 提取策略与结果（web 策略失败回退 RSS 时诚实标记）。
    extractPolicy: str | None = None
    extractionFailed: bool | None = None
    # F011：原样透传的 enclosure[]（audio/video 等媒体附件；greader
    # items 响应中的 enclosure 数组，形状异常的元素保守丢弃）。
    enclosure: list[EntryEnclosure] = Field(default_factory=list)
    # N032：正文明显变短时的版本选择块（未触发为 None；字段存在于
    # 契约，response_model_exclude_none=False 下始终出现）。
    contentVariants: ContentVariantsBlock | None = None



# ---------------------------------------------------------------------------
# AI article artifacts (0015/0016) — summary, translation, conversation
# ---------------------------------------------------------------------------


class TitleTranslationView(BaseModel):
    """F23：单条标题译文（原题保留，UI 叠加展示）。"""

    originalTitle: str
    translatedTitle: str
    cached: bool = False
    language: str = ""
    model: str = ""


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


class EncodingInspection(BaseModel):
    """N033：有界响应体的编码检查（声明 / 检测 / 乱码风险 + 掩码样本）。

    - declared/declaredMethod：文档声称的编码与判定来源
      （bom | xml_declaration | meta_charset | content_type_header | none）；
    - detected/detectedMethod：轻启发式结果（无 chardet 依赖）：
      bom → xml/meta 声明经解码验证 → utf-8 严格校验 → unknown；
    - mojibakeRisk：声明与检测不一致，或字节流不是合法 UTF-8；
    - sample：首个无效字节附近 ≤200 字符的解码样本（无效字节以
      U+FFFD 掩码）；无无效字节 → None。
    """

    declared: str | None = None
    declaredMethod: str | None = None
    detected: str | None = None
    detectedMethod: str | None = None
    utf8Valid: bool = True
    mojibakeRisk: bool = False
    sample: str | None = None
    bodyBytes: int = 0


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
    # N033：编码检查（直连预览路径附带；rsshub/preview 无抓取 → None）。
    encodingInspection: EncodingInspection | None = None


class FeedPreviewReparseRequest(BaseModel):
    """POST /api/v1/feed-preview/reparse body (N033)."""

    model_config = {"extra": "forbid"}

    feedUrl: str = Field(min_length=1)
    encoding: Literal["utf-8", "declared", "detected"] | None = None
    save: bool = False


class FeedPreviewEncodingChoice(BaseModel):
    """reparse：一种编码选择下文档的真实渲染（title + 掩码样本）。"""

    encoding: str
    resolvedCodec: str | None = None
    title: str | None = None
    sample: str | None = None
    mojibakeRisk: bool = False


class FeedPreviewReparseResponse(BaseModel):
    """reparse 响应：三种选择的渲染对比 + （可选）保存的覆盖。"""

    feedUrl: str
    inspection: EncodingInspection
    choices: list[FeedPreviewEncodingChoice]
    applied: str | None = None
    savedOverride: str | None = None


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


class RssHubFavoriteItem(BaseModel):
    """One N021 route favorite (params carry masked sensitive values only)."""

    routeKey: str
    templateId: str
    label: str
    params: dict[str, str]
    createdAt: str


class RssHubRecentItem(BaseModel):
    """One N021 recently used route (params carry masked sensitive values)."""

    routeKey: str
    templateId: str
    params: dict[str, str]
    lastUsedAt: str
    lastSuccessAt: str | None = None


class RssHubCacheInfo(BaseModel):
    """N027: preview freshness (fresh=True when computed for this request)."""

    ageS: float
    fresh: bool


class RssHubPreviewResult(FeedPreviewResult):
    """POST /api/v1/rsshub/preview — adds the server-derived routeKey.

    N021/N025: the key (template id + masked params signature) is built
    server-side; clients use it for favorites/recents/history/refresh
    and never assemble it themselves. N027 adds cache freshness."""

    routeKey: str
    cache: RssHubCacheInfo


class RssHubRefreshResult(BaseModel):
    """POST /api/v1/rsshub/refresh — one forced re-fetch of THAT route."""

    routeKey: str
    title: str
    entryCount: int | None = None
    ranAt: str
    durationMs: int
    cache: RssHubCacheInfo


class RssHubRouteRun(BaseModel):
    """One N025 route health timeline row (no secrets — route keys are
    masked server-side before storage)."""

    id: int
    routeKey: str
    ranAt: str
    status: Literal["ok", "failed"]
    durationMs: int
    entryCount: int | None = None
    failureClass: str | None = None


class RssHubRouteRuns(BaseModel):
    """GET /api/v1/rsshub/routes/history — bounded run list, newest first."""

    items: list[RssHubRouteRun]


# ---------------------------------------------------------------------------
# OPML import (0013 Gate 4)
# ---------------------------------------------------------------------------


class OpmlImportPreviewCategory(BaseModel):
    """Per-category feed count in the import preview."""

    label: str
    feedCount: int


class OpmlImportPreviewItem(BaseModel):
    """F002：逐项预览行（status: new|duplicate|invalid|category_conflict）。"""

    index: int
    title: str = ""
    xmlUrl: str
    category: str | None = None
    status: str
    note: str | None = None


class OpmlImportPreview(BaseModel):
    """POST /api/v1/opml/import/preview (strictly non-mutating)."""

    totalFeeds: int
    newFeeds: int
    duplicates: int
    invalidEntries: int
    categories: list[OpmlImportPreviewCategory]
    items: list[OpmlImportPreviewItem] = []


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


class OpmlImportSkipped(BaseModel):
    """F002：一个未参与导入的条目（诚实汇报跳过原因）。"""

    feedUrl: str
    title: str
    reason: str  # not_selected | invalid


class OpmlImportResult(BaseModel):
    """POST /api/v1/opml/import (merge-only: duplicates are never touched)."""

    added: list[OpmlImportAdded]
    duplicates: list[OpmlImportDuplicate]
    failed: list[OpmlImportFailed]
    skipped: list[OpmlImportSkipped] = []
    categoriesCreated: list[str]


# ---------------------------------------------------------------------------
# F004 重复订阅检查器 / F005 来源备注 / F006 批量分类迁移
# ---------------------------------------------------------------------------


class DuplicateSuspectMember(BaseModel):
    """F004：重复候选组内的一个订阅成员。"""

    subscriptionRef: str
    title: str
    feedUrl: str
    categoryLabel: str | None = None


class DuplicateSuspectGroup(BaseModel):
    """F004：一组重复候选（成员 ≥2；key 为受控规范化 URL）。"""

    key: str
    members: list[DuplicateSuspectMember] = []
    differences: list[str] = []


class DuplicateSuspectsResponse(BaseModel):
    groups: list[DuplicateSuspectGroup] = []
    checked: int = 0


class SourceNotesView(BaseModel):
    """F005：一个订阅的备注/理由/维护记录（原文存储，渲染转义）。"""

    subscriptionRef: str
    note: str | None = None
    reason: str | None = None
    maintenanceLog: str | None = None
    updatedAt: str | None = None


class SourceNotesList(BaseModel):
    items: list[SourceNotesView] = []


class SourceNotesUpdate(BaseModel):
    """PATCH /api/v1/subscriptions/{ref}/notes — sentinel：缺席=不改，
    null=清空，字符串=覆盖原文（有界截断）。"""

    note: str | None = None
    reason: str | None = None
    maintenanceLog: str | None = None


class BatchMoveRequest(BaseModel):
    """POST /api/v1/subscriptions/batch-move — 全部 refs 逐项执行。"""

    refs: list[str] = Field(min_length=1)
    targetCategoryId: str = Field(min_length=1)


class BatchMoveItem(BaseModel):
    """F006：单条迁移结果（失败项带稳定错误码，不中断整批）。"""

    ref: str
    ok: bool
    error: str | None = None


class BatchMoveResult(BaseModel):
    items: list[BatchMoveItem] = []
    moved: int = 0


# ---------------------------------------------------------------------------
# Misc: FreshRSS UI escape hatch, version provenance
# ---------------------------------------------------------------------------


class FreshRssUiInfo(BaseModel):
    """GET /api/v1/freshrss-ui (null url = not configured, UI hides it)."""

    url: str | None = None


class FreshRssNativeUrl(BaseModel):
    """GET /api/v1/freshrss/native-url — 委托入口数据（P09）。

    响应**恰好**两个字段：浏览器可达的 FreshRSS 站点根（origin，来自
    绑定的 public_url）+ 该账户的 FreshRSS 用户名（原生界面登录可识别）。
    API 密码 / greader token 等任何凭据永不进入此响应——模型没有承载
    它们的字段，契约上就不可能泄露。"""

    origin: str
    username: str


class TrashItem(BaseModel):
    """F019：回收站条目（kind: bookmark | clip）。30 天过期由既有清理
    机制承担；当前若无调度器则仅在文档标注，不新建调度器。"""

    uuid: str
    kind: str
    title: str
    url: str | None = None
    deletedAt: str


class TrashList(BaseModel):
    items: list[TrashItem] = []


class NoteImportFile(BaseModel):
    """F020：一个待入库的 Markdown 文件。"""

    name: str = Field(min_length=1, max_length=500)
    content: str


class NoteImportRequest(BaseModel):
    """POST /api/v1/library/notes/import — 逐文件校验、逐项汇报。"""

    files: list[NoteImportFile] = Field(min_length=1, max_length=50)
    workspaceId: str | None = None


class NoteImportResultItem(BaseModel):
    name: str
    ok: bool
    uuid: str | None = None
    reason: str | None = None


class NoteImportResult(BaseModel):
    items: list[NoteImportResultItem] = []
    imported: int = 0
    skipped: int = 0


class LumiNoteView(BaseModel):
    """F020：笔记列表项（摘要首行，≤160 字）。"""

    uuid: str
    title: str
    workspaceId: str | None = None
    excerpt: str
    createdAt: str
    updatedAt: str


class LumiNoteList(BaseModel):
    items: list[LumiNoteView] = []


# ---------------------------------------------------------------------------
# Session authentication (LUMIRSS_AUTH_MODE=session)
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """POST /api/v1/auth/login — username + password (multi-account);
    legacy single-user mode sends password only."""

    username: str | None = Field(default=None, min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    """POST /api/v1/auth/password — current + new password.

    ``totpCode`` is REQUIRED when the account has TOTP enabled (N007
    server-enforced second factor for sensitive operations); ignored
    otherwise."""

    currentPassword: str = Field(min_length=1, max_length=256)
    newPassword: str = Field(min_length=1, max_length=256)
    totpCode: str | None = Field(default=None, max_length=64)


class LoginChallenge(BaseModel):
    """POST /api/v1/auth/login response when the account has TOTP enabled
    (N007): the password was verified, but the session is minted only
    after ``POST /auth/totp/verify`` with this short-lived pending token
    (which is NOT a session and grants nothing on its own)."""

    totpRequired: Literal[True]
    pendingToken: str


class ActivationSourceResult(BaseModel):
    """One scheme initial-source subscription attempt (N001).

    ``ok=False`` is an honest per-URL failure record — activation itself
    is never blocked or rolled back by a source failure."""

    url: str
    ok: bool
    error: str | None = None


class AuthStatus(BaseModel):
    """Login / session-status payload; expiresAt is an ISO-8601 instant.

    mode tells the web app WHICH auth layer is active: "basic" = proxy
    Basic Auth (the app must not render its own login gate), "session" =
    BFF sessions (gate on ``authenticated``). userId/username/role carry
    the server-verified identity for the account menu — the client never
    declares who it is. initialSources is only present on the invite
    activation response (N001); every other surface omits it entirely."""

    authenticated: bool
    mode: Literal["basic", "session"] = "session"
    expiresAt: str | None = None
    userId: str | None = None
    username: str | None = None
    role: Literal["owner", "admin", "member"] | None = None
    initialSources: list[ActivationSourceResult] | None = None


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
    # F064：用量限制（window "" = 不限；maxCalls 0 = 不限）。
    quotaWindow: Literal["", "day", "month"] = ""
    quotaMaxCalls: int = 0


class AiProfile(BaseModel):
    """One AI profile (keys surface only as ``keyConfigured``)."""

    id: str
    label: str
    provider: Literal["openai_compatible", "gemini"]
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


class SegmentProtectedTerm(BaseModel):
    """N083：一个受保护术语在本段的保留结果（诚实报告，不臆造）。"""

    term: str
    protected: bool
    count: int = 0
    reason: str | None = None


class TranslationSegmentState(BaseModel):
    """Per-block translation state (lookup = cache only; generate explicit)."""

    index: int
    status: Literal["success", "failed", "not_generated"]
    translatedText: str | None = None
    failureType: str | None = None
    cached: bool = False
    # F062：手工修订（存在时 UI 优先展示；stale = 保存修订后源段已变化）。
    userRevision: str | None = None
    revisedAt: str | None = None
    revisionStale: bool = False
    # N086：用户标记「不翻译」的块（不参与生成；缓存译文照常展示）。
    noTranslate: bool = False
    # N083：受保护术语在本段的保留结果报告。
    protectedTerms: list[SegmentProtectedTerm] = []


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
    # N031/N032/N040：投影摄取需要原始 HTML（差异摘要 / 内容变体边界
    # 判定）与 FreshRSS 首次收录时刻。contentHtml 只在投影写入路径内部
    # 使用，绝不入库为全文（投影不保存正文副本），也不出现在 API 响应。
    contentHtml: str = ""
    crawledAt: str = ""


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
    # F072：正文命中偏移（前 ≤10 处；老客户端可选；仅标题命中 → 空表）
    matchPositions: list[dict[str, str | int]] | None = None


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
    # Library-leg keyset continuation (pool #10): the old fixed newest-50
    # slice re-listed itself on every RSS page and hid older hits.
    libraryNextCursor: str | None = None
    libraryHasMore: bool = False


class SearchRebuildResult(BaseModel):
    """Envelope for POST /api/v1/search/rebuild."""

    entryCount: int
    pages: int
    partial: bool
    elapsedMs: int


class SavedSearchView(BaseModel):
    """One saved search view (pool #09): query + filter intent, never a
    result snapshot — opening a view re-runs the search."""

    id: str
    name: str
    query: str
    view: str = "all"
    categoryKey: str = ""
    createdAt: str
    updatedAt: str
    # F035：固定视图 + 构建器完整意图（向后兼容：老视图无 filters）。
    pinned: bool = False
    pinOrder: int | None = None
    filters: dict[str, str | bool | None] | None = None
    # F061：私有 Atom 订阅是否已启用（布尔；token 本身绝不返回）。
    hasFeedToken: bool = False


class SavedSearchList(BaseModel):
    """GET /api/v1/search/views."""

    items: list[SavedSearchView]


class ViewFeedTokenResult(BaseModel):
    """F061：启用/轮换私有 Atom 订阅的响应。

    ``atomPath`` 是带 secret 的完整路径，仅在此响应中出现一次；
    之后只显示"已隐藏，可轮换"。"""

    atomPath: str
    hasFeedToken: bool = True


class SavedSearchCreate(BaseModel):
    """POST /api/v1/search/views."""

    model_config = {"extra": "forbid"}

    name: str
    query: str
    view: str = "all"
    categoryKey: str = ""
    # F035：构建器完整意图（可选；None = 只存 q 解析路径）。
    filters: dict[str, str | bool | None] | None = None


class SavedSearchRename(BaseModel):
    """PATCH /api/v1/search/views/{id}."""

    model_config = {"extra": "forbid"}

    name: str


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
    # F25：工作区说明（目标/范围/入口导航；空 = 无说明）
    description: str | None = None


class WorkspaceRename(BaseModel):
    """PATCH /api/v1/workspaces/{id}（description 缺省 = 不修改说明）。"""

    model_config = {"extra": "forbid"}

    name: str
    description: str | None = None


class Workspace(BaseModel):
    """One workspace summary (read-later reports reserved=true)."""

    id: str
    name: str
    position: int
    itemCount: int
    reserved: bool
    # F25：工作区说明（纯文本；空串 = 未设置）
    description: str = ""
    # F084：归档状态（默认导航隐藏；深链接仍可打开）
    archived: bool = False
    archivedAt: str | None = None
    # P15：条目域变更计数（add/remove/reorder/status +1）；重排序可带
    # expectedRevision 做乐观并发，不匹配 → 409。
    revision: int = 1


class WorkspaceListResponse(BaseModel):
    """Envelope for GET /api/v1/workspaces."""

    items: list[Workspace]


class WorkspaceItemAddRequest(BaseModel):
    """POST /api/v1/workspaces/{id}/items — one typed ItemRef.

    N101：``groupName`` 可选（null/缺省 = 未分组隐式前置组）。"""

    model_config = {"extra": "forbid"}

    itemRef: str
    groupName: str | None = None


class WorkspaceItem(BaseModel):
    """One workspace member (ref + ordering; content resolves separately).

    N101/N102：``groupName``（null = 未分组）与 ``pinned`` 为增量元数据，
    排序语义不变（position 升序）。"""

    itemRef: str
    position: int
    addedAt: str
    groupName: str | None = None
    pinned: bool = False


class WorkspaceItemsResponse(BaseModel):
    """Envelope for GET /api/v1/workspaces/{id}/items."""

    items: list[WorkspaceItem]


class WorkspaceGroup(BaseModel):
    """N101：一个分组（name=null = 未分组隐式前置组）；组内 position 序。"""

    name: str | None
    items: list[WorkspaceItem]


class WorkspaceGroupsResponse(BaseModel):
    """Envelope for GET/PUT /api/v1/workspaces/{id}/groups（N101/N102）.

    ``pinned`` 区在最前（N102：固定排所有组之前）；``groupOrder`` 是
    命名组的呈现顺序（未列入的组按名字典序追加在后）。"""

    workspaceId: str
    revision: int
    groupOrder: list[str]
    pinned: list[WorkspaceItem]
    groups: list[WorkspaceGroup]


class WorkspaceGroupOrderPut(BaseModel):
    """PUT /api/v1/workspaces/{id}/groups — 命名组呈现顺序。

    只重排既有组（名字必须是当前真实存在的组；不创建、不重命名）。"""

    model_config = {"extra": "forbid"}

    order: list[str]


class WorkspaceItemGroupMoveRequest(BaseModel):
    """PATCH /api/v1/workspaces/{id}/items/{ref}/group — 移动到分组。

    ``groupName=null`` = 移回未分组隐式前置组。"""

    model_config = {"extra": "forbid"}

    groupName: str | None = None


class WorkspaceItemPinRequest(BaseModel):
    """PUT /api/v1/workspaces/{id}/items/{ref}/pin — set 语义固定标记。"""

    model_config = {"extra": "forbid"}

    pinned: bool


class WorkspaceReorderRequest(BaseModel):
    """PATCH /api/v1/workspaces/{id}/items — refs in their new order.

    P15：``expectedRevision`` 可选（If-Match 式乐观并发）；缺省 = 旧
    行为（不校验），保证既有调用方零改动。"""

    model_config = {"extra": "forbid"}

    itemRefs: list[str]
    expectedRevision: int | None = None


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
    # Why a stale card is stale: unsupported | not_found | timeout |
    # error (pool #13) — the UI maps these to distinct next actions.
    staleReason: str | None = None
    payload: dict[str, object] = {}


class WorkspaceItemsResolvedResponse(BaseModel):
    """Envelope for GET /api/v1/workspaces/{id}/contents (resolved views)."""

    items: list[ResolvedItem]


class WorkspaceResumePutRequest(BaseModel):
    """PUT /api/v1/workspaces/{id}/resume — one member ItemRef."""

    model_config = {"extra": "forbid"}

    itemRef: str


class WorkspaceResumePointer(BaseModel):
    """「上次看到哪」指针（P15）：ref + 保存时的位置快照。"""

    itemRef: str
    positionAtSave: int | None = None
    updatedAt: str


class WorkspaceResumeResponse(BaseModel):
    """Envelope for GET/PUT /api/v1/workspaces/{id}/resume（无指针时
    pointer=null，GET 永远 200——「没有指针」是正常态而非错误）。"""

    workspaceId: str
    pointer: WorkspaceResumePointer | None = None


class WorkspaceSnapshotCreate(BaseModel):
    """POST /workspaces/{id}/snapshots — 命名捕获当前标签页状态。"""

    model_config = {"extra": "forbid"}

    name: str


class WorkspaceSnapshot(BaseModel):
    """N105：一个命名会话快照（元数据视图；payload 留在服务端）。

    ``itemCount`` 是捕获时刻的成员数（从 payload 派生）。"""

    id: str
    workspaceId: str
    name: str
    createdAt: str
    itemCount: int


class WorkspaceSnapshotList(BaseModel):
    """Envelope for GET /api/v1/workspaces/{id}/snapshots（新→旧）。"""

    items: list[WorkspaceSnapshot]


class WorkspaceSnapshotRestoreRequest(BaseModel):
    """POST /workspaces/{id}/snapshots/{sid}/restore（N105）.

    - ``reorder``：只重排/重分组/重固定既有成员，快照外成员保留；
    - ``replace``：移除快照外成员再应用（固定条目受 N102 保护——拒绝
      丢固定条目除非 ``force=true``）；
    - 快照里已消失的 ref 诚实上报，绝不复活。
    """

    model_config = {"extra": "forbid"}

    mode: str
    force: bool = False


class WorkspaceSnapshotRestoreResult(BaseModel):
    """恢复 diff 摘要：restored=应用数；missing=快照中已消失的 ref；
    kept=快照外保留数（replace 恒 0）；removed=replace 移除的 ref。"""

    restored: int
    missing: list[str]
    kept: int
    removed: list[str]
    revision: int


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
    pagination: dict[str, object] | None = None
    subscribe: bool = True


class ApiSourceUpdate(BaseModel):
    """PATCH /api/v1/api-sources/{uuid} — all fields optional."""

    model_config = {"extra": "forbid"}

    name: str | None = None
    endpoint: str | None = None
    itemsExpr: str | None = None
    fieldMap: dict[str, str] | None = None
    pagination: dict[str, object] | None = None
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
    # F042: pagination sampling config; F043: structure baseline state.
    pagination: dict[str, object] | None = None
    confirmedSchema: bool = False
    schemaDrift: dict[str, list[str]] | None = None


class ApiSourceListResponse(BaseModel):
    """Envelope for GET /api/v1/api-sources."""

    items: list[ApiSource]


class ApiSourcePreviewRequest(BaseModel):
    """POST /api/v1/api-sources/preview — nothing is saved."""

    model_config = {"extra": "forbid"}

    endpoint: str
    itemsExpr: str
    fieldMap: dict[str, str]
    pagination: dict[str, object] | None = None
    dryRunPagination: bool = False


class ApiSourcePaginationDryRun(BaseModel):
    """F042: bounded pagination walk against the sample (no writes)."""

    pages: list[dict[str, object]]
    stopReason: str


class ApiSourcePreviewResult(BaseModel):
    """Bounded preview (≤5 mapped items + F041 Atom-form preview)."""

    items: list[dict[str, object]]
    totalAvailable: int
    atomPreview: list[dict[str, object]] = []
    paginationDryRun: ApiSourcePaginationDryRun | None = None


class ApiSourceConfirmSchemaResult(BaseModel):
    """F043: baseline confirmation outcome."""

    confirmed: bool
    sampledItems: int


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
    # IANA 名称（'' = 服务器本地，历史语义）；调度与 nextSend 按此解释。
    timezone: str = ""
    # F008：enabled 时给出下次发送时间（配置时区墙钟；'' = 服务器本地）
    nextSendAt: str | None = None
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
    timezone: str | None = None
    smtpPassword: str | None = None


class DigestPreview(BaseModel):
    """GET /api/v1/digest/preview — 无副作用预览（不发送、不记录错误）."""

    subject: str
    text: str
    html: str
    itemCount: int
    enabled: bool
    hour: int
    timezone: str
    nextSendAt: str | None = None
    note: str | None = None


class GptDigestSettings(BaseModel):
    """GPT 日报配置（订阅 token 不在此响应中，见 /api/v1/gpt-digest/feed）。"""

    enabled: bool
    hour: int
    timezone: str = ""
    windowHours: int = 24
    limitCount: int = 12
    perSourceCap: int = 2
    lastIssueKey: str | None = None
    lastError: str | None = None


class GptDigestSettingsUpdate(BaseModel):
    """PUT /api/v1/gpt-digest/settings — partial；非法值回退现值。"""

    enabled: bool | None = None
    hour: int | None = None
    timezone: str | None = None
    windowHours: int | None = None
    limitCount: int | None = None
    perSourceCap: int | None = None


class GptDigestItem(BaseModel):
    summary: str
    sourceIds: list[str] = []
    uncertainty: str | None = None


class GptDigestSection(BaseModel):
    heading: str
    items: list[GptDigestItem] = []


class GptDigestRef(BaseModel):
    title: str
    url: str = ""
    feedTitle: str = ""
    publishedAt: str = ""


class GptDigestIssue(BaseModel):
    """一期日报；列表与详情共用（列表 limit 小、正文不重）。"""

    issueKey: str
    status: str
    title: str
    sections: list[GptDigestSection] = []
    refs: dict[str, GptDigestRef] = {}
    model: str = ""
    createdAt: str = ""
    publishedAt: str = ""
    updatedAt: str = ""


class GptDigestIssueList(BaseModel):
    items: list[GptDigestIssue] = []


class GptDigestIssueRevise(BaseModel):
    """PUT /api/v1/gpt-digest/configs/{id}/issues/{key} — F08 人工修订。

    sections 结构沿用生成时 schema；sourceIds 只能引用既有引用集。"""

    title: str
    sections: list[dict[str, object]]


class GptDigestFeedInfo(BaseModel):
    """订阅路径（含 token）。token 即凭据：只在会话认证下返回。"""

    atomPath: str


class GptDigestPreviewItem(BaseModel):
    """F06：预览中的一条入选材料（sourceId 与生成时一致）。"""

    sourceId: str
    title: str
    feedTitle: str
    feedUrl: str
    url: str
    publishedAt: str
    # F102：manual = 素材池条目（用户显式指定），auto = 自动选材。
    source: str = "auto"


class GptDigestExcludedRecent(BaseModel):
    """F101：被「近期已刊用」去重排除的一条材料明细。"""

    title: str
    feedTitle: str = ""
    url: str = ""
    reason: str = "recent_issue"


class GptDigestPoolInvalid(BaseModel):
    """F102：素材池失效条目（原文删除 / 引用非法）。"""

    entryRef: str
    reason: str


class GptDigestPreview(BaseModel):
    """GET /api/v1/gpt-digest/preview — 无副作用选材预览。"""

    windowStart: str
    windowEnd: str
    selected: list[GptDigestPreviewItem] = []
    counts: dict[str, int] = {}
    perSource: dict[str, int] = {}
    coveredSources: list[dict[str, str]] = []
    missingSources: list[dict[str, str]] = []
    excludedRecent: list[GptDigestExcludedRecent] = []
    poolInvalid: list[GptDigestPoolInvalid] = []
    note: str | None = None


class GlossaryTerm(BaseModel):
    """F21：一条术语（term 不唯一——同词不同含义可并存）。"""

    id: str
    term: str
    definition: str
    sourceRef: str | None = None
    # N083：受保护术语 —— 分段翻译后处理会把译文里大小写漂移的该词
    # 还原为原始词形（完全缺失则如实上报未保护）。
    protect: bool = False
    createdAt: str = ""
    updatedAt: str = ""


class GlossaryTermList(BaseModel):
    items: list[GlossaryTerm] = []


class GlossaryTermCreate(BaseModel):
    """POST/PATCH /api/v1/glossary — PATCH 全量替换 term+definition+protect。"""

    term: str
    definition: str
    sourceRef: str | None = None
    protect: bool = False


class TranslationVerificationFinding(BaseModel):
    """N082：一条可见数字差异（基于可见 token，非语义判断）。"""

    kind: Literal["missing", "changed", "added"]
    token: str
    sourceContext: str = ""
    translatedContext: str = ""


class TranslationVerificationBlock(BaseModel):
    """N082：一个块的校验结果（不可校验时诚实给 reason）。"""

    blockIndex: int
    verifiable: bool
    revised: bool = False
    reason: str | None = None
    findings: list[TranslationVerificationFinding] = []


class TranslationVerificationView(BaseModel):
    """GET /api/v1/entries/{ref}/translation-verification 响应。"""

    entryRef: str
    language: str
    totalFindings: int = 0
    blocks: list[TranslationVerificationBlock] = []


class GptDigestConfig(BaseModel):
    """F01/F02：一份主题日报配置（token 不在此响应中）。

    ``slots`` 为发布小时列表（升序、最多 4 个）；空列表 = 单时点
    （用 hour），期号退化为日期。"""

    id: int
    name: str
    enabled: bool
    hour: int
    timezone: str = ""
    windowHours: int = 24
    limitCount: int = 12
    perSourceCap: int = 2
    # F101：回看去重窗口（天；0=关，默认 7，上限 90）。
    lookbackDays: int = 7
    feedUrlAllow: str = ""
    # F04：材料源（window=订阅窗口 / read_later=稍后读 / starred=收藏）
    sourceKind: str = "window"
    slots: list[int] = []
    lastIssueKey: str | None = None
    lastError: str | None = None
    createdAt: str = ""


class GptDigestConfigList(BaseModel):
    items: list[GptDigestConfig] = []


class GptDigestCreate(BaseModel):
    """POST /api/v1/gpt-digest/configs（新配置默认 paused）。"""

    name: str
    hour: int | None = None
    timezone: str | None = None
    windowHours: int | None = None
    limitCount: int | None = None
    perSourceCap: int | None = None
    lookbackDays: int | None = None
    feedUrlAllow: str | None = None
    sourceKind: str | None = None
    slots: list[int] | None = None


class GptDigestConfigUpdate(BaseModel):
    """PUT /api/v1/gpt-digest/configs/{id} — partial（enabled=false = 暂停）。"""

    name: str | None = None
    enabled: bool | None = None
    hour: int | None = None
    timezone: str | None = None
    windowHours: int | None = None
    limitCount: int | None = None
    perSourceCap: int | None = None
    lookbackDays: int | None = None
    feedUrlAllow: str | None = None
    sourceKind: str | None = None
    slots: list[int] | None = None


class StorageUsage(BaseModel):
    """GET /api/v1/storage/usage — F36 用量口径（未知为 null，不冒充零）。"""

    database: dict[str, int]
    libraryAssets: dict[str, int | None]
    backupsDir: dict[str, int]
    totalKnownBytes: int
    budgetMB: int | None = None
    warning: str | None = None
    generatedAt: str


class TaskRecord(BaseModel):
    """F35：一条后台任务记录（备份/日报/邮件摘要）。"""

    kind: str
    status: str
    startedAt: str = ""
    finishedAt: str | None = None
    error: str | None = None
    ref: str = ""


class TaskRecordList(BaseModel):
    items: list[TaskRecord] = []


class SourceOverrideResult(BaseModel):
    """F11/F13/F001/N015：单个来源的 Lumi 覆盖（null = 该维度未启用）。"""

    feedUrl: str
    hiddenUntil: str | None = None
    showFrom: str | None = None
    staleAlertHours: int | None = None
    # F048/F055：per-source 提取策略与阅读样式覆盖（默认随全局）。
    extractPolicy: str = "rss"
    readerStyle: dict[str, object] | None = None
    # F066：per-source AI 禁用（派生数据保留，仅不再更新/不被 AI 消费）。
    aiDisabled: bool = False
    # N015：分时静音窗口（每周循环；[]/None = 未启用）。
    muteWindows: list[dict[str, object]] | None = None
    updatedAt: str = ""


class SourceOverrideList(BaseModel):
    items: list[SourceOverrideResult] = []


class SourceOverrideUpdate(BaseModel):
    """PUT /api/v1/sources/overrides — sentinel：缺席=不改，null=清除。"""

    feedUrl: str
    hiddenUntil: str | None = None
    showFrom: str | None = None
    staleAlertHours: int | None = Field(default=None, ge=1, le=8760)
    extractPolicy: str | None = None  # F048：'rss' | 'web'
    readerStyle: dict[str, object] | None = None  # F055：fontSize/lineHeight/width 子集
    aiDisabled: bool | None = None  # F066：per-source AI 禁用
    # N015：分时静音（每周循环窗口；None=清除，缺席=不改）。
    muteWindows: list[dict[str, object]] | None = None


class SourceAliasView(BaseModel):
    """N013：一个来源的显示别名（服务端真源；展示时优先于上游标题）。"""

    feedUrl: str
    customName: str
    updatedAt: str = ""


class SourceAliasList(BaseModel):
    items: list[SourceAliasView] = []


class SourceAliasUpdate(BaseModel):
    """PUT /api/v1/sources/alias — upsert + 变化时写历史（含上游快照）。"""

    feedUrl: str = Field(min_length=1)
    customName: str = Field(min_length=1, max_length=200)


class SourceAliasHistoryItem(BaseModel):
    """N013：一条改名历史（old 为 NULL = 首设别名；恢复 = 用旧名 PUT）。"""

    id: int
    feedUrl: str
    oldCustomName: str | None = None
    upstreamNameAtSave: str | None = None
    changedAt: str = ""


class SourceAliasHistoryList(BaseModel):
    items: list[SourceAliasHistoryItem] = []


class StaleSourceItem(BaseModel):
    """F001：一个超期来源（basis 诚实标注判定依据，绝不把发布时间
    冒充抓取成功；无条目投影的来源 basis=unknown 且不判超期）。"""

    feedUrl: str
    subscriptionRef: str | None = None
    title: str = ""
    staleAlertHours: int
    lastActivityAt: str | None = None
    ageHours: float | None = None
    basis: str = "latest_entry"


class StaleSourcesResponse(BaseModel):
    checked: int = 0
    items: list[StaleSourceItem] = []
    generatedAt: str = ""


class SettingsHistoryEntry(BaseModel):
    """F33：一次设置变更（diff 只含实际变化的键）。"""

    id: int
    changedAt: str
    action: str
    diff: dict[str, dict[str, object]] = {}


class SettingsHistoryList(BaseModel):
    items: list[SettingsHistoryEntry] = []


class SettingsRevertResult(BaseModel):
    """回退结果：applied=已应用的键值；skipped=因新修改被跳过的键。"""

    applied: dict[str, object] = {}
    skipped: dict[str, object] = {}


class CollectionTiming(BaseModel):
    """N040：三时点采集延迟块（未知保持 null，绝不臆造）。

    - upstreamPublishedLatest：投影中该源最新条目的发布时间（上游声明）；
    - freshrssFetchedLatest：FreshRSS crawlTimestampMsec（首次收录时刻，
      非「每次抓取时间」——上游不提供 per-entry 周期抓取时间，诚实标注
      口径；源从未提供 → None + basis="未提供 by upstream"）；
    - lumiProjectedLatest：投影最近一次写入（fetched_at MAX）；
    - latencyHint：最大缺口环节提示（数据不足 → None）。
    """

    upstreamPublishedLatest: str | None = None
    freshrssFetchedLatest: str | None = None
    freshrssFetchedBasis: str = "未提供 by upstream"
    lumiProjectedLatest: str | None = None
    latencyHint: str | None = None


class SubscriptionVolumeItem(BaseModel):
    """F12：单个订阅的收件量（投影未覆盖 → publishedCount=null）。"""

    feedUrl: str
    title: str
    publishedCount: int | None = None
    lastPublishedAt: str | None = None
    lastSyncedAt: str | None = None
    # N040：三时点采集延迟块（投影未覆盖 → None）。
    collectionTiming: CollectionTiming | None = None


class SubscriptionVolumeResponse(BaseModel):
    """GET /api/v1/sources/volume — 收件量概览（口径 = 发布时间窗口）。"""

    days: int
    since: str
    basis: str
    items: list[SubscriptionVolumeItem] = []
    generatedAt: str


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
    envRootConfigured: bool = False


class ObsidianRescanResult(BaseModel):
    """Bounded scan report with rename detection."""

    added: int
    changed: int
    removed: int
    renames: int
    unchanged: int
    skipped: int
    truncatedNotes: int = 0
    elapsedMs: int
    vaultPath: str = ""


class NoteView(BaseModel):
    """One projected note; contentHtml only on detail (client sanitizes).

    ``truncated`` marks notes that exceeded the bounded-projection caps
    — never silently shortened (P0-09d)."""

    ref: str
    relPath: str
    title: str
    tags: list[str] = []
    indexedAt: str
    wikilinks: list[str] | None = None
    contentHtml: str | None = None
    truncated: bool = False


class NoteListResponse(BaseModel):
    """Envelope for GET /api/v1/obsidian/notes."""

    items: list[NoteView]


# ---------------------------------------------------------------------------
# P16：多设备交接 —— 设备档案 / 导出模板 / 交接结果（每用户，非 owner 专属）
# ---------------------------------------------------------------------------


class ObsidianDeviceProfile(BaseModel):
    """One device where the user runs Obsidian (URI generation ONLY).

    Device profiles never describe server-side vault paths — the vault
    the BFF reads is mounted server-side (env or manual), while these
    names describe the user's OWN Obsidian app for obsidian:// links."""

    id: str
    label: str
    vaultName: str
    vaultIdentifier: str = ""
    platform: Literal["windows", "ios", "ipados", "other"] = "other"
    createdAt: str


class ObsidianDeviceProfileList(BaseModel):
    """Envelope for GET /api/v1/obsidian/devices."""

    items: list[ObsidianDeviceProfile]


class ObsidianDeviceProfilePayload(BaseModel):
    """POST/PUT body — full payload both for create and update."""

    model_config = {"extra": "forbid"}

    label: str = Field(min_length=1, max_length=100)
    vaultName: str = Field(min_length=1, max_length=200)
    vaultIdentifier: str = Field(default="", max_length=200)
    platform: Literal["windows", "ios", "ipados", "other"] = "other"


class ObsidianExportTemplateView(BaseModel):
    """GET /api/v1/obsidian/export-template."""

    template: str
    defaultTemplate: str
    allowedVars: list[str]


class ObsidianExportTemplateUpdate(BaseModel):
    """PUT /api/v1/obsidian/export-template body."""

    model_config = {"extra": "forbid"}

    template: str = Field(max_length=20000)


class ObsidianTemplatePreviewRequest(BaseModel):
    """POST /api/v1/obsidian/export-template/preview body.

    ``entryRef`` omitted → renders against fixture text (settings page);
    present → renders against the real article (reader-side preview)."""

    model_config = {"extra": "forbid"}

    template: str = Field(max_length=20000)
    entryRef: str | None = None


class ObsidianTemplatePreviewResult(BaseModel):
    """Rendered preview + honest unknown-variable list (UI validation)."""

    text: str
    unknownVars: list[str] = []
    source: Literal["entry", "fixture"] = "fixture"


class ObsidianExportHandoffRequest(BaseModel):
    """POST /api/v1/obsidian/export-handoff body."""

    model_config = {"extra": "forbid"}

    entryRef: str
    deviceId: str


class ObsidianExportHandoffResult(BaseModel):
    """Honest handoff verdict — the UI must never claim a vault write.

    ``mode='uri'``  → open ``uri``; the user confirms the save IN Obsidian.
    ``mode='file'`` → URI budget exceeded (reason='tooLong') → download
    ``filename`` + clipboard fallback instead."""

    mode: Literal["uri", "file"]
    uri: str | None = None
    reason: str | None = None
    filename: str
    content: str
    unknownVars: list[str] = []
    deviceLabel: str = ""


class TagItemsResponse(BaseModel):
    """GET /api/v1/tags/{id}/items — one tag's refs, resolved server-side."""

    items: list[ResolvedItem]


class ReadLaterItem(BaseModel):
    """One read-later timeline row (P0-01: server-driven list).

    ``entry`` is the RSS card from the projection (or a live adapter
    fallback); ``resolved`` is the unified registry view for library
    refs (inbox pushes etc. are first-class read-later members since
    0021 — Q-P1-05). A dangling member surfaces as ``stale=True`` with
    no card instead of disappearing from the list.
    """

    itemRef: str
    addedAt: str
    stale: bool = False
    entry: SearchItem | None = None
    resolved: ResolvedItem | None = None


class ReadLaterTimelineResponse(BaseModel):
    """GET /api/v1/workspaces/read-later/timeline."""

    items: list[ReadLaterItem]
    nextCursor: str | None = None


class ResearchPackRequest(BaseModel):
    """POST workspaces/{id}/research-pack — F27 导出选项。"""

    title: str | None = None
    includeNotes: bool = True


class ReadLaterSnoozeRequest(BaseModel):
    """POST snooze — 延后到该 ISO 时刻（必须为未来）。"""

    until: str


class ReadLaterSnoozeResult(BaseModel):
    """延后结果 / 单项（F19）。"""

    itemRef: str
    snoozedUntil: str


class ReadLaterSnoozedList(BaseModel):
    """GET snoozed — 当前延后中的项目。"""

    items: list[ReadLaterSnoozeResult] = []


class LibrarySearchItem(BaseModel):
    """Library leg of unified search (same shape philosophy as SearchItem)."""

    ref: str
    kind: str
    title: str
    url: str | None = None
    snippet: str = ""
    updatedAt: str = ""
    stale: bool = False


class FavoritesResponse(BaseModel):
    """Federated favorites: rss star + library favorite, merged for
    display only — each stays owned by its own domain."""

    rss: list[SearchItem]
    library: list[LibrarySearchItem]
    libraryError: str | None = None
    libraryTotal: int = 0


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
    """One fused retrieval hit (ref resolves to real content).

    F092：title/modelId 为后端如实返回；score 缺失时前端显示「—」
    绝不编造百分比。"""

    ref: str
    kind: str
    text: str
    score: float
    title: str | None = None
    modelId: str | None = None


class RagSearchResponse(BaseModel):
    """Envelope for GET /api/v1/rag/search (honest degradation flags)."""

    items: list[RagSearchItem]
    semanticUsed: bool
    semanticError: str | None = None


class RagRebuildResult(BaseModel):
    """Bounded rebuild report（F093 起为作业感知：jobId/status）。"""

    chunks: int
    elapsedMs: int
    jobId: str | None = None
    status: str | None = None


class RagEnableResult(BaseModel):
    """Explicit model-enable acknowledgement."""

    enabled: bool


# ---------------------------------------------------------------------------
# Library domain (phase2 G8) — tags + derived graph
# ---------------------------------------------------------------------------


class TagBinding(BaseModel):
    """One tag or binding view."""

    id: int | None = None
    name: str
    count: int = 0
    ref: str | None = None
    origin: str | None = None
    status: str | None = None


class TagListResponse(BaseModel):
    """Envelope for GET /api/v1/tags (suggested rows never appear)."""

    items: list[TagBinding]


class TagAssignRequest(BaseModel):
    """POST /api/v1/tags/assign — attach one tag to one ItemRef."""

    model_config = {"extra": "forbid"}

    itemRef: str
    name: str
    origin: str = "manual"


class TagRenameRequest(BaseModel):
    """PATCH /api/v1/tags/{id}."""

    model_config = {"extra": "forbid"}

    name: str


class TagMergeRequest(BaseModel):
    """POST /api/v1/tags/merge — merge source INTO target."""

    model_config = {"extra": "forbid"}

    sourceId: int
    targetId: int


class TagMergePreview(BaseModel):
    """GET /api/v1/tags/merge/preview — affected counts, read-only."""

    sourceId: int
    targetId: int
    bindings: int
    overlaps: int
    willMove: int


class TagMergeResult(BaseModel):
    """POST /api/v1/tags/merge — committed outcome."""

    targetId: int
    movedBindings: int
    dedupedBindings: int


class TagSuggestionsResponse(BaseModel):
    """AI suggestions — computed only, never stored until accepted."""

    suggestions: list[str]


class GraphNode(BaseModel):
    """One derived graph node (item | tag | workspace | wikilink)."""

    ref: str
    label: str
    kind: str
    degree: int = 0


class GraphEdge(BaseModel):
    """One derived edge."""

    src: str
    dst: str
    kind: str


class GraphResponse(BaseModel):
    """Envelope for GET /api/v1/graph (truncation reported honestly).

    ``totalNodes`` is the pre-truncation candidate count; ``returnedNodes``
    is what the payload carries (P0-10d — the truncated count never
    masquerades as the total).
    """

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    totalNodes: int
    returnedNodes: int = 0


# ---------------------------------------------------------------------------
# phase2 recovery (IMPL-BE-2) — Mail additions (append-only block; the
# G5 Mail models above are untouched)
# ---------------------------------------------------------------------------


class MailBridgeListCreatedV2(MailBridgeListCreated):
    """Creation response + honest FreshRSS auto-subscribe status
    (P0-06i). Extends the G5 shape; ``subscribeFailed``/``atomPath`` are
    omitted from wire responses when unset
    (response_model_exclude_none), keeping the historical payload
    byte-compatible on success."""

    subscribeFailed: str | None = None
    atomPath: str | None = None


class MailImapSettings(BaseModel):
    """GET /api/v1/mail/imap/settings — password never returned."""

    configured: bool = False
    host: str = ""
    port: int = 993
    user: str = ""
    folder: str = "INBOX"
    ssl: bool = True
    listUuid: str = ""
    intervalSeconds: int = 300
    enabled: bool = True
    passwordConfigured: bool = False


class MailImapSettingsUpdate(BaseModel):
    """PUT /api/v1/mail/imap/settings — partial; password write-only."""

    model_config = {"extra": "forbid"}

    host: str | None = None
    port: int | None = None
    user: str | None = None
    folder: str | None = None
    ssl: bool | None = None
    listUuid: str | None = None
    intervalSeconds: int | None = None
    enabled: bool | None = None
    password: str | None = None


class MailImapTestResult(BaseModel):
    """POST /api/v1/mail/imap/test — honest connectivity report."""

    ok: bool
    error: str | None = None


class MailImapPollResult(BaseModel):
    """POST /api/v1/mail/imap/poll — one bounded manual poll."""

    fetched: int
    ingested: list[MailIngestResult]


# ---------------------------------------------------------------------------
# Library domain (phase2 recovery P0-03) — server-side clip pipeline.
# Appended by IMPL-BE-1; the pre-recovery Clip models above are kept in
# place untouched (append-only policy). routers/clips.py binds the ACTIVE
# contracts for /api/v1/library/clips* to the models below: all clip
# content is derived server-side, client-submitted HTML is never stored.
# ---------------------------------------------------------------------------


class ClipCreateRequest(BaseModel):
    """POST /api/v1/library/clips — URL confirmation only.

    ``url`` is required; ``finalUrl`` (from the /fetch preview) is
    fetched instead when present. ``title``/``byline``/``contentHtml``/
    ``contentText``/``fetchedAt`` are deprecated client-derived fields:
    accepted for wire-shape compatibility with the pre-recovery client,
    NEVER trusted or stored (server re-derives everything).
    """

    model_config = {"extra": "forbid"}

    url: str
    finalUrl: str | None = None
    title: str | None = None
    byline: str | None = None
    contentHtml: str | None = None
    contentText: str | None = None
    fetchedAt: str | None = None


class ClipFetchArticleResult(BaseModel):
    """POST /api/v1/library/clips/fetch — the server-produced article.

    ``url`` echoes the requested URL; ``finalUrl`` is where the fetch
    actually landed (redirects followed). ``contentHtml`` is already
    server-sanitized (allow-list); the browser DOMPurify pass remains
    the final render boundary.
    """

    url: str
    finalUrl: str
    title: str
    byline: str | None = None
    contentHtml: str
    contentText: str


# ---------------------------------------------------------------------------
# Inbox push sources (0021) — machine-to-machine connector + user reads
# ---------------------------------------------------------------------------


class InboxSourceCreated(BaseModel):
    """POST /api/v1/inbox/sources — the bearer ``secret`` is shown exactly
    once, here; list/read paths never echo it."""

    uuid: str
    name: str
    secret: str
    ingestPath: str
    createdAt: str


class InboxSourceCreate(BaseModel):
    """POST /api/v1/inbox/sources body."""

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class InboxSource(BaseModel):
    """One inbox connector without its secret."""

    uuid: str
    name: str
    enabled: bool
    lastSuccessAt: str | None = None
    lastError: str | None = None
    createdAt: str


class InboxIngestItem(BaseModel):
    """POST /api/v1/inbox/ingest/{uuid} body.

    Unknown fields are rejected (honest machine contract). ``content`` is
    plain text; ``contentHtml`` is UNTRUSTED and is sanitized server-side
    (allow-list) before storage — the browser DOMPurify pass remains the
    final render boundary. There is no attachment storage in v1; senders
    must not include an ``attachments`` field.
    """

    model_config = {"extra": "forbid"}

    guid: str = Field(min_length=1, max_length=512)
    title: str | None = Field(default=None, min_length=1, max_length=512)
    url: str | None = Field(default=None, max_length=2048)
    author: str | None = Field(default=None, min_length=1, max_length=256)
    content: str | None = Field(default=None, max_length=200_000)
    contentHtml: str | None = Field(default=None, max_length=500_000)
    publishedAt: str | None = Field(default=None, max_length=64)
    categories: list[str] = Field(default_factory=list, max_length=24)


class InboxIngestResult(BaseModel):
    """``created`` on first sight of (source, guid); ``exists`` on replay."""

    status: Literal["created", "exists"]
    ref: str


class InboxItemRow(BaseModel):
    """One inbox item as a bare ItemRef row; cards come from
    POST /api/v1/resolve (the registry owns display shapes)."""

    ref: str
    createdAt: str
    sourceUuid: str


class InboxItemList(BaseModel):
    items: list[InboxItemRow]
    nextCursor: str | None = None
    hasMore: bool


class SourceRegistryEntry(BaseModel):
    """One row of the unified read-only source registry (统一 API ≠ 统一
    数据库): synthesized from the owning stores at request time, never a
    second source of truth."""

    id: str
    type: str
    label: str
    enabled: bool
    summary: str | None = None
    lastSuccessAt: str | None = None
    lastError: str | None = None


class SourceRegistryResponse(BaseModel):
    sources: list[SourceRegistryEntry]
    generatedAt: str


# ---------------------------------------------------------------------------
# F021 手工关联内容
# ---------------------------------------------------------------------------


class ResolvedRefView(BaseModel):
    """Relation end resolved through the source registry (stale-safe)."""

    ref: str
    domain: str
    kind: str
    title: str
    source: str
    datetime: str | None = None
    excerpt: str | None = None
    url: str | None = None
    stale: bool = False
    staleReason: str | None = None


class RelationCreate(BaseModel):
    """POST /api/v1/relations body."""

    model_config = {"extra": "forbid"}

    srcRef: str = Field(min_length=1, max_length=600)
    dstRef: str = Field(min_length=1, max_length=600)
    note: str = Field(default="", max_length=500)


class RelationView(BaseModel):
    """One manual relation with BOTH ends resolved; ``stale`` is true when
    either end no longer resolves (the relation itself is kept)."""

    id: int
    srcRef: str
    dstRef: str
    note: str
    createdAt: str
    src: ResolvedRefView
    dst: ResolvedRefView
    stale: bool = False


class RelationList(BaseModel):
    items: list[RelationView]


class SavedSearchPinOrder(BaseModel):
    """PATCH …/views/{id}/pin-order body。"""

    model_config = {"extra": "forbid"}

    pinOrder: int = Field(ge=0, le=200)


class SavedSearchCount(BaseModel):
    """GET …/views/{id}/count — 服务端真实计数（有界）。"""

    count: int
    capped: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# F022 收件箱归类规则
# ---------------------------------------------------------------------------


class InboxRuleCreate(BaseModel):
    """POST /api/v1/inbox/rules body."""

    model_config = {"extra": "forbid"}

    field: Literal["source", "title"]
    operator: Literal["contains", "equals"]
    value: str = Field(min_length=1, max_length=200)
    targetWorkspaceId: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    priority: int | None = None


class InboxRuleUpdate(BaseModel):
    """PATCH /api/v1/inbox/rules/{id} body — partial."""

    model_config = {"extra": "forbid"}

    field: Literal["source", "title"] | None = None
    operator: Literal["contains", "equals"] | None = None
    value: str | None = Field(default=None, min_length=1, max_length=200)
    targetWorkspaceId: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = Field(default=None, strict=True)


class InboxRule(BaseModel):
    id: int
    priority: int
    field: str
    operator: str
    value: str
    targetWorkspaceId: str
    enabled: bool
    createdAt: str


class InboxRuleList(BaseModel):
    items: list[InboxRule]


class InboxRuleDryRun(BaseModel):
    """POST /api/v1/inbox/rules/dry-run body — never persists anything."""

    model_config = {"extra": "forbid"}

    field: Literal["source", "title"]
    value: str = Field(min_length=1, max_length=200)
    source: str | None = Field(default=None, max_length=200)


class InboxRuleDryRunResult(BaseModel):
    matchedRule: InboxRule | None = None
    explanation: str


# ---------------------------------------------------------------------------
# F023 跨来源作者聚合
# ---------------------------------------------------------------------------


class AuthorSummary(BaseModel):
    """One aggregated author: canonical display name + item count (aliases
    folded into the canonical count only via explicit user aliases)."""

    author: str
    count: int


class AuthorList(BaseModel):
    items: list[AuthorSummary]


class AuthorAliasCreate(BaseModel):
    """POST /api/v1/authors/aliases body — explicit user merge only."""

    model_config = {"extra": "forbid"}

    alias: str = Field(min_length=1, max_length=200)
    canonical: str = Field(min_length=1, max_length=200)


class AuthorAlias(BaseModel):
    alias: str
    canonical: str
    createdAt: str


class AuthorAliasList(BaseModel):
    items: list[AuthorAlias]


class AuthorItemsResponse(BaseModel):
    """Items of one canonical author (aliases folded in)."""

    author: str
    items: list[EntryListItem]
    hasMore: bool


# ---------------------------------------------------------------------------
# F024 积压整理助手
# ---------------------------------------------------------------------------


class BacklogPreviewRequest(BaseModel):
    """POST /api/v1/entries/backlog-preview body.

    starred / read-later are ALWAYS excluded server-side — passing false
    does not disable the protection (the response echoes effective
    exclusions)."""

    model_config = {"extra": "forbid"}

    olderThanDays: int = Field(ge=1, le=3650)
    feedUrl: str | None = Field(default=None, max_length=2048)
    categoryId: str | None = Field(default=None, max_length=200)
    excludeStarred: bool = True
    excludeReadLater: bool = True


class BacklogSampleItem(BaseModel):
    ref: str
    title: str
    publishedAt: str | None = None


class BacklogPreviewResponse(BaseModel):
    count: int
    sample: list[BacklogSampleItem]
    effectiveExclusions: list[str]
    confirmPreviewToken: str


class BacklogApplyRequest(BaseModel):
    """POST /api/v1/entries/backlog-apply body — must carry the one-shot
    preview token (30s) so the applied condition cannot drift."""

    model_config = {"extra": "forbid"}

    olderThanDays: int = Field(ge=1, le=3650)
    feedUrl: str | None = Field(default=None, max_length=2048)
    categoryId: str | None = Field(default=None, max_length=200)
    excludeStarred: bool = True
    excludeReadLater: bool = True
    confirmPreviewToken: str = Field(min_length=16, max_length=128)


class BacklogApplyResponse(BaseModel):
    applied: int
    failed: list[BacklogSampleItem]
    effectiveExclusions: list[str]


# ---------------------------------------------------------------------------
# F025 AI 输入预览与范围控制
# ---------------------------------------------------------------------------


class AiInputScope(BaseModel):
    """Optional request scope for AI generation endpoints."""

    model_config = {"extra": "forbid"}

    maxChars: int | None = Field(default=None, ge=512, le=50_000)


# ---------------------------------------------------------------------------
# F027 AI 结果版本
# ---------------------------------------------------------------------------


class SummaryVersionView(BaseModel):
    versionId: str
    summary: str
    provider: str
    model: str
    createdAt: str


class SummaryVersionsInfo(BaseModel):
    versions: list[SummaryVersionView]
    activeVersionId: str | None = None


class EntrySummaryVersions(EntrySummary):
    """GET/POST summary response + version history (旧→新)."""

    inputChars: int | None = None
    truncated: bool = False
    versions: list[SummaryVersionView] = Field(default_factory=list)
    activeVersionId: str | None = None



# ---------------------------------------------------------------------------
# F030 问答模板
# ---------------------------------------------------------------------------


class QaTemplate(BaseModel):
    id: str
    name: str
    text: str
    createdAt: str
    updatedAt: str


class QaTemplateList(BaseModel):
    items: list[QaTemplate]


# ---------------------------------------------------------------------------
# W5: F081–F100
# ---------------------------------------------------------------------------


class BatchEditPatch(BaseModel):
    """F081 批量元数据编辑补丁——字段缺省（None）= 未勾选，保持原值。

    titleSuffix 只允许追加模式；tags add/remove 幂等；workspaceId =
    移动目标（记录原工作区）。仅作用于 Lumi 自有字段。"""

    model_config = {"extra": "forbid"}

    titleSuffix: str | None = None
    tagsAdd: list[str] | None = None
    tagsRemove: list[str] | None = None
    workspaceId: str | None = None


class BatchEditItemState(BaseModel):
    title: str
    tags: list[str] = []
    workspaceIds: list[str] = []


class BatchEditPreviewItem(BaseModel):
    ref: str
    before: BatchEditItemState
    after: BatchEditItemState


class BatchEditPreviewRequest(BaseModel):
    model_config = {"extra": "forbid"}

    refs: list[str] = Field(min_length=1, max_length=50)
    patch: BatchEditPatch


class BatchEditPreviewResponse(BaseModel):
    items: list[BatchEditPreviewItem]


class BatchEditApplyItem(BaseModel):
    ref: str
    ok: bool
    error: str | None = None


class BatchEditApplyRequest(BatchEditPreviewRequest):
    pass


class BatchEditApplyResponse(BaseModel):
    items: list[BatchEditApplyItem]
    applied: int = 0
    failed: int = 0


class MergePolicy(BaseModel):
    """F082 合并策略——逐字段保留选择；tags 恒并集、workspace 恒取
    primary（规格固定，不进 policy）。"""

    model_config = {"extra": "forbid"}

    title: str = "primary"
    note: str = "primary"


class MergePreviewRequest(BaseModel):
    model_config = {"extra": "forbid"}

    primaryRef: str
    duplicateRef: str


class MergeFieldCompare(BaseModel):
    field: str
    primary: object = None
    duplicate: object = None


class MergePreviewResponse(BaseModel):
    primaryRef: str
    duplicateRef: str
    fields: list[MergeFieldCompare]
    annotationCount: int = 0
    assetUuids: list[str] = []


class MergeRequest(MergePreviewRequest):
    policy: MergePolicy = Field(default_factory=MergePolicy)


class MergeResult(BaseModel):
    mergedRef: str
    removedRef: str
    tagsUnion: list[str] = []
    movedAnnotations: int = 0
    trashed: bool = True


class WorkspaceTemplate(BaseModel):
    """F083 工作区模板（config 不含条目内容/凭据）。"""

    id: str
    name: str
    config: dict = {}
    createdAt: str


class WorkspaceTemplateList(BaseModel):
    items: list[WorkspaceTemplate] = []


class SaveAsTemplateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=50)


class FromTemplateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    templateId: str
    name: str
    includeExampleItems: bool = False
    exampleRefs: list[str] = Field(default_factory=list, max_length=5)


class WorkspaceFromTemplateResult(BaseModel):
    workspace: Workspace
    addedExampleRefs: list[str] = []
    skippedExampleRefs: list[str] = []


class WorkspacePatch(BaseModel):
    """PATCH /api/v1/workspaces/{id}（F084 扩展：archive/restore）。

    name/description 缺省 = 不修改；archived=True 归档、False 恢复。"""

    model_config = {"extra": "forbid"}

    name: str | None = None
    description: str | None = None
    archived: bool | None = None


class BoardColumn(BaseModel):
    """F085 看板一列（前 50 条 + 真实总数）。"""

    status: str
    items: list[dict] = []
    total: int = 0


class WorkspaceBoardResponse(BaseModel):
    workspaceId: str
    columns: list[BoardColumn] = []


class BoardUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str
    status: str


class WorkspaceGoalView(BaseModel):
    """F086 阅读目标（进度 = 看板 done 去重条目数，真实事件驱动）。"""

    workspaceId: str
    targetCount: int
    deadline: str | None = None
    doneCount: int = 0
    createdAt: str


class WorkspaceGoalPut(BaseModel):
    model_config = {"extra": "forbid"}

    targetCount: int = Field(ge=1)
    deadline: str | None = None


class BookmarkCheckRequest(BaseModel):
    """F087 书签失效检查（≤30 个，重复 ref 去重）。"""

    model_config = {"extra": "forbid"}

    refs: list[str] = Field(min_length=1, max_length=30)


class BookmarkCheckItem(BaseModel):
    ref: str
    status: str
    httpStatus: int | None = None
    finalUrl: str | None = None
    checkedAt: str
    error: str | None = None


class BookmarkCheckResponse(BaseModel):
    items: list[BookmarkCheckItem] = []


class ResearchPackPreviewRequest(BaseModel):
    """F088 资料包预览（可选纳入快照资产）。"""

    model_config = {"extra": "forbid"}

    includeSnapshots: list[str] = Field(default_factory=list, max_length=50)


class SnapshotBrief(BaseModel):
    uuid: str
    title: str
    bytes: int


class ResearchPackPreviewResponse(BaseModel):
    entryCount: int
    missingCount: int
    estBytes: int
    snapshots: list[SnapshotBrief] = []


class ClipRevisionRequest(BaseModel):
    """F089 剪藏手工修订（保留块 id 列表；全移除需 force）。"""

    model_config = {"extra": "forbid"}

    blocks: list[str] = Field(max_length=500)
    note: str | None = None
    force: bool = False
    baseContentHash: str | None = None


class ClipRevisionInfo(BaseModel):
    revisedAt: str
    note: str | None = None
    baseContentHash: str | None = None


class ClipDetailResponse(BaseModel):
    """GET 剪藏详情（含原始与修订后内容）。"""

    ref: str
    url: str
    title: str
    byline: str | None = None
    fetchedAt: str
    createdAt: str
    original: dict = {}
    revised: ClipRevisionInfo | None = None
    content: dict = {}


class LumiNoteCreate(BaseModel):
    """F090 手动创建笔记（contentMd ≤100KB）。"""

    model_config = {"extra": "forbid"}

    title: str = Field(min_length=1, max_length=500)
    contentMd: str = Field(max_length=100 * 1024)
    workspaceId: str | None = None


class LumiNoteUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, max_length=500)
    contentMd: str | None = Field(default=None, max_length=100 * 1024)
    baseUpdatedAt: str | None = None


class LumiNoteDetail(BaseModel):
    uuid: str
    title: str
    contentMd: str
    workspaceId: str | None = None
    createdAt: str
    updatedAt: str


class RagExclusionItem(BaseModel):
    """F091 单来源索引排除状态（含受影响分块计数预览）。"""

    feedUrl: str
    ragExcluded: bool
    aiDisabled: bool
    affectedChunks: int = 0


class RagExclusionList(BaseModel):
    items: list[RagExclusionItem] = []


class RagExclusionPut(BaseModel):
    model_config = {"extra": "forbid"}

    feedRef: str
    excluded: bool


class RagInconsistencyItem(BaseModel):
    """F100 版本失配条目（basis: content_hash | embedding_model）。"""

    ref: str
    storedHash: str | None = None
    currentHash: str | None = None
    basis: str


class RagInconsistencyList(BaseModel):
    modelId: str
    items: list[RagInconsistencyItem] = []


class RagRepairRequest(BaseModel):
    model_config = {"extra": "forbid"}

    refs: list[str] = Field(min_length=1, max_length=50)


class RagRepairResult(BaseModel):
    repaired: list[str] = []
    failed: list[dict] = []


class AgentThreadUpdate(BaseModel):
    """F094/F098 会话设置（scope / toolPolicy；None = 清除/不修改按键）。

    scope=None 显式清除范围锁定；键缺省 = 不修改。"""

    model_config = {"extra": "forbid"}

    title: str | None = None
    scope: dict | None = None
    clearScope: bool = False
    toolPolicy: dict | None = None
    clearToolPolicy: bool = False


class AgentBranchRequest(BaseModel):
    """F099 从指定消息分支。"""

    model_config = {"extra": "forbid"}

    messageIndex: int = Field(ge=0)
