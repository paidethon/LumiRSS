/** 与 BFF 真实契约一一对应的最小前端类型（docs/specs/0005-web-shell.md）。
 * 不添加后端不存在的字段。 */

export type EntryView = 'all' | 'unread' | 'starred'

export interface Feed {
  title: string
  feedUrl: string
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

export interface ApiErrorResponse {
  error: { type: string; message: string }
}
