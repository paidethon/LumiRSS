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

/** GET/PUT /api/v1/settings/ai（0015）——浏览器安全视图：
 * configured 只报告服务端是否配置了 API key；key 本身永不下发。 */
export interface AiSettings {
  provider: 'openai_compatible'
  baseUrl: string
  model: string
  summaryLanguage: 'zh-CN' | 'en'
  configured: boolean
}

/** PUT /api/v1/settings/ai body（0015）：只含非机密字段，可部分更新。 */
export interface AiSettingsUpdate {
  baseUrl?: string
  model?: string
  summaryLanguage?: 'zh-CN' | 'en'
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
