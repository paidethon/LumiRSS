/** 与 BFF 真实契约一一对应的最小前端类型（docs/specs/0005-web-shell.md）。
 * 不添加后端不存在的字段。 */

export type EntryView = 'all' | 'unread' | 'starred'

/** FreshRSS 分类（0011：subscription/list 的 categories[0]，单分类模型）。
 * id 是稳定 key（user/-/label/<名>），label 是展示名。 */
export interface FeedCategory {
  id: string
  label: string
}

/** GET /api/v1/categories —— 分类列表（含空分类；0013 Gate 1 契约）。 */
export interface Category {
  id: string
  label: string
}

/** GET /api/v1/subscriptions 的项（0013 Gate 1）：subscriptionRef 是
 * Lumi-owned opaque 引用，前端只透传，绝不拼装/解析。 */
export interface Subscription {
  subscriptionRef: string
  title: string
  feedUrl: string
  category: FeedCategory | null
}

export interface Feed {
  title: string
  feedUrl: string
  /** FreshRSS 真实分类；无分类 → null（UI 归入未分组） */
  category: FeedCategory | null
}

export interface EntryListItem {
  entryRef: string
  title: string
  feedTitle: string
  author: string | null
  url: string | null
  publishedAt: string | null
  read: boolean
  starred: boolean
}

export interface EntryListResponse {
  items: EntryListItem[]
  nextCursor: string | null
}

/** Detail（GET /api/v1/entries/{entryRef}）——与 BFF EntryDetail 一一对应。
 * contentHtml 是不可信的上游 RSS HTML：BFF 只搬运，sanitize 在渲染前
 * 由 DOMPurify 完成（见 lib/sanitize-article-html.ts）。 */
export interface EntryDetail {
  entryRef: string
  title: string
  feedTitle: string
  author: string | null
  url: string | null
  publishedAt: string | null
  read: boolean
  starred: boolean
  contentText: string
  contentHtml: string | null
}

export interface ApiErrorResponse {
  error: { type: string; message: string }
}

/** POST /api/v1/feed-preview（0013 Gate 2）—— 无副作用的直接 RSS/Atom
 * 预览：只有可靠元数据，无正文/条目。format 与 BFF 解析结果一致。 */
export interface FeedPreviewMetadata {
  title: string
  feedUrl: string
  siteUrl: string | null
  description: string | null
  format: 'rss' | 'atom'
  alreadySubscribed: boolean
}

/** POST /api/v1/opml/import/preview（0013 Gate 4）—— 无副作用的导入预览。
 * duplicates 只包含可靠可判定项：与现有订阅的 feedUrl 精确匹配 + 文件内
 * 重复；无任何推测性判断。 */
export interface OpmlImportPreview {
  totalFeeds: number
  newFeeds: number
  duplicates: number
  invalidEntries: number
  categories: { label: string; feedCount: number }[]
}

/** POST /api/v1/opml/import（merge 语义）的单条导入结果。 */
export interface OpmlImportAdded {
  feedUrl: string
  title: string
  categoryLabel: string | null
  categoryApplied: boolean
}

export interface OpmlImportResult {
  added: OpmlImportAdded[]
  duplicates: { feedUrl: string; title: string }[]
  failed: { feedUrl: string; title: string; error: string }[]
  categoriesCreated: string[]
}

/** GET /api/v1/freshrss-ui —— 高级逃生入口（未配置时为 null，UI 不渲染）。 */
export interface FreshRssUiInfo {
  url: string | null
}

/** POST /api/v1/source-discovery 的候选（0014）：
 * declared = rel=alternate 声明（未预取，format 未知）；
 * probed = 常见端点探测成功（title/format 已解析）。 */
export interface DiscoveryCandidate {
  feedUrl: string
  title: string | null
  source: 'declared' | 'probed'
  format: 'rss' | 'atom' | null
}

/** POST /api/v1/source-discovery 响应（0014）。 */
export interface SourceDiscoveryResponse {
  candidates: DiscoveryCandidate[]
}

/** GET /api/v1/rsshub/routes 的参数描述符（0014，Lumi-owned）。 */
export interface RssHubParameter {
  key: string
  label: string
  required: boolean
  pattern: string
  example: string
  help: string
}

/** GET /api/v1/rsshub/routes 的路由描述符（0014，Lumi-owned）。
 * 前端只用于渲染参数表单；路径构造在服务端完成。 */
export interface RssHubRoute {
  id: string
  title: string
  description: string
  pathTemplate: string
  parameters: RssHubParameter[]
}

/** GET /api/v1/rsshub/routes 响应（0014）：
 * configured=false 时服务端未设置 RSSHub 实例（目录仍可用，预览会 503）。 */
export interface RssHubRoutesResponse {
  configured: boolean
  routes: RssHubRoute[]
}

/** GET/PUT /api/v1/settings/ai —— 浏览器安全视图：所有 key 相关字段只报
 * 布尔状态；key 本身永不下发。扩展字段支持浏览器管理的 Profile 层。 */
export interface AiSettings {
  provider: 'openai_compatible'
  baseUrl: string
  model: string
  summaryLanguage: 'zh-CN' | 'en'
  translationLanguage: 'zh-CN' | 'en'
  configured: boolean
  /** 环境变量 AI_API_KEY 是否存在（legacy 回退，只报存在性）。 */
  envKeyConfigured: boolean
  /** 浏览器设置的默认 Key（SecretsStore）或 env 回退是否可用。 */
  defaultKeyConfigured: boolean
  /** 用途 → profile id（'default' = 全局设置 + 默认 Key）。 */
  purposes: AiPurposes
  /** 各用途的有效解析（secret-free，用于 UI 展示真实状态）。 */
  purposeStatus: Record<AiPurposeKey, AiPurposeStatus>
}

export type AiPurposeKey = 'summary' | 'translation' | 'chat'

export type AiPurposes = Record<AiPurposeKey, string>

/** purposeStatus 条目：绝不包含任何 key 值。 */
export interface AiPurposeStatus {
  profileId: string
  source: 'default' | 'profile'
  profileLabel: string | null
  baseUrl: string
  model: string
  keyConfigured: boolean
  keySource: 'profile_secret' | 'default_secret' | 'env' | 'missing'
  configured: boolean
}

/** AI Profile（浏览器可管理；key 只见 keyConfigured 布尔）。 */
export interface AiProfile {
  id: string
  label: string
  provider: 'openai_compatible'
  baseUrl: string
  model: string
  enabled: boolean
  keyConfigured: boolean
  createdAt: string
  updatedAt: string
}

/** PUT /api/v1/settings/ai body：只含非机密字段，可部分更新。 */
export interface AiSettingsUpdate {
  baseUrl?: string
  model?: string
  summaryLanguage?: 'zh-CN' | 'en'
  translationLanguage?: 'zh-CN' | 'en'
}

/** GET /api/v1/version —— BFF 构建溯源（版本错配诊断；无 env/路径/secret）。 */
export interface ApiVersion {
  version: string
  commit: string
  apiVersion: number
}

/** GET/PATCH /api/v1/settings（0017）—— portable 设置的浏览器安全视图。
 * stored=false 表示服务端尚无持久化文档（客户端本地值可作迁移种子）；
 * stored=true 表示这些字段是服务端持久值（server-durable）。 */
export interface ServerSettings {
  schemaVersion: number
  stored: boolean
  themeMode: 'system' | 'light' | 'dark'
  accentColor: string
  uiFontStack: 'default' | 'sans' | 'serif' | 'mono'
  uiFontSize: number
  reduceMotion: boolean
  readerFontFamily: 'system' | 'sans' | 'serif' | 'mono'
  readerFontSize: number
  readerLineHeight: number
  readerParagraphSpacing: number
  readerContentWidth: number
  readerPageMargin: number
  readerBackground: 'follow' | 'sepia' | 'warm' | 'paper' | 'mint' | 'custom'
  readerBackgroundCustom: string
  readerJustify: boolean
  readerImageMode: 'all' | 'grayscale' | 'hidden'
  readerTextIndent: 'off' | '2em'
  readerHangingPunctuation: boolean
  readerChineseConversion: 'off' | 's2t' | 't2s' | 'tw' | 'hk'
  readerShowReadingTime: boolean
  readerCodeHighlight: 'auto' | 'off'
  readerCodeTheme: 'auto' | 'github-light' | 'github-dark' | 'vitesse-light' | 'vitesse-dark'
  scrollMarkUnread: boolean
}

/** GET/POST /api/v1/entries/{entryRef}/summary 状态（0015）。 */
export type SummaryStatus = 'not_generated' | 'generating' | 'success' | 'failed'

export interface EntrySummary {
  status: SummaryStatus
  summary: string | null
  provider: string | null
  model: string | null
  promptVersion: string | null
  language: string | null
  generatedAt: string | null
  failureType: string | null
  cached: boolean
}

/** GET/POST /api/v1/entries/{entryRef}/translation 状态（0016）。
 * 译文为纯文本；原文永远不会被替换。 */
export type TranslationStatus = 'not_generated' | 'generating' | 'success' | 'failed'

export interface EntryTranslation {
  status: TranslationStatus
  translatedTitle: string | null
  translatedText: string | null
  provider: string | null
  model: string | null
  promptVersion: string | null
  targetLanguage: string | null
  generatedAt: string | null
  failureType: string | null
  cached: boolean
}

/** GET /api/v1/entries/{entryRef}/conversation（0016）——
 * 文章限定对话：status empty = 尚无消息。 */
export type ConversationRole = 'user' | 'assistant'

export interface ConversationMessage {
  id: number
  role: ConversationRole
  content: string
  createdAt: string
}

export interface EntryConversation {
  status: 'empty' | 'active'
  messages: ConversationMessage[]
}

// ---- 0018 Operations ----

export type DependencyStatus =
  | 'unconfigured'
  | 'healthy'
  | 'unauthenticated'
  | 'unavailable'

export interface OperationsComponentStatus {
  status: DependencyStatus
  latencyMs: number | null
  lastCheckedAt: string | null
  error: { type: string } | null
}

export interface OperationsStatus {
  lumi: { status: string; version: string }
  sqlite: { status: string; schemaVersion?: number }
  freshrss: OperationsComponentStatus & { configured: boolean }
  rsshub: OperationsComponentStatus & {
    configured: boolean
    restartRequired: boolean
    pendingConfigCount: number
  }
  backup: {
    webdavConfigured: boolean
    lastBackup: BackupJob | null
  }
}

// ---- 0018 RSSHub Control Center ----

export type RssHubItemType = 'int' | 'bool' | 'string' | 'enum' | 'secret'

export interface RssHubConfigItem {
  key: string
  label: string
  description: string
  group: string
  type: RssHubItemType
  default: number | string | boolean
  editable: boolean
  secret: boolean
  restartRequired: boolean
  options: string[] | null
  value?: number | string | boolean
  configured?: boolean
}

export interface RssHubConfigGroup {
  id: string
  label: string
  items: RssHubConfigItem[]
}

export interface RssHubConfig {
  schemaVersion: number
  configured: boolean
  pendingCount: number
  pendingSecrets: boolean
  groups: RssHubConfigGroup[]
}

// ---- 0018 WebDAV / Backup / Restore ----

export interface WebDavSettings {
  configured: boolean
  serverUrl: string
  username: string
  remoteDir: string
  tlsVerify: boolean
  passwordConfigured: boolean
}

export interface WebDavTestResult {
  status: 'ok' | 'failed'
  message?: string
}

export type BackupJobStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'interrupted'

export type BackupJobType = 'full' | 'safety' | 'restore'

export interface BackupJob {
  id: string
  type: BackupJobType
  status: BackupJobStatus
  stage: string | null
  target: string | null
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
  summary: {
    filename?: string
    target?: string
    sizeBytes?: number
    components?: string[]
    fileCount?: number
    remotePath?: string
    localPath?: string
  } | null
  safeError: string | null
}

export interface RemoteBackup {
  fileName: string
  sizeBytes: number
}

export interface RemoteBackupsResponse {
  backups: RemoteBackup[]
}

export interface RestorePreview {
  restoreSessionId: string
  fileName?: string
  createdAt: string | null
  lumiVersion: string | null
  lumiDbSchemaVersion: number
  currentDbSchemaVersion: number
  compatible: boolean
  components: string[]
  files: { path: string; size: number }[]
  excludedSecrets: string[]
  secretConfigured: boolean
}

export interface RestoreResult {
  lumiRestored: boolean
  freshrss: 'not_included' | 'offline_restore_required'
  safetyBackupId: string | null
  freshrssStagedAt?: string
  health: { sqlite: string }
}
