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
