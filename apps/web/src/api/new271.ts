/** NEW-271..280 AI 任务的可控运行与结果复核 — 本组专属 API 调用
 * （独立文件，不触碰共享 client.ts；URL 全部相对 /api/v1/*，与
 * client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new27*.py；类型按 BFF
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

async function toApiError(response: Response): Promise<ApiError> {
  let errorType = 'request_failed'
  let message = `请求失败（${response.status}）`
  let payload: Record<string, unknown> = {}
  try {
    const body = (await response.json()) as {
      error?: { type?: string; message?: string; noteContentMd?: string }
    }
    if (body.error?.type) errorType = body.error.type
    if (body.error?.message) message = body.error.message
    payload = (body.error ?? {}) as Record<string, unknown>
  } catch {
    // 非 JSON 错误体：保留状态码信息
  }
  return new ApiError(response.status, errorType, message, payload)
}

// ---- NEW-271 AI 任务输入预览 ---------------------------------------------

export interface PreviewSection {
  key: string
  label: string
  included: boolean
  totalChars: number
  effectiveChars: number
}

export interface AiInputPreview {
  purpose: 'summary' | 'conversation'
  title: string
  feedTitle: string
  sections: PreviewSection[]
  effectiveText: string
  note: string
  noteChars: number
  truncated: boolean
  totalEffectiveChars: number
  honestyNote: string
}

export function previewAiInput(
  entryRef: string,
  body: { purpose: 'summary' | 'conversation'; maxChars?: number; note?: string; question?: string },
  signal?: AbortSignal,
): Promise<AiInputPreview> {
  return sendJson(`${API_BASE}/entries/${encodeURIComponent(entryRef)}/ai-input-preview`, 'POST', body)
}

// ---- NEW-272 AI 草稿版本对照 ---------------------------------------------

export interface AiDraft {
  id: string
  entryRef: string
  materialHash: string
  schemeLabel: string
  promptText: string
  draftText: string
  sourceKind: string
  kept: boolean
  createdAt: string
}

export interface AiDraftDiff {
  a: AiDraft
  b: AiDraft
  unified: string
  addedLines: number
  removedLines: number
  identical: boolean
}

export function generateAiDraft(
  entryRef: string,
  body: { schemeLabel: string; promptText?: string; maxChars?: number },
): Promise<AiDraft> {
  return sendJson(`${API_BASE}/entries/${encodeURIComponent(entryRef)}/ai-drafts/generate`, 'POST', body)
}

export function saveAiDraft(
  entryRef: string,
  body: { schemeLabel: string; promptText?: string; draftText: string },
): Promise<AiDraft> {
  return sendJson(`${API_BASE}/entries/${encodeURIComponent(entryRef)}/ai-drafts`, 'POST', body)
}

export interface AiDraftGroup {
  materialHash: string
  drafts: AiDraft[]
}

export async function listAiDrafts(entryRef: string, signal?: AbortSignal): Promise<AiDraft[]> {
  const payload = await getJson<{ entryRef: string; groups: AiDraftGroup[]; total: number }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/ai-drafts`,
    signal,
  )
  return (payload.groups ?? []).flatMap((group) => group.drafts)
}

export function getAiDraftDiff(draftA: string, draftB: string): Promise<AiDraftDiff> {
  return getJson(`${API_BASE}/ai-drafts/${encodeURIComponent(draftA)}/diff/${encodeURIComponent(draftB)}`)
}

export function keepAiDraft(draftId: string): Promise<AiDraft> {
  return sendJson(`${API_BASE}/ai-drafts/${encodeURIComponent(draftId)}/keep`, 'POST')
}

export function deleteAiDraft(draftId: string): Promise<null> {
  return sendJson(`${API_BASE}/ai-drafts/${encodeURIComponent(draftId)}`, 'DELETE')
}

// ---- NEW-273 提示模板试运行 -----------------------------------------------

export interface TrialSampleResult {
  title: string
  inputChars: number
  output: string
  status: 'success' | 'failed'
  errorType?: string
}

export interface TemplateTrial {
  id: string
  templateText: string
  sampleKind: string
  results: TrialSampleResult[]
  promotedTemplateId: string | null
  createdAt: string
}

export function runTemplateTrial(body: {
  templateText: string
  samples: { title: string; text: string }[]
  sampleKind?: string
}): Promise<TemplateTrial> {
  return sendJson(`${API_BASE}/ai/template-trials`, 'POST', body)
}

export async function listTemplateTrials(signal?: AbortSignal): Promise<TemplateTrial[]> {
  const payload = await getJson<{ items: TemplateTrial[]; total: number }>(
    `${API_BASE}/ai/template-trials`,
    signal,
  )
  return payload.items ?? []
}

export function promoteTemplateTrial(trialId: string, name: string): Promise<TemplateTrial> {
  return sendJson(`${API_BASE}/ai/template-trials/${encodeURIComponent(trialId)}/promote`, 'POST', { name })
}

// ---- NEW-274 AI 结果引用核验 ----------------------------------------------

export interface CheckedCitation {
  index: number
  entryRef: string
  claim: string
  status: 'found' | 'not_found' | 'entry_unavailable' | 'unchecked'
  excerpt?: string
  offset?: number
}

export interface CitationCheck {
  id: string
  answerText: string
  citations: CheckedCitation[]
  checked: boolean
  confirmedMissing: boolean
  missingCount: number
  createdAt: string
  checkedAt: string | null
  honestyNote: string
}

export function createCitationCheck(body: {
  answerText: string
  citations: { index: number; entryRef: string; claim: string }[]
}): Promise<CitationCheck> {
  return sendJson(`${API_BASE}/ai/citation-checks`, 'POST', body)
}

export async function listCitationChecks(signal?: AbortSignal): Promise<CitationCheck[]> {
  const payload = await getJson<{ items: CitationCheck[]; total: number }>(
    `${API_BASE}/ai/citation-checks`,
    signal,
  )
  return payload.items ?? []
}

export function markCitationChecked(
  checkId: string,
  confirmMissing: boolean,
): Promise<CitationCheck> {
  return sendJson(`${API_BASE}/ai/citation-checks/${encodeURIComponent(checkId)}/mark-checked`, 'POST', {
    confirmMissing,
  })
}

// ---- NEW-275 批量 AI 任务审批单 --------------------------------------------

// 后端 BUDGET_KINDS 目前只有 summary（诚实口径：只有摘要有有界的
// 单项重放路径；扩展 kind 属后端演进）。
export type ApprovalKind = 'summary'

export interface ApprovalItem {
  id: string
  entryRef: string
  status: 'pending' | 'done' | 'over_budget' | 'quota_exceeded' | 'failed' | 'cancelled'
  errorType: string | null
  finishedAt: string | null
  ord: number
}

export interface BatchApproval {
  id: string
  kind: ApprovalKind
  budgetCalls: number
  usedCalls: number
  status: 'draft' | 'approved' | 'completed' | 'cancelled'
  createdAt: string
  approvedAt: string | null
  closedAt: string | null
  items: ApprovalItem[]
}

export function createBatchApproval(body: {
  kind: ApprovalKind
  budgetCalls: number
  entryRefs: string[]
}): Promise<BatchApproval> {
  return sendJson(`${API_BASE}/ai/batch-approvals`, 'POST', body)
}

export async function listBatchApprovals(signal?: AbortSignal): Promise<BatchApproval[]> {
  const payload = await getJson<{ items: BatchApproval[]; total: number }>(
    `${API_BASE}/ai/batch-approvals`,
    signal,
  )
  return payload.items ?? []
}

export function approveBatchApproval(approvalId: string): Promise<BatchApproval> {
  return sendJson(`${API_BASE}/ai/batch-approvals/${encodeURIComponent(approvalId)}/approve`, 'POST')
}

export function executeBatchApproval(approvalId: string): Promise<BatchApproval> {
  return sendJson(`${API_BASE}/ai/batch-approvals/${encodeURIComponent(approvalId)}/execute`, 'POST')
}

export function cancelBatchApproval(approvalId: string): Promise<BatchApproval> {
  return sendJson(`${API_BASE}/ai/batch-approvals/${encodeURIComponent(approvalId)}/cancel`, 'POST')
}

// ---- NEW-276 AI 失败重放诊断 ------------------------------------------------

export interface ReplayDiagnostic {
  id: string
  kind: string
  status: string
  model: string
  entryRef: string | null
  inputChars: number
  durationMs: number
  errorType: string
  createdAt: string
  requestShape: { endpoint: string; boundedFields: string[]; note: string; entryRef?: string }
  redactionNote: string
  replayModes: string[]
}

export interface ReplayOutcome {
  replayId: string
  originalTaskId: string
  replayTaskId: string
  mode: string
}

export function getReplayDiagnostic(taskId: string, signal?: AbortSignal): Promise<ReplayDiagnostic> {
  return getJson(`${API_BASE}/ai/tasks/${encodeURIComponent(taskId)}/replay-diagnostic`, signal)
}

export function replayTask(
  taskId: string,
  body: { mode: 'same' | 'modified'; maxChars?: number; question?: string },
): Promise<ReplayOutcome> {
  return sendJson(`${API_BASE}/ai/tasks/${encodeURIComponent(taskId)}/replay`, 'POST', body)
}

// ---- NEW-277 模型配置用途约束 ------------------------------------------------

export interface PurposeConstraint {
  profileId: string
  profileLabel: string
  allowedPurposes: string[]
  purposes: string[]
}

export interface PurposeOptions {
  purpose: string
  purposes: string[]
  mappedProfileId: string | null
  blocked: boolean
  options: { profileId: string; profileLabel: string; eligible: boolean; isCurrentMapping: boolean }[]
  honestyNote: string
}

export function putPurposeConstraint(
  profileId: string,
  allowedPurposes: string[],
): Promise<PurposeConstraint> {
  return sendJson(
    `${API_BASE}/settings/ai/profiles/${encodeURIComponent(profileId)}/purpose-constraints`,
    'PUT',
    { allowedPurposes },
  )
}

export async function getPurposeConstraint(
  profileId: string,
  signal?: AbortSignal,
): Promise<PurposeConstraint | null> {
  try {
    return await getJson<PurposeConstraint>(
      `${API_BASE}/settings/ai/profiles/${encodeURIComponent(profileId)}/purpose-constraints`,
      signal,
    )
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export function getPurposeOptions(purpose: string, signal?: AbortSignal): Promise<PurposeOptions> {
  return getJson(`${API_BASE}/ai/purpose-options?purpose=${encodeURIComponent(purpose)}`, signal)
}

// ---- NEW-278 AI 输入隐私过滤预览 ---------------------------------------------

export interface PrivacyFilterView {
  exclude: string[]
  fields: string[]
  fieldLabels: Record<string, string>
  honestyNote: string
}

export interface PrivacyDiff {
  sections: (PreviewSection & { excludedByFilter?: boolean })[]
  removedChars: number
  exclude: string[]
  honestyNote: string
}

export async function getPrivacyFilters(signal?: AbortSignal): Promise<PrivacyFilterView> {
  return getJson(`${API_BASE}/ai/privacy-filters`, signal)
}

export function putPrivacyFilters(exclude: string[]): Promise<PrivacyFilterView> {
  return sendJson(`${API_BASE}/ai/privacy-filters`, 'PUT', { exclude })
}

export function postPrivacyDiff(body: {
  entryRef: string
  purpose: 'summary' | 'conversation'
  maxChars?: number
  note?: string
}): Promise<PrivacyDiff> {
  return sendJson(`${API_BASE}/ai/privacy-filters/diff`, 'POST', body)
}

// ---- NEW-279 问答结论采纳 -----------------------------------------------------

export interface AnswerAdoption {
  id: string
  entryRef: string | null
  conclusion: string
  citations: { index: number; entryRef: string }[]
  model: string
  noteUuid: string
  noteUpdatedAt: string
  noteContentHash: string
  createdAt: string
  updatedAt: string
}

export function createAnswerAdoption(body: {
  conclusion: string
  citations?: { index: number; entryRef: string }[]
  model?: string
  entryRef?: string
  noteUuid?: string
  newTitle?: string
}): Promise<AnswerAdoption> {
  return sendJson(`${API_BASE}/ai/answer-adoptions`, 'POST', body)
}

export async function listAnswerAdoptions(signal?: AbortSignal): Promise<AnswerAdoption[]> {
  const payload = await getJson<{ items: AnswerAdoption[]; total: number }>(
    `${API_BASE}/ai/answer-adoptions`,
    signal,
  )
  return payload.items ?? []
}

export function reviseAnswerAdoption(adoptionId: string, conclusion: string): Promise<AnswerAdoption> {
  return sendJson(`${API_BASE}/ai/answer-adoptions/${encodeURIComponent(adoptionId)}`, 'PATCH', {
    conclusion,
  })
}

export function deleteAnswerAdoption(adoptionId: string): Promise<null> {
  return sendJson(`${API_BASE}/ai/answer-adoptions/${encodeURIComponent(adoptionId)}`, 'DELETE')
}

// ---- NEW-280 AI 配额分桶 -------------------------------------------------------

export interface QuotaBucket {
  purpose: string
  maxCalls: number
  used: number
  remaining: number
  nearLimit: boolean
  updatedAt: string
}

export interface QuotaBucketSnapshot {
  window: string
  windowKey: string
  windowReset: string
  buckets: QuotaBucket[]
  purposes: string[]
  honestyNote: string
}

export async function getQuotaBuckets(signal?: AbortSignal): Promise<QuotaBucketSnapshot> {
  return getJson(`${API_BASE}/ai/quota/buckets`, signal)
}

export function putQuotaBucket(purpose: string, maxCalls: number): Promise<QuotaBucket> {
  return sendJson(`${API_BASE}/ai/quota/buckets/${encodeURIComponent(purpose)}`, 'PUT', { maxCalls })
}

export function deleteQuotaBucket(purpose: string): Promise<null> {
  return sendJson(`${API_BASE}/ai/quota/buckets/${encodeURIComponent(purpose)}`, 'DELETE')
}
