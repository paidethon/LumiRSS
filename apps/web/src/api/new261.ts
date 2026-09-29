/** NEW-261..270 翻译质量与个人语言工作流 — 本组专属 API 调用（独立文件，
 * 不触碰共享 client.ts；URL 全部相对 /api/v1/*，与 client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new26*.py；类型按 BFF
 * 稳定 DTO 手写（本组端点尚未进 OpenAPI 生成集——诚实注释，不假装
 * generated）。 */

const API_BASE = '/api/v1'

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
  if (!response.ok) throw new Error(`请求失败（${response.status}）`)
  return (await response.json()) as T
}

async function sendJson<T>(
  path: string,
  method: 'POST' | 'PUT' | 'DELETE',
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const payload = (await response.json()) as { error?: { message?: string } }
      if (payload.error?.message) message = payload.error.message
    } catch {
      // 非 JSON 错误体：保留状态码信息
    }
    throw new Error(message)
  }
  if (response.status === 204) return null as T
  return (await response.json()) as T
}

// ---- NEW-261 术语表冲突处理 ---------------------------------------------------

export interface GlossaryVariant {
  termId: string
  definition: string
  sourceRef: string | null
  protect: boolean
  updatedAt: string
}

export interface GlossaryChoice {
  term: string
  chosenTermId: string
  scope: 'project' | 'source'
  sourceUrl: string
  updatedAt: string
}

export interface GlossaryConflict {
  term: string
  variants: GlossaryVariant[]
  chosen?: GlossaryChoice
}

export function listGlossaryConflicts(signal?: AbortSignal): Promise<{ conflicts: GlossaryConflict[] }> {
  return getJson(`${API_BASE}/glossary/conflicts`, signal)
}

export function setGlossaryChoice(
  term: string,
  chosenTermId: string,
  scope: 'project' | 'source',
  sourceUrl = '',
): Promise<GlossaryChoice> {
  return sendJson(`${API_BASE}/glossary/conflicts/choice`, 'POST', {
    term,
    chosenTermId,
    scope,
    sourceUrl,
  })
}

export function clearGlossaryChoice(
  term: string,
  scope: 'project' | 'source',
  sourceUrl = '',
): Promise<{ removed: boolean }> {
  const params = new URLSearchParams({ term, scope })
  if (sourceUrl) params.set('sourceUrl', sourceUrl)
  return sendJson(`${API_BASE}/glossary/conflicts/choice?${params.toString()}`, 'DELETE')
}

// ---- NEW-262 译文人工修订层 ---------------------------------------------------

export interface RevisionDecision {
  id: string
  blockIndex: number
  overwrittenText: string
  supersededMachineText: string
  createdAt: string
}

export interface RevisionDiscardResult extends RevisionDecision {
  regenerated: {
    status: string
    translatedText?: string | null
    failureType?: string | null
    cached?: boolean
    reason?: string
  } | null
}

export function discardRevision(
  entryRef: string,
  blockIndex: number,
  regenerate: boolean,
): Promise<RevisionDiscardResult> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/segments/${blockIndex}/revision/discard`,
    'POST',
    { regenerate },
  )
}

export function listRevisionDecisions(
  entryRef: string,
  signal?: AbortSignal,
): Promise<{ decisions: RevisionDecision[] }> {
  return getJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/revision-decisions`,
    signal,
  )
}

// ---- NEW-263 译文质量反馈 -----------------------------------------------------

export type FeedbackIssueKind = 'omission' | 'mistranslation' | 'format'

export interface TranslationFeedback {
  id: string
  entryRef: string
  blockIndex: number
  issueKind: FeedbackIssueKind
  note: string
  sourceExcerpt: string | null
  machineExcerpt: string | null
  revisedExcerpt: string | null
  status: 'open' | 'resolved'
  createdAt: string
  resolvedAt: string | null
}

export function createSegmentFeedback(
  entryRef: string,
  blockIndex: number,
  issueKind: FeedbackIssueKind,
  note: string,
): Promise<TranslationFeedback> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/segments/${blockIndex}/feedback`,
    'POST',
    { issueKind, note },
  )
}

export function listEntryFeedback(
  entryRef: string,
  signal?: AbortSignal,
): Promise<{ feedback: TranslationFeedback[] }> {
  return getJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/feedback`,
    signal,
  )
}

export function listFeedbackQueue(
  signal?: AbortSignal,
): Promise<{ queue: TranslationFeedback[] }> {
  return getJson(`${API_BASE}/translation/feedback/queue`, signal)
}

export function resolveFeedback(feedbackId: string): Promise<TranslationFeedback> {
  return sendJson(`${API_BASE}/translation/feedback/${encodeURIComponent(feedbackId)}/resolve`, 'POST')
}

export function deleteFeedback(feedbackId: string): Promise<{ removed: boolean }> {
  return sendJson(`${API_BASE}/translation/feedback/${encodeURIComponent(feedbackId)}`, 'DELETE')
}

// ---- NEW-264 翻译服务能力比较 -------------------------------------------------

export interface ProbeSampleOutcome {
  index: number
  ok: boolean
  text?: string
  error?: string
  elapsedMs: number
}

export interface ProbeSide {
  configured: boolean
  reason?: string
  samples?: ProbeSampleOutcome[]
}

export interface CapabilityProbeReport {
  id: string
  samples: string[]
  sides: Record<string, ProbeSide>
  available: boolean
  reason: string
  createdAt: string
}

export function runCapabilityProbe(samples: string[]): Promise<CapabilityProbeReport> {
  return sendJson(`${API_BASE}/translation/capability-probe`, 'POST', { samples })
}

export function listCapabilityProbes(signal?: AbortSignal): Promise<{ probes: CapabilityProbeReport[] }> {
  return getJson(`${API_BASE}/translation/capability-probe`, signal)
}

// ---- NEW-265 翻译任务预算预估 -------------------------------------------------

export interface BudgetSettings {
  pricePer1kChars: number | null
  currency: string
  updatedAt: string
}

export interface BudgetEstimate {
  totalBlocks: number
  chargeableBlocks: number
  cachedBlocks: number
  noTranslateBlocks: number
  revisedBlocks: number
  totalChars: number
  chargeableChars: number
  pricePer1kChars: number | null
  currency: string
  estimatedCost: number | null
  engine: string
  note: string
}

export function getBudgetSettings(signal?: AbortSignal): Promise<BudgetSettings> {
  return getJson(`${API_BASE}/translation/budget/settings`, signal)
}

export function putBudgetSettings(
  pricePer1kChars: number | null,
  currency: string,
): Promise<BudgetSettings> {
  return sendJson(`${API_BASE}/translation/budget/settings`, 'PUT', {
    pricePer1kChars,
    currency,
  })
}

export function estimateBudget(
  entryRef: string,
  blocks: Array<{ index: number; text: string }>,
): Promise<BudgetEstimate> {
  return sendJson(`${API_BASE}/translation/budget/estimate`, 'POST', {
    entryRef,
    blocks,
  })
}

// ---- NEW-266 分段翻译优先队列 -------------------------------------------------

export interface QueueEntry {
  index: number
  addedAt: string
}

export interface QueueRunState {
  index: number
  status: 'success' | 'failed' | 'not_generated'
  translatedText: string | null
  failureType: string | null
  cached: boolean
}

export interface QueueRunResult {
  queuedCount: number
  skippedMissingText: number[]
  queuedStates: QueueRunState[]
}

export function getPriorityQueue(
  entryRef: string,
  signal?: AbortSignal,
): Promise<{ queue: QueueEntry[] }> {
  return getJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/priority-queue`,
    signal,
  )
}

export function putPriorityQueue(entryRef: string, indexes: number[]): Promise<{ queue: QueueEntry[] }> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/priority-queue`,
    'PUT',
    { indexes },
  )
}

export function clearPriorityQueue(entryRef: string): Promise<{ removed: number }> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/priority-queue`,
    'DELETE',
  )
}

export function removePriorityQueueItem(entryRef: string, index: number): Promise<{ removed: boolean }> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/priority-queue/${index}`,
    'DELETE',
  )
}

export function runPriorityQueue(
  entryRef: string,
  blocks: Array<{ index: number; text: string }>,
): Promise<QueueRunResult> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/priority-queue/run`,
    'POST',
    { blocks },
  )
}

// ---- NEW-267 专有名词保护例外 -------------------------------------------------

export interface ProtectException {
  term: string
  createdAt: string
}

export interface ProtectHit {
  term: string
  hitSegments: number
}

export function getProtectExceptions(
  entryRef: string,
  signal?: AbortSignal,
): Promise<{ exceptions: ProtectException[]; hits: ProtectHit[] }> {
  return getJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/protect-exceptions`,
    signal,
  )
}

export function addProtectException(entryRef: string, term: string): Promise<ProtectException> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/protect-exceptions`,
    'POST',
    { term },
  )
}

export function removeProtectException(entryRef: string, term: string): Promise<{ removed: boolean }> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/protect-exceptions/${encodeURIComponent(term)}`,
    'DELETE',
  )
}

// ---- NEW-268 译文引用导出 -----------------------------------------------------

export interface QuoteExport {
  id: string
  entryRef: string
  blockIndex: number
  sourceText: string
  translatedText: string
  humanRevised: boolean
  sourceUrl: string
  feedTitle: string
  format: string
  rendered?: string
  createdAt: string
}

export function exportQuote(
  entryRef: string,
  blockIndex: number,
  blockText: string,
  confirmed: boolean,
  format = 'markdown',
): Promise<QuoteExport> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/segments/${blockIndex}/quote-export`,
    'POST',
    { blockText, format, confirmed },
  )
}

export function listQuoteExports(
  entryRef: string,
  signal?: AbortSignal,
): Promise<{ exports: QuoteExport[] }> {
  return getJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/quote-exports`,
    signal,
  )
}

// ---- NEW-269 语言识别纠正 -----------------------------------------------------

export interface LanguageOverride {
  scope: 'entry' | 'source'
  refKey: string
  language: string
  createdAt: string
  updatedAt: string
}

export function listLanguageOverrides(signal?: AbortSignal): Promise<{ overrides: LanguageOverride[] }> {
  return getJson(`${API_BASE}/translation/language-overrides`, signal)
}

export function setLanguageOverride(
  scope: 'entry' | 'source',
  refKey: string,
  language: string,
): Promise<LanguageOverride> {
  return sendJson(`${API_BASE}/translation/language-overrides`, 'PUT', { scope, refKey, language })
}

export function deleteLanguageOverride(scope: 'entry' | 'source', refKey: string): Promise<{ removed: boolean }> {
  const params = new URLSearchParams({ scope, refKey })
  return sendJson(`${API_BASE}/translation/language-overrides?${params.toString()}`, 'DELETE')
}

export function getEntryLanguageOverride(
  entryRef: string,
  signal?: AbortSignal,
): Promise<{ language: string | null }> {
  return getJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/language-override`,
    signal,
  )
}

// ---- NEW-270 翻译完整性报告 ---------------------------------------------------

export interface CompletenessReport {
  id: string
  entryRef: string
  total: number
  translated: number
  failed: number
  missing: number
  skipped: number
  translatedIndexes: number[]
  failedIndexes: number[]
  missingIndexes: number[]
  skippedIndexes: number[]
  filled: number
  createdAt: string
}

export function buildCompletenessReport(
  entryRef: string,
  blocks: Array<{ index: number; text: string }>,
): Promise<CompletenessReport> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/completeness/report`,
    'POST',
    { blocks },
  )
}

export function fillCompleteness(
  entryRef: string,
  blocks: Array<{ index: number; text: string }>,
): Promise<CompletenessReport> {
  return sendJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/completeness/fill`,
    'POST',
    { blocks },
  )
}

export function listCompletenessReports(
  entryRef: string,
  signal?: AbortSignal,
): Promise<{ reports: Array<Omit<CompletenessReport, 'translatedIndexes' | 'failedIndexes' | 'missingIndexes' | 'skippedIndexes'>> }> {
  return getJson(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/completeness/reports`,
    signal,
  )
}
