/** NEW-281..290 日报、简报与周期阅读 — 本组专属 API 调用（独立文件，
 * 不触碰共享 client.ts；URL 全部相对 /api/v1/*，与 client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new28*.py；类型按 BFF
 * 稳定 DTO 手写（本组端点尚未进 OpenAPI 生成集——诚实注释，不假装
 * generated）。 */

const API_BASE = '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly errorType: string
  readonly payload: Record<string, unknown>

  constructor(status: number, errorType: string, message: string, payload: Record<string, unknown>) {
    super(message)
    this.status = status
    this.errorType = errorType
    this.payload = payload
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let errorType = 'request_failed'
  let message = `请求失败（${response.status}）`
  let payload: Record<string, unknown> = {}
  try {
    const body = (await response.json()) as { error?: { type?: string; message?: string } }
    if (body.error?.type) errorType = body.error.type
    if (body.error?.message) message = body.error.message
    payload = (body.error ?? {}) as Record<string, unknown>
  } catch {
    // 非 JSON 错误体：保留状态码信息
  }
  return new ApiError(response.status, errorType, message, payload)
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

async function sendJson<T>(
  path: string,
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return null as T
  return (await response.json()) as T
}

// ---- 共享 DTO ------------------------------------------------------------

export interface CandidateCard {
  entryRef: string
  itemId: string
  title: string
  feedTitle: string
  feedUrl: string
  url: string
  publishedAt: string
  starred: boolean
  excerpt: string
  seenInIssues: { issueId: string; issueTitle: string; confirmedAt: string }[]
}

export interface BriefingItem {
  id: string
  entryRef: string
  title: string
  feedTitle: string
  url: string
  publishedAt: string
  excerpt: string
  sectionKey: string
  position: number
  provenance: 'manual' | 'rule'
  provenanceLabel: string
  pulledBack: boolean
}

export interface BriefingSection {
  key: string
  label: string
}

export interface Briefing {
  id: string
  title: string
  status: 'draft' | 'confirmed'
  rangeFrom: string
  rangeTo: string
  source: string
  sections: BriefingSection[]
  items: BriefingItem[]
  confirmedAt: string | null
}

export interface BriefingSummary {
  id: string
  title: string
  status: 'draft' | 'confirmed'
  confirmedAt: string | null
  itemCount: number
}

// ---- NEW-281 编排台 --------------------------------------------------------

export async function fetchCandidates(
  from: string,
  to: string,
  feedUrl: string,
  signal?: AbortSignal,
): Promise<{ candidates: CandidateCard[]; count: number }> {
  const params = new URLSearchParams({ from, to })
  if (feedUrl) params.set('feedUrl', feedUrl)
  return getJson(`${API_BASE}/briefings/candidates?${params.toString()}`, signal)
}

export async function createBriefing(body: {
  title: string
  rangeFrom: string
  rangeTo: string
  sections: { key: string; label: string }[]
  items: {
    entryRef: string
    sectionKey: string
    title: string
    feedTitle?: string
    url?: string
    publishedAt?: string
    excerpt?: string
    provenance?: 'manual' | 'rule'
    pullBack?: boolean
    dupDecision?: 'include' | 'defer' | 'skip'
  }[]
}): Promise<Briefing> {
  return sendJson(`${API_BASE}/briefings`, 'POST', body)
}

export async function listBriefings(signal?: AbortSignal): Promise<{ issues: BriefingSummary[]; count: number }> {
  return getJson(`${API_BASE}/briefings`, signal)
}

export async function confirmBriefing(issueId: string): Promise<Briefing> {
  return sendJson(`${API_BASE}/briefings/${issueId}/confirm`, 'POST')
}

// ---- NEW-282 去重审批 ------------------------------------------------------

export interface Followup {
  entryRef: string
  title: string
  feedTitle: string
  priorIssue: string
  deferredAt: string
}

export async function fetchFollowups(signal?: AbortSignal): Promise<{ followups: Followup[]; count: number }> {
  return getJson(`${API_BASE}/briefings/followups`, signal)
}

// ---- NEW-283 截稿窗口 ------------------------------------------------------

export interface BriefingWindow {
  configured: boolean
  timezone?: string
  cutoffTime?: string
  periodDays?: number
  startUtc?: string
  cutoffUtc?: string
  nextWindowStartUtc?: string
}

export async function fetchWindow(signal?: AbortSignal): Promise<BriefingWindow> {
  return getJson(`${API_BASE}/briefings/window`, signal)
}

export async function putWindow(timezone: string, cutoffTime: string, periodDays: number): Promise<BriefingWindow> {
  return sendJson(`${API_BASE}/briefings/window`, 'PUT', { timezone, cutoffTime, periodDays })
}

// ---- NEW-284 缺刊诊断 ------------------------------------------------------

export interface MissingInput {
  field: string
  reason: string
}

export interface GenerationAttempt {
  id: string
  stage: string
  status: 'failed' | 'ok'
  missing: MissingInput[]
  detail: string
  createdAt: string
}

export async function generateBriefing(body: {
  recipeId?: string
  rangeFrom?: string
  rangeTo?: string
}): Promise<{ issue: Briefing; excludedLate: number }> {
  return sendJson(`${API_BASE}/briefings/generate`, 'POST', body)
}

export async function listAttempts(signal?: AbortSignal): Promise<{
  attempts: GenerationAttempt[]
  count: number
  honestyNote: string
}> {
  return getJson(`${API_BASE}/briefings/attempts`, signal)
}

// ---- NEW-285 RSS 发布 ------------------------------------------------------

export interface FeedState {
  enabled: boolean
  createdAt: string | null
  rotatedAt: string | null
  revokedAt: string | null
}

export async function fetchFeedState(signal?: AbortSignal): Promise<FeedState> {
  return getJson(`${API_BASE}/briefings/feed`, signal)
}

export async function enableFeed(): Promise<{ token: string; path: string; note: string }> {
  return sendJson(`${API_BASE}/briefings/feed/enable`, 'POST')
}

export async function rotateFeed(): Promise<{ token: string; path: string; note: string }> {
  return sendJson(`${API_BASE}/briefings/feed/rotate`, 'POST')
}

export async function revokeFeed(): Promise<null> {
  return sendJson(`${API_BASE}/briefings/feed/revoke`, 'POST')
}

// ---- NEW-286 栏目配方 ------------------------------------------------------

export interface RecipeSection {
  key: string
  label: string
  rule: 'starred' | 'recent' | 'feed'
  budget: number
  feedUrl: string
}

export interface Recipe {
  id: string
  name: string
  sections: RecipeSection[]
}

export async function listRecipes(signal?: AbortSignal): Promise<{ recipes: Recipe[]; count: number }> {
  return getJson(`${API_BASE}/briefings/recipes`, signal)
}

export async function createRecipe(name: string, sections: RecipeSection[]): Promise<Recipe> {
  return sendJson(`${API_BASE}/briefings/recipes`, 'POST', { name, sections })
}

export async function deleteRecipe(recipeId: string): Promise<null> {
  return sendJson(`${API_BASE}/briefings/recipes/${recipeId}`, 'DELETE')
}

export async function applyRecipe(issueId: string, recipeId: string): Promise<Briefing & { droppedItems: number }> {
  return sendJson(`${API_BASE}/briefings/${issueId}/apply-recipe`, 'POST', { recipeId })
}

// ---- NEW-287 人工精选标记 --------------------------------------------------

export async function fetchSuggestions(
  from: string,
  to: string,
  rule: 'starred' | 'recent' | 'feed',
  feedUrl: string,
  signal?: AbortSignal,
): Promise<{ suggestions: (CandidateCard & { provenance: string; provenanceLabel: string })[]; count: number }> {
  const params = new URLSearchParams({ from, to, rule })
  if (feedUrl) params.set('feedUrl', feedUrl)
  return getJson(`${API_BASE}/briefings/suggestions?${params.toString()}`, signal)
}

export async function flipProvenance(issueId: string, itemId: string, provenance: 'manual' | 'rule'): Promise<Briefing> {
  return sendJson(`${API_BASE}/briefings/${issueId}/items/${itemId}/provenance`, 'PATCH', { provenance })
}

// ---- NEW-288 跨期主题 ------------------------------------------------------

export interface TopicSummary {
  id: string
  name: string
  entryCount: number
}

export interface TopicEntry {
  entryRef: string
  itemId: string
  briefingId: string
  issueTitle: string
  issueStatus: string
  issueConfirmedAt: string | null
  title: string
  feedTitle: string
  url: string
  excerpt: string
  position: number
}

export async function listTopics(signal?: AbortSignal): Promise<{ topics: TopicSummary[]; count: number }> {
  return getJson(`${API_BASE}/briefings/topics`, signal)
}

export async function createTopic(name: string): Promise<{ id: string; name: string; created: boolean }> {
  return sendJson(`${API_BASE}/briefings/topics`, 'POST', { name })
}

export async function fetchTopicChain(topicId: string, signal?: AbortSignal): Promise<{
  id: string
  name: string
  entries: TopicEntry[]
  honestyNote: string
}> {
  return getJson(`${API_BASE}/briefings/topics/${topicId}`, signal)
}

export async function attachTopicEntry(topicId: string, briefingId: string, itemId: string): Promise<{ attached: boolean }> {
  return sendJson(`${API_BASE}/briefings/topics/${topicId}/entries`, 'POST', { briefingId, itemId })
}

// ---- NEW-289 EML 导出 ------------------------------------------------------

/** 导出确认为 EML 文件（浏览器下载；绝不发送邮件）。 */
export async function exportEml(issueId: string): Promise<{ filename: string; size: number }> {
  const response = await fetch(`${API_BASE}/briefings/${issueId}/export.eml`)
  if (!response.ok) throw await toApiError(response)
  const disposition = response.headers.get('content-disposition') ?? ''
  const match = /filename="([^"]+)"/.exec(disposition)
  const filename = match?.[1] ?? `briefing-${issueId.slice(0, 8)}.eml`
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
  return { filename, size: blob.size }
}

// ---- NEW-290 历史更正 ------------------------------------------------------

export interface Correction {
  id: string
  briefingId: string
  body: string
  createdAt: string
}

export async function listCorrections(
  issueId: string,
  signal?: AbortSignal,
): Promise<{ corrections: Correction[]; count: number; honestyNote: string }> {
  return getJson(`${API_BASE}/briefings/${issueId}/corrections`, signal)
}

export async function addCorrection(issueId: string, body: string): Promise<Correction> {
  return sendJson(`${API_BASE}/briefings/${issueId}/corrections`, 'POST', { body })
}
