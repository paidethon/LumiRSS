/** NEW-201..210 来源运维工作台 —— API 客户端（组内唯一入口）。
 *
 * 与 api/client.ts 同形契约：非 2xx → ApiError 形态错误（取服务端
 * error.message）；类型对齐各 new2xx 路由的 OpenAPI 模型。shared-wiring
 * 纪律：本文件是新文件，queries.ts 不改——hooks 在本目录内联使用。 */

export class OpsApiError extends Error {
  readonly status: number
  readonly type: string

  constructor(status: number, type: string, message: string) {
    super(message)
    this.status = status
    this.type = type
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers:
      init?.body !== undefined
        ? { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }
        : init?.headers,
  })
  if (!response.ok) {
    let type = 'unknown_error'
    let message = `请求失败（${response.status}）`
    try {
      const body = (await response.json()) as { error?: { type?: string; message?: string } }
      type = body.error?.type ?? type
      message = body.error?.message ?? message
    } catch {
      // 非 JSON 错误体：保留默认文案
    }
    throw new OpsApiError(response.status, type, message)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const post = <T,>(path: string, body: unknown): Promise<T> =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) })

// ---- NEW-210 停机计划 ----

export interface PausePlan {
  id: string
  feedUrl: string
  reason: string | null
  startAt: string
  endAt: string | null
  status: string
  activeNow: boolean
}

export const createPausePlan = (input: {
  feedUrl: string
  startAt?: string
  endAt?: string
  openEnded?: boolean
  reason?: string
}) => post<PausePlan>('/api/v1/new210/pauses', input)

export const listPausePlans = () =>
  request<{ items: PausePlan[]; note: string }>('/api/v1/new210/pauses')

export const cancelPausePlan = (id: string) =>
  post<PausePlan>(`/api/v1/new210/pauses/${encodeURIComponent(id)}/cancel`, {})

// ---- NEW-208 认证到期提醒 ----

export interface CredentialReminder {
  id: string
  feedUrl: string
  sourceLabel: string | null
  expiresOn: string
  note: string | null
  status: string
  renewedCount: number
  bucket: string | null
  updateEntry: string | null
}

export const createReminder = (input: { feedUrl: string; expiresOn: string; note?: string }) =>
  post<CredentialReminder>('/api/v1/new208/reminders', input)

export const listReminders = (today?: string) =>
  request<{ items: CredentialReminder[]; note: string }>(
    today ? `/api/v1/new208/reminders?today=${encodeURIComponent(today)}` : '/api/v1/new208/reminders',
  )

export const renewReminder = (id: string, expiresOn: string) =>
  post<CredentialReminder>(`/api/v1/new208/reminders/${encodeURIComponent(id)}/renew`, { expiresOn })

export const dismissReminder = (id: string) =>
  post<CredentialReminder>(`/api/v1/new208/reminders/${encodeURIComponent(id)}/dismiss`, {})

// ---- NEW-209 回收箱 ----

export interface BinRow {
  id: string
  feedUrl: string
  title: string | null
  categoryLabel: string | null
  keepDays: number
  purgeAfter: string
  status: string
  expired: boolean
}

export const unsubscribeToBin = (input: { subscriptionRef: string; keepDays: number }) =>
  post<BinRow>('/api/v1/new209/unsubscribe', input)

export const listBin = () =>
  request<{ items: BinRow[]; note: string }>('/api/v1/new209/bin')

export const restoreBinRow = (id: string) =>
  post<BinRow>(`/api/v1/new209/bin/${encodeURIComponent(id)}/restore`, {})

export const discardBinRow = (id: string) =>
  post<BinRow>(`/api/v1/new209/bin/${encodeURIComponent(id)}/discard`, {})

// ---- NEW-202 停更观察 ----

export interface Observation {
  id: string
  feedUrl: string
  note: string | null
  startedAt: string
  endsAt: string
  status: string
  resolution: string | null
  lastPostAt: string | null
  postsSinceStart: number
  fetchHealth: string | null
  verdict: string | null
  fetchPaused: boolean
  expired: boolean
}

export const createObservation = (input: { feedUrl: string; days: number; note?: string }) =>
  post<Observation>('/api/v1/new202/observations', input)

export const listObservations = (status: 'active' | 'closed' | 'all' = 'active') =>
  request<{ items: Observation[] }>(`/api/v1/new202/observations?status=${status}`)

export const extendObservation = (id: string, days: number) =>
  post<Observation>(`/api/v1/new202/observations/${encodeURIComponent(id)}/extend`, { days })

export const closeObservation = (id: string, resolution: 'continue' | 'unsubscribed') =>
  post<Observation>(`/api/v1/new202/observations/${encodeURIComponent(id)}/close`, { resolution })

// ---- NEW-206 阅读日历 ----

export interface CalendarDay {
  date: string
  count: number
  sample: { entryRef: string; title: string; publishedAt: string }[]
}

export interface CalendarView {
  feedUrl: string
  month: string
  days: CalendarDay[]
  totalEntries: number
  coverage: string
  fetchPaused: boolean
  note: string
}

export const getFeedCalendar = (feedUrl: string, month: string) =>
  request<CalendarView>(
    `/api/v1/new206/calendar?feedUrl=${encodeURIComponent(feedUrl)}&month=${encodeURIComponent(month)}`,
  )

// ---- NEW-203 分流视图 ----

export interface SourceView {
  id: string
  feedUrl: string
  name: string
  field: string
  value: string
}

export const createView = (input: { feedUrl: string; name: string; field: string; value: string }) =>
  post<SourceView>('/api/v1/new203/views', input)

export const listViews = (feedUrl?: string) =>
  request<{ items: SourceView[] }>(
    feedUrl ? `/api/v1/new203/views?feedUrl=${encodeURIComponent(feedUrl)}` : '/api/v1/new203/views',
  )

export const deleteView = (id: string) =>
  request<void>(`/api/v1/new203/views/${encodeURIComponent(id)}`, { method: 'DELETE' })

export interface ViewEntry {
  entryRef: string
  title: string
  author: string
  publishedAt: string
}

export const getViewEntries = (id: string) =>
  request<{ view: SourceView; entries: ViewEntry[]; note: string }>(
    `/api/v1/new203/views/${encodeURIComponent(id)}/entries`,
  )

// ---- NEW-205 保留策略 ----

export interface RetentionDryRun {
  feedUrl: string
  retentionDays: number
  preserved: { starredEntries: number; annotations: number; libraryBookmarks: number }
  reclaimed: { prunableEntries: number; cutoff: string }
  totalEntries: number
  note: string
}

export const retentionDryRun = (input: { feedUrl: string; days: number }) =>
  post<RetentionDryRun>('/api/v1/new205/retention/dry-run', input)

export const retentionEnable = (input: { feedUrl: string; days: number; confirmed: boolean }) =>
  post<{ enabled: boolean; pruned: number }>('/api/v1/new205/retention/enable', input)

// ---- NEW-201 接管向导 ----

export interface TakeoverPlan {
  toSubscribe: { feedUrl: string; title: string; categoryLabel: string | null }[]
  alreadySubscribed: {
    feedUrl: string
    opmlCategory: string | null
    currentCategory: string | null
    categoryDiffers: boolean
    subscriptionRef: string | null
  }[]
  invalidCount: number
  exportedTotal: number
}

export const takeoverPreview = (opml: string) =>
  post<TakeoverPlan>('/api/v1/new201/takeover/preview', { opml })

export const takeoverApply = (input: {
  items: { action: string; feedUrl: string; title?: string; categoryLabel?: string }[]
  label?: string
}) =>
  post<{
    created: number
    skippedExisting: number
    moved: number
    failed: number
    results: { feedUrl: string; outcome: string }[]
  }>('/api/v1/new201/takeover/apply', input)

// ---- NEW-204 镜像比对 ----

export interface MirrorCompareResult {
  sideA: { title: string | null; entryCount: number | null; error: string | null }
  sideB: { title: string | null; entryCount: number | null; error: string | null }
  comparison: { commonCount: number; onlyACount: number; onlyBCount: number } | null
  note: string
}

export const mirrorCompare = (urlA: string, urlB: string) =>
  post<MirrorCompareResult>('/api/v1/new204/compare', { urlA, urlB })

export const recordMirrorChoice = (input: { urlA: string; urlB: string; picked: 'A' | 'B'; note?: string }) =>
  post<{ id: string }>('/api/v1/new204/choices', input)

// ---- NEW-207 RSSHub 参数表单 ----

export interface RssHubFormSchema {
  routeId: string
  title: string
  description: string
  pathTemplate: string
  parameters: {
    key: string
    label: string
    required: boolean
    pattern: string
    example: string
    help: string
  }[]
}

export const getRssHubFormSchema = (routeId: string) =>
  request<RssHubFormSchema>(`/api/v1/new207/rsshub-form/${encodeURIComponent(routeId)}`)

export const validateRssHubForm = (routeId: string, params: Record<string, string>) =>
  post<{ valid: boolean; errors: { key: string; code: string; message: string }[]; generatedPath?: string }>(
    `/api/v1/new207/rsshub-form/${encodeURIComponent(routeId)}/validate`,
    { params },
  )

export const applyRssHubForm = (
  routeId: string,
  input: { params: Record<string, string>; title?: string; confirmed: boolean },
) =>
  post<{ subscription: { feedUrl: string } }>(
    `/api/v1/new207/rsshub-form/${encodeURIComponent(routeId)}/apply`,
    input,
  )

export interface RssHubRouteOption {
  id: string
  title: string
}

export const listRssHubRoutes = () =>
  request<{ configured: boolean; routes: (RssHubRouteOption & { parameters: unknown[] })[] }>(
    '/api/v1/rsshub/routes',
  )
