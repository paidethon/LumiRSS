/** NEW-361..370 搜索表达、专题发现与回溯 — 本组专属 API 调用。
 *
 * 后端真源：services/bff/src/lumirss/routers/new361_*.py .. new370_*.py；
 * 类型按 BFF 稳定 DTO 手写（本组端点尚未进 OpenAPI 生成集——诚实
 * 注释，不假装 generated）。URL 全部相对 /api/v1/*。
 *
 * 语义红线（与 BFF 一致）：
 * - 361 分布只由实际命中生成；362/365 只有显式确认才入组/入查询；
 * - 368 只建议不自动替换；370 反馈默认不改排序，仅本人显式启用的方案生效。
 */

const API_BASE = '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly errorType: string

  constructor(status: number, errorType: string, message: string) {
    super(message)
    this.status = status
    this.errorType = errorType
  }
}

function messageOf(payload: unknown, fallback: string): string {
  if (payload !== null && typeof payload === 'object') {
    const candidate = payload as { error?: { message?: string } }
    if (candidate.error && typeof candidate.error.message === 'string') {
      return candidate.error.message
    }
  }
  return fallback
}

async function toApiError(response: Response): Promise<ApiError> {
  let text = ''
  try {
    text = await response.text()
  } catch {
    // 无响应体
  }
  let parsed: unknown = null
  try {
    parsed = text ? (JSON.parse(text) as unknown) : null
  } catch {
    // 非 JSON 错误体
  }
  if (parsed !== null && typeof parsed === 'object') {
    const error = (parsed as { error?: { type?: string; message?: string } }).error
    if (error && typeof error.type === 'string') {
      return new ApiError(response.status, error.type, messageOf(parsed, error.message ?? '请求失败'))
    }
  }
  return new ApiError(response.status, 'request_failed', messageOf(parsed, `请求失败（${response.status}）`))
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

async function sendJson<T>(
  path: string,
  method: 'POST' | 'PUT' | 'DELETE',
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

// ---- NEW-361 时间范围刷选 --------------------------------------------------

export interface BrushBucket {
  key: string
  count: number
}

export interface TimeBrushResult {
  buckets: BrushBucket[]
  total: number
  granularity: 'day' | 'month'
  dayFrom: string
  dayTo: string
  hint: string
}

export function fetchTimeBrush(params: {
  q: string
  from: string
  to: string
  author?: string | null
  feedUrl?: string | null
}): Promise<TimeBrushResult> {
  const search = new URLSearchParams({ q: params.q, from: params.from, to: params.to })
  if (params.author) search.set('author', params.author)
  if (params.feedUrl) search.set('feedUrl', params.feedUrl)
  return getJson(`${API_BASE}/search/time-brush?${search.toString()}`)
}

// ---- NEW-362 相似标题候选审阅 ----------------------------------------------

export interface SimilarTitleCandidate {
  entryRef: string
  title: string
  feedTitle: string
  publishedAt: string
  sameSource: boolean
  inGroup: string | null
  inGroupNote: string | null
  score: number
  sharedBigrams: number
  sharedSample: string
  totalBigrams: { a: number; b: number }
}

export interface SimilarTitleCandidatesResult {
  entry: { entryRef: string; title: string; feedTitle: string; publishedAt: string }
  candidates: SimilarTitleCandidate[]
  scanned: number
  scannedCapped: boolean
}

export function fetchSimilarTitleCandidates(entryRef: string): Promise<SimilarTitleCandidatesResult> {
  return getJson(
    `${API_BASE}/search/similar-title-candidates?entryRef=${encodeURIComponent(entryRef)}`,
  )
}

export interface ConfirmSimilarTitleResult {
  relation: {
    id: number
    srcRef: string
    dstRef: string
    kind: 'manual' | 'duplicate'
    note: string
    createdAt: string
  }
  explained: string
}

export function confirmSimilarTitle(
  aRef: string,
  bRef: string,
  relation: 'duplicate' | 'reprint',
): Promise<ConfirmSimilarTitleResult> {
  return sendJson(`${API_BASE}/search/similar-title-candidates/confirm`, 'POST', {
    aRef,
    bRef,
    relation,
  })
}

// ---- NEW-363 跨字段命中说明 -------------------------------------------------

export interface FieldHitItem {
  entryRef: string
  fields: string[]
  noteHit: { count: number; excerpt: string } | null
}

export interface FieldHitsResult {
  items: FieldHitItem[]
  missing: string[]
}

export function postFieldHits(query: string, entryRefs: string[]): Promise<FieldHitsResult> {
  return sendJson(`${API_BASE}/search/field-hits`, 'POST', { query, entryRefs })
}

// ---- NEW-364 作者与来源交叉筛选 ---------------------------------------------

export interface AuthorFacet {
  author: string
  count: number
}

export interface SourceFacet {
  feedUrl: string
  feedTitle: string
  count: number
}

export interface AuthorSourceFacets {
  total: number
  authors: AuthorFacet[]
  authorsComplete: boolean
  sources: SourceFacet[]
  sourcesComplete: boolean
  selected: { author: string | null; feedUrl: string | null }
  note: string
}

export function fetchAuthorSourceFacets(params: {
  q: string
  author?: string | null
  feedUrl?: string | null
}): Promise<AuthorSourceFacets> {
  const search = new URLSearchParams({ q: params.q })
  if (params.author) search.set('author', params.author)
  if (params.feedUrl) search.set('feedUrl', params.feedUrl)
  return getJson(`${API_BASE}/search/author-source?${search.toString()}`)
}

// ---- NEW-365 搜索排除词建议审批 ---------------------------------------------

export interface ExclusionCandidate {
  word: string
  markedHits: number
}

export interface ExclusionCandidatesResult {
  candidates: ExclusionCandidate[]
  markedScanned: number
  markedMissing: number
}

export function fetchExclusionCandidates(query: string, markedRefs: string[]): Promise<ExclusionCandidatesResult> {
  return sendJson(`${API_BASE}/search/exclusion-candidates`, 'POST', { query, markedRefs })
}

export interface ExclusionWordItem {
  id: number
  word: string
  createdAt: string
}

export interface ExclusionWordsResult {
  queryKey: string
  items: ExclusionWordItem[]
}

export function fetchExclusionWords(query: string): Promise<ExclusionWordsResult> {
  return getJson(`${API_BASE}/search/exclusion-words?q=${encodeURIComponent(query)}`)
}

export function approveExclusionWord(query: string, word: string): Promise<ExclusionWordItem & { already: boolean }> {
  return sendJson(`${API_BASE}/search/exclusion-words`, 'POST', { query, word })
}

export function deleteExclusionWord(id: number): Promise<void> {
  return sendJson(`${API_BASE}/search/exclusion-words/${id}`, 'DELETE')
}

// ---- NEW-366 段落级搜索结果 -------------------------------------------------

export interface ParagraphHit {
  index: number
  offset: number
  terms: string[]
  text: string
  truncatedText: boolean
}

export interface ParagraphHitsResult {
  entry: { entryRef: string; title: string }
  paragraphs: ParagraphHit[]
  paragraphTotal: number
  complete: boolean
}

export function fetchParagraphHits(entryRef: string, q: string): Promise<ParagraphHitsResult> {
  return getJson(
    `${API_BASE}/search/paragraphs?entryRef=${encodeURIComponent(entryRef)}&q=${encodeURIComponent(q)}`,
  )
}

export interface SavedFragment {
  id: number
  entryRef: string
  entryTitle: string
  query: string
  paragraphIndex: number
  text: string
  createdAt: string
}

export function saveFragment(body: {
  entryRef: string
  query: string
  paragraphIndex: number
  text: string
}): Promise<SavedFragment> {
  return sendJson(`${API_BASE}/search/fragments`, 'POST', body)
}

export function fetchFragments(entryRef?: string | null): Promise<{ items: SavedFragment[] }> {
  const suffix = entryRef ? `?entryRef=${encodeURIComponent(entryRef)}` : ''
  return getJson(`${API_BASE}/search/fragments${suffix}`)
}

export function deleteFragment(id: number): Promise<void> {
  return sendJson(`${API_BASE}/search/fragments/${id}`, 'DELETE')
}

// ---- NEW-367 搜索会话回溯 ---------------------------------------------------

export interface SessionStep {
  query: string
  filters: Record<string, unknown>
  at: string
  refs: string[]
}

export interface SearchSessionView {
  id: string
  title: string
  currentStep: number
  stepCount: number
  createdAt: string
  updatedAt: string
}

export interface SearchSessionDetail extends SearchSessionView {
  steps: SessionStep[]
  resumeStep: number
  reopened?: boolean
}

export function createSearchSession(title: string): Promise<SearchSessionView> {
  return sendJson(`${API_BASE}/search/sessions`, 'POST', { title })
}

export function fetchSearchSessions(): Promise<{ items: SearchSessionView[] }> {
  return getJson(`${API_BASE}/search/sessions`)
}

export function appendSessionStep(
  sessionId: string,
  query: string,
  filters?: Record<string, unknown>,
): Promise<SearchSessionDetail> {
  return sendJson(`${API_BASE}/search/sessions/${sessionId}/steps`, 'POST', { query, filters: filters ?? null })
}

export function setSessionSelections(sessionId: string, refs: string[]): Promise<SearchSessionDetail> {
  return sendJson(`${API_BASE}/search/sessions/${sessionId}/selections`, 'POST', { refs })
}

export function reopenSearchSession(sessionId: string): Promise<SearchSessionDetail> {
  return sendJson(`${API_BASE}/search/sessions/${sessionId}/reopen`, 'POST')
}

// ---- NEW-368 相近拼写搜索提示 -----------------------------------------------

export interface SpellCandidate {
  term: string
  suggestion: string
  distance: number
  occurrences: number
}

export interface SpellSuggestionsResult {
  hasHits: boolean
  total: number
  candidates: SpellCandidate[]
  note: string
}

export function fetchSpellSuggestions(q: string): Promise<SpellSuggestionsResult> {
  return getJson(`${API_BASE}/search/spell-suggestions?q=${encodeURIComponent(q)}`)
}

// ---- NEW-369 个人资料语言筛选 ------------------------------------------------

export interface LanguageGroup {
  language: string
  count: number
  sampleRefs: string[]
}

export interface LanguageGroupsResult {
  total: number
  complete: boolean
  groups: LanguageGroup[]
  unknown: { count: number; sampleRefs: string[] }
  note: string
}

export function fetchLanguageGroups(q: string): Promise<LanguageGroupsResult> {
  return getJson(`${API_BASE}/search/by-language?q=${encodeURIComponent(q)}`)
}

// ---- NEW-370 搜索结果评注 ----------------------------------------------------

export interface FeedbackItem {
  id: number
  entryRef: string
  entryTitle: string
  verdict: 'useful' | 'irrelevant'
  reason: string
  updatedAt: string
}

export interface FeedbackListResult {
  queryKey: string
  items: FeedbackItem[]
  counts: { useful: number; irrelevant: number }
}

export function recordHitFeedback(body: {
  query: string
  entryRef: string
  verdict: 'useful' | 'irrelevant'
  reason?: string | null
}): Promise<{ id: number; already: boolean }> {
  return sendJson(`${API_BASE}/search/feedback`, 'POST', body)
}

export function fetchHitFeedback(query: string): Promise<FeedbackListResult> {
  return getJson(`${API_BASE}/search/feedback?q=${encodeURIComponent(query)}`)
}

export interface RankingSchemeState {
  scheme: string
  enabled: boolean
  updatedAt: string | null
  note: string
}

export function fetchRankingScheme(): Promise<RankingSchemeState> {
  return getJson(`${API_BASE}/search/ranking-scheme`)
}

export function setRankingScheme(enabled: boolean): Promise<RankingSchemeState> {
  return sendJson(`${API_BASE}/search/ranking-scheme`, 'POST', { enabled })
}

export interface RerankedItem {
  entryRef: string
  boosted: boolean
}

export interface RerankedResult extends RankingSchemeState {
  items: RerankedItem[]
  complete: boolean
}

export function fetchReranked(query: string): Promise<RerankedResult> {
  return getJson(`${API_BASE}/search/reranked?q=${encodeURIComponent(query)}`)
}
