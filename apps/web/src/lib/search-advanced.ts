/** search-advanced — F27 日期范围 / F29 高级条件（仅标题/精确短语/排除词）
 * 的参数类型、URL 构造与请求函数（纯逻辑 + 薄 fetch 包装）。
 *
 * 为什么不走 api/client.searchEntries：BFF /search 已支持 from/to，但
 * client.ts 尚未暴露 intitle/phrase/exclude；client.ts 属禁改文件，
 * 故在本模块自带一个同构 fetch（API_BASE 与 client.ts 的私有常量保持
 * 一致 '/api/v1'；仅访问相对路径，同源由 Vite 代理 / Caddy 反代承担）。
 * 后续 client.ts 收录这三个参数后应迁移回去（登记为合同缺口）。
 *
 * 日期语义：from/to 为本地时区的 YYYY-MM-DD 日期串（from = 该日 00:00
 * 起、to = 该日末尾止，inclusive 由服务端解释）。
 * 库腿：高级/日期模式只推进 RSS 腿（cursor），不消费 library 字段——
 * UI 侧诚实标注「高级筛选仅覆盖 RSS 结果」。
 *
 * 响应形状与 SearchResponse 同构（类型从 ../api/types 引用），分页
 * nextCursor/hasMore 语义与既有搜索一致（cursor opaque 原样透传）。 */

import type { SearchResponse } from '../api/types'

/** 与 api/client.ts 内部 API_BASE 一致（client.ts 未导出该常量）。 */
const API_BASE = '/api/v1'

/** F27 快捷范围种类（custom 由面板日期输入直接给出起止）。 */
export type QuickDateRangeKind = 'today' | '7d' | '30d'

/** 日期范围（YYYY-MM-DD；from/to 可只填其一）。 */
export interface DateRangeFilter {
  from: string | null
  to: string | null
}

/** F29 高级文本条件（全部可选；空串视为未填）。 */
export interface AdvancedTextFilter {
  intitle: string
  phrase: string
  exclude: string
}

export const EMPTY_ADVANCED_FILTER: AdvancedTextFilter = {
  intitle: '',
  phrase: '',
  exclude: '',
}

/** 本地时区日期 → YYYY-MM-DD（input[type=date] 与服务端共用格式）。 */
export function toLocalDateString(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** 快捷范围 → 日期区间（含当天；近 N 天 = 含今天的 N 天窗口）。 */
export function quickRange(
  kind: QuickDateRangeKind,
  now: Date = new Date(),
): DateRangeFilter {
  const to = toLocalDateString(now)
  if (kind === 'today') return { from: to, to }
  const days = kind === '7d' ? 7 : 30
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - (days - 1))
  return { from: toLocalDateString(start), to }
}

/** 是否填了至少一个高级文本条件。 */
export function hasAdvancedText(filter: AdvancedTextFilter | null | undefined): boolean {
  if (filter === null || filter === undefined) return false
  return (
    filter.intitle.trim() !== '' || filter.phrase.trim() !== '' || filter.exclude.trim() !== ''
  )
}

/** 是否处于「高级/日期查询」模式（任一条件存在即切换到专用查询）。 */
export function isAdvancedSearchActive(
  range: DateRangeFilter | null,
  advanced: AdvancedTextFilter | null,
): boolean {
  const rangeActive =
    range !== null && ((range.from !== null && range.from !== '') || (range.to !== null && range.to !== ''))
  return rangeActive || hasAdvancedText(advanced)
}

export interface AdvancedSearchParams {
  q: string
  /** RSS 腿 opaque cursor：原样透传，绝不 decode/parse。 */
  cursor?: string | null
  limit?: number
  feedUrl?: string | null
  categoryId?: string | null
  state?: 'unread' | null
  favorite?: boolean | null
  from?: string | null
  to?: string | null
  intitle?: string | null
  phrase?: string | null
  exclude?: string | null
  /** F017：仅摘要有/无维度（true=有摘要；false=无摘要；null=不过滤）。 */
  hasSummary?: boolean | null
}

/** 构造 /api/v1/search 请求 URL（导出供测试断言参数）。 */
export function buildAdvancedSearchUrl(params: AdvancedSearchParams): string {
  const query = new URLSearchParams()
  query.set('q', params.q)
  if (params.cursor != null) query.set('cursor', params.cursor)
  if (params.limit != null) query.set('limit', String(params.limit))
  if (params.feedUrl != null) query.set('feedUrl', params.feedUrl)
  if (params.categoryId != null) query.set('categoryId', params.categoryId)
  if (params.state != null) query.set('state', params.state)
  if (params.favorite != null) query.set('favorite', params.favorite ? 'true' : 'false')
  if (params.from != null) query.set('from', params.from)
  if (params.to != null) query.set('to', params.to)
  if (params.intitle != null && params.intitle !== '') query.set('intitle', params.intitle)
  if (params.phrase != null && params.phrase !== '') query.set('phrase', params.phrase)
  if (params.exclude != null && params.exclude !== '') query.set('exclude', params.exclude)
  if (params.hasSummary != null) query.set('hasSummary', params.hasSummary ? 'true' : 'false')
  return `${API_BASE}/search?${query}`
}

export interface BuilderFilters {
  /** 来源（feedUrl）；null = 全部来源。 */
  sourceFeedUrl: string | null
  unread: boolean | null
  favorite: boolean | null
  hasSummary: boolean | null
}

export const EMPTY_BUILDER_FILTERS: BuilderFilters = {
  sourceFeedUrl: null,
  unread: null,
  favorite: null,
  hasSummary: null,
}

/** 是否至少启用了一个构建器维度。 */
export function hasBuilderFilters(f: BuilderFilters): boolean {
  return (
    f.sourceFeedUrl !== null || f.unread !== null || f.favorite !== null || f.hasSummary !== null
  )
}

/** F017：生成的查询语义（人类可读；用于面板确认与保存意图说明）。 */
export function describeAdvancedQuery(opts: {
  q: string
  sourceLabel?: string | null
  unread?: boolean | null
  favorite?: boolean | null
  hasSummary?: boolean | null
  intitle?: string | null
  phrase?: string | null
  exclude?: string | null
  from?: string | null
  to?: string | null
}): string {
  const parts: string[] = [`搜索「${opts.q}」`]
  if (opts.sourceLabel) parts.push(`来源=${opts.sourceLabel}`)
  if (opts.unread) parts.push('未读')
  if (opts.favorite) parts.push('收藏')
  if (opts.hasSummary === true) parts.push('有摘要')
  if (opts.hasSummary === false) parts.push('无摘要')
  if (opts.intitle) parts.push(`标题含「${opts.intitle}」`)
  if (opts.phrase) parts.push(`短语「${opts.phrase}」`)
  if (opts.exclude) parts.push(`排除「${opts.exclude}」`)
  if (opts.from) parts.push(`自 ${opts.from}`)
  if (opts.to) parts.push(`至 ${opts.to}`)
  return parts.join(' AND ')
}

/** 把非 2xx 响应转成 Error（容错 BFF error envelope；与 client.toApiError
 * 同语义——UI 只显示 message，绝不透出原始响应体）。 */
async function toSearchError(response: Response): Promise<Error> {
  let message = `请求失败（HTTP ${response.status}），请稍后重试。`
  try {
    const body: unknown = await response.json()
    if (
      typeof body === 'object' &&
      body !== null &&
      'error' in body &&
      typeof (body as { error?: { message?: unknown } }).error?.message === 'string'
    ) {
      message = (body as { error: { message: string } }).error.message
    }
  } catch {
    // 非 JSON 错误页 → 使用安全 fallback
  }
  return new Error(message)
}

/** 高级搜索请求（GET /api/v1/search + intitle/phrase/exclude 扩展参数）。
 * AbortError 原样上抛（TanStack Query cancellation 契约）。 */
export async function searchEntriesAdvanced(
  params: AdvancedSearchParams,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  let response: Response
  try {
    response = await fetch(buildAdvancedSearchUrl(params), { signal })
  } catch (error) {
    if (
      typeof error === 'object' &&
      error !== null &&
      (error as { name?: unknown }).name === 'AbortError'
    ) {
      throw error
    }
    throw new Error('无法连接到服务器，请稍后重试。')
  }
  if (!response.ok) {
    throw await toSearchError(response)
  }
  return (await response.json()) as SearchResponse
}
