/** 与 BFF 真实契约一一对应的最小前端类型（docs/specs/0005-web-shell.md）。
 * 不添加后端不存在的字段。 */

export type EntryView = 'all' | 'unread' | 'starred'

/** FreshRSS 分类（0011：subscription/list 的 categories[0]，单分类模型）。
 * id 是稳定 key（user/-/label/<名>），label 是展示名。 */
export interface FeedCategory {
  id: string
  label: string
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
