/** search-insight — N142/N143/N145/N147/N141/N149 搜索理解与排障的取数层
 * （纯逻辑 + 薄 fetch 包装）。
 *
 * 取数位置：快照（N141）/时间线（N149）与既有 N142-N147 端点同居本
 * 模块——同一 DistributionParams 口径复用，自带同构 fetch（API_BASE =
 * '/api/v1'，仅相对路径，同源由 Vite 代理 / Caddy 反代承担）；域内
 * 邻接端点（标签合并撤销 N150、保存视图范围 N144）则收录于
 * api/client.ts，与其既有函数并列。
 *
 * 诚实口径：
 * - parse-query 的 unrecognized 原样透传（服务端已保证不静默丢弃）；
 * - why-missed 的 reasons / rank / rankCapped 原样透传（不编造结论）；
 * - distribution 只含 SQL 聚合计数（服务端不回传正文）；
 * - snapshot compare 的 added/removed/rankChanges/permissionLost 原样
 *   透传（complete=false 时不冒充完整）；
 * - timeline 的月份计数与批注列表原样透传（annotationsComplete=false
 *   诚实标注截断）。
 */

import type {
  SearchDistributionResult,
  SearchParseResult,
  SearchSnapshotCompareResult,
  SearchSnapshotList,
  SearchSnapshotView,
  SearchTimelineResult,
  SearchWhyMissedResult,
} from '../api/types'

/** 与 api/client.ts 内部 API_BASE 一致（client.ts 未导出该常量）。 */
const API_BASE = '/api/v1'

/** 把非 2xx 响应转成 Error（容错 BFF error envelope；与
 * search-advanced.toSearchError 同语义）。AbortError 原样上抛。 */
async function toInsightError(response: Response): Promise<Error> {
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

async function insightFetch(url: string, init: RequestInit, signal?: AbortSignal): Promise<Response> {
  let response: Response
  try {
    response = await fetch(url, { ...init, signal })
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
    throw await toInsightError(response)
  }
  return response
}

// ---- N142 自然语言转过滤条件 -------------------------------------------------

/** POST /api/v1/search/parse-query（纯规则，无模型调用）。 */
export async function parseSearchQuery(
  query: string,
  signal?: AbortSignal,
): Promise<SearchParseResult> {
  const response = await insightFetch(
    `${API_BASE}/search/parse-query`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    },
    signal,
  )
  return (await response.json()) as SearchParseResult
}

// ---- N143 为什么没命中 -------------------------------------------------------

export interface WhyMissedParams {
  query: string
  entryRef: string
  feedUrl?: string | null
  categoryId?: string | null
  state?: 'unread' | null
  favorite?: boolean | null
  from?: string | null
  to?: string | null
  intitle?: string | null
  phrase?: string | null
  exclude?: string | null
  hasSummary?: boolean | null
}

/** POST /api/v1/search/why-missed（own-scope：他人条目 → 404）。 */
export async function whyMissed(
  params: WhyMissedParams,
  signal?: AbortSignal,
): Promise<SearchWhyMissedResult> {
  const response = await insightFetch(
    `${API_BASE}/search/why-missed`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: params.query,
        entryRef: params.entryRef,
        feedUrl: params.feedUrl ?? null,
        categoryId: params.categoryId ?? null,
        state: params.state ?? null,
        favorite: params.favorite ?? false,
        from: params.from ?? null,
        to: params.to ?? null,
        intitle: params.intitle ?? null,
        phrase: params.phrase ?? null,
        exclude: params.exclude ?? null,
        hasSummary: params.hasSummary ?? null,
      }),
    },
    signal,
  )
  return (await response.json()) as SearchWhyMissedResult
}

// ---- N145 来源内搜索分布 -----------------------------------------------------

export interface DistributionParams {
  q: string
  feedUrl?: string | null
  categoryId?: string | null
  state?: 'unread' | null
  favorite?: boolean | null
  from?: string | null
  to?: string | null
  intitle?: string | null
  phrase?: string | null
  exclude?: string | null
  hasSummary?: boolean | null
}

/** 构造 distribution 请求 URL（导出供测试断言参数；与
 * buildAdvancedSearchUrl 同一省略口径）。 */
export function buildDistributionUrl(params: DistributionParams): string {
  const query = new URLSearchParams()
  query.set('q', params.q)
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
  return `${API_BASE}/search/distribution?${query}`
}

/** GET /api/v1/search/distribution（SQL 聚合；无正文出站）。 */
export async function fetchDistribution(
  params: DistributionParams,
  signal?: AbortSignal,
): Promise<SearchDistributionResult> {
  const response = await insightFetch(buildDistributionUrl(params), {}, signal)
  return (await response.json()) as SearchDistributionResult
}

// ---- N141 搜索快照比较 -------------------------------------------------------

/** POST /api/v1/search/snapshots（冻结当前结果引用；≤2000 诚实截断）。 */
export async function createSearchSnapshot(
  params: DistributionParams,
  signal?: AbortSignal,
): Promise<SearchSnapshotView> {
  const response = await insightFetch(
    `${API_BASE}/search/snapshots`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        q: params.q,
        feedUrl: params.feedUrl ?? null,
        categoryId: params.categoryId ?? null,
        state: params.state ?? null,
        favorite: params.favorite ?? false,
        from: params.from ?? null,
        to: params.to ?? null,
        intitle: params.intitle ?? null,
        phrase: params.phrase ?? null,
        exclude: params.exclude ?? null,
        hasSummary: params.hasSummary ?? null,
      }),
    },
    signal,
  )
  return (await response.json()) as SearchSnapshotView
}

/** GET /api/v1/search/snapshots（有界列表：引用计数而非引用清单）。 */
export async function fetchSearchSnapshots(
  signal?: AbortSignal,
): Promise<SearchSnapshotList> {
  const response = await insightFetch(`${API_BASE}/search/snapshots`, {}, signal)
  return (await response.json()) as SearchSnapshotList
}

/** POST /api/v1/search/snapshots/{id}/compare（对存储作用域原样复跑）。 */
export async function compareSearchSnapshot(
  snapshotId: string,
  signal?: AbortSignal,
): Promise<SearchSnapshotCompareResult> {
  const response = await insightFetch(
    `${API_BASE}/search/snapshots/${encodeURIComponent(snapshotId)}/compare`,
    { method: 'POST' },
    signal,
  )
  return (await response.json()) as SearchSnapshotCompareResult
}

// ---- N149 主题演变时间线 -----------------------------------------------------

/** 构造 timeline 请求 URL（与 distribution 完全同参，仅端点不同）。 */
export function buildTimelineUrl(params: DistributionParams): string {
  return `${buildDistributionUrl(params).replace('/search/distribution', '/search/timeline')}`
}

/** GET /api/v1/search/timeline（24 个月逐月计数 + 本人批注，≤10 条）。 */
export async function fetchSearchTimeline(
  params: DistributionParams,
  signal?: AbortSignal,
): Promise<SearchTimelineResult> {
  const response = await insightFetch(buildTimelineUrl(params), {}, signal)
  return (await response.json()) as SearchTimelineResult
}
