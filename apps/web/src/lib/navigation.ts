/** navigation — ContentScope / buildEntryQuery（0011 阻断修复 §10/§15/§18）。
 *
 * 四级 Scope（全部信息源 → 全部 RSS → RSS 分类 → 单个 Feed）统一为一个
 * 判别联合，替代 selectedFeedUrl boolean soup；RSS 订阅与全部信息源语义
 * 独立（scope.kind='rss' 的 query 显式携带 sourceType=rss，即使当前系统
 * 全部条目恰好都是 RSS——§51）。
 *
 * buildEntryQuery：NavigationTarget → Entry API query 的唯一集中映射
 * （§18：Sidebar/EntryList/MobileHeader 不各写一份判断）。
 *   all      → 无 source 过滤
 *   rss      → sourceType=rss（BFF 契约，服务端语义）
 *   category → sourceType=rss + categoryId（greader label stream，服务端过滤）
 *   feed     → feedUrl（既有服务端过滤）
 *   readLater → view=all 全量拉取 + 客户端 marker 过滤（本地 sidecar，§31）
 *   favorites → view=starred（既有）
 *
 * Query key 统一含 scope（§19）：不同 scope 不同 cache，切换不闪旧数据。 */

import type { EntryView } from '../api/types'

export type { UiView } from './read-later'

/** 内容范围（§15）：与 Layout 展开状态（rssTreeExpanded 等）完全分离。 */
export type ContentScope =
  | { kind: 'all' }
  | { kind: 'rss' }
  | { kind: 'rss-category'; categoryId: string; categoryLabel: string }
  | { kind: 'rss-feed'; feedUrl: string }

/** §5 注：FreshRSS greader 模型一个 feed 只有一个 category（多分类不存在，
 * 已在最终报告说明该上游限制）。 */

/** Entry query 参数（client.getEntries 的入参形状）。 */
export interface EntryQuery {
  view: EntryView
  feedUrl: string | null
  sourceType: string | null
  categoryId: string | null
}

/** NavigationTarget → Entry API query（§18 唯一映射；纯函数可单测）。 */
export function buildEntryQuery(
  scope: ContentScope,
  view: 'all' | 'unread' | 'starred' | 'read-later',
): EntryQuery {
  // read-later 是本地 workspace：API 拉全量，列表侧客户端 marker 过滤
  const apiView: EntryView = view === 'read-later' ? 'all' : view
  switch (scope.kind) {
    case 'all':
      return { view: apiView, feedUrl: null, sourceType: null, categoryId: null }
    case 'rss':
      // §51：显式 sourceType=rss——未来加入 Email 后不会自动混入
      return { view: apiView, feedUrl: null, sourceType: 'rss', categoryId: null }
    case 'rss-category':
      return {
        view: apiView,
        feedUrl: null,
        sourceType: 'rss',
        categoryId: scope.categoryId,
      }
    case 'rss-feed':
      return { view: apiView, feedUrl: scope.feedUrl, sourceType: null, categoryId: null }
  }
}

/** Query key 的 scope 段（§19）：结构稳定、不同 scope 必然不同。 */
export function scopeKey(scope: ContentScope): string | { categoryId: string } | { feedUrl: string } {
  switch (scope.kind) {
    case 'all':
      return 'all'
    case 'rss':
      return 'rss'
    case 'rss-category':
      return { categoryId: scope.categoryId }
    case 'rss-feed':
      return { feedUrl: scope.feedUrl }
  }
}

/** Scope 显示标题（Mobile Header / 列表头共用）。 */
export function scopeTitle(scope: ContentScope): string {
  switch (scope.kind) {
    case 'all':
      return '全部信息源'
    case 'rss':
      return 'RSS 订阅'
    case 'rss-category':
      return scope.categoryLabel
    case 'rss-feed':
      return '订阅源' // feed 标题由调用方用 feeds 数据补全（见 MobileHeader）
  }
}
