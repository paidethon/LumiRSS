/** NEW-251..260 研究项目组 — 本组专属 API 调用（独立文件，不触碰共享
 * client.ts；URL 全部相对 /api/v1/*，与 client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new25*.py / new260*.py；
 * 类型按 BFF 稳定 DTO 手写（本组端点尚未进 OpenAPI 生成集——诚实
 * 注释，不假装 generated）。 */

const API_BASE = '/api/v1'

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
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

// ---- NEW-251 研究项目主线 + 问题拆分 -----------------------------------------

export interface ResearchProject {
  id: string
  title: string
  description: string | null
  questionCount: number
  openSubquestionCount: number
  createdAt: string
  updatedAt: string
}

export interface ResearchSubquestion {
  id: string
  questionId: string
  text: string
  conclusion: string | null
  status: 'open' | 'resolved'
  createdAt: string
  updatedAt: string
  resolvedAt: string | null
}

export interface ResearchQuestion {
  id: string
  question: string
  createdAt: string
  subquestions: ResearchSubquestion[]
}

export interface QuestionMaterial {
  id: string
  itemRef: string
  addedAt: string
}

export function listResearchProjects(signal?: AbortSignal): Promise<{ items: ResearchProject[] }> {
  return getJson(`${API_BASE}/research/projects`, signal)
}

export function createResearchProject(title: string, description?: string): Promise<ResearchProject> {
  return sendJson(`${API_BASE}/research/projects`, 'POST', { title, description })
}

export function deleteResearchProject(projectId: string): Promise<null> {
  return sendJson(`${API_BASE}/research/projects/${encodeURIComponent(projectId)}`, 'DELETE')
}

export function listResearchQuestions(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; items: ResearchQuestion[] }> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/questions`,
    signal,
  )
}

export function addResearchQuestion(projectId: string, question: string): Promise<ResearchQuestion> {
  return sendJson(`${API_BASE}/research/projects/${encodeURIComponent(projectId)}/questions`, 'POST', {
    question,
  })
}

export function addSubquestion(questionId: string, text: string): Promise<ResearchSubquestion> {
  return sendJson(`${API_BASE}/research/questions/${encodeURIComponent(questionId)}/subquestions`, 'POST', {
    text,
  })
}

export function patchSubquestion(
  subquestionId: string,
  patch: { text?: string; conclusion?: string | null; status?: 'open' | 'resolved' },
): Promise<ResearchSubquestion> {
  return sendJson(`${API_BASE}/research/subquestions/${encodeURIComponent(subquestionId)}`, 'PATCH', patch)
}

export function listSubquestionMaterials(
  subquestionId: string,
  signal?: AbortSignal,
): Promise<{ subquestionId: string; items: QuestionMaterial[] }> {
  return getJson(
    `${API_BASE}/research/subquestions/${encodeURIComponent(subquestionId)}/materials`,
    signal,
  )
}

export function addSubquestionMaterial(
  subquestionId: string,
  itemRef: string,
): Promise<QuestionMaterial & { outcome: string }> {
  return sendJson(
    `${API_BASE}/research/subquestions/${encodeURIComponent(subquestionId)}/materials`,
    'POST',
    { itemRef },
  )
}

// ---- NEW-252 假设登记册 ------------------------------------------------------

export interface HypothesisMaterial {
  id: string
  itemRef: string
  side: 'support' | 'refute'
  note: string | null
  addedAt: string
}

export interface Hypothesis {
  id: string
  projectId: string
  statement: string
  supportCondition: string
  refuteCondition: string
  status: 'proposed' | 'supported' | 'refuted' | 'retired'
  materials: HypothesisMaterial[]
  createdAt: string
  updatedAt: string
}

export function listHypotheses(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; items: Hypothesis[] }> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/hypotheses`,
    signal,
  )
}

export function createHypothesis(
  projectId: string,
  body: { statement: string; supportCondition: string; refuteCondition: string },
): Promise<Hypothesis> {
  return sendJson(`${API_BASE}/research/projects/${encodeURIComponent(projectId)}/hypotheses`, 'POST', body)
}

export function patchHypothesis(
  hypothesisId: string,
  patch: { status?: Hypothesis['status'] },
): Promise<Hypothesis> {
  return sendJson(`${API_BASE}/research/hypotheses/${encodeURIComponent(hypothesisId)}`, 'PATCH', patch)
}

export function addHypothesisMaterial(
  hypothesisId: string,
  body: { itemRef: string; side: 'support' | 'refute'; note?: string },
): Promise<HypothesisMaterial & { outcome: string }> {
  return sendJson(
    `${API_BASE}/research/hypotheses/${encodeURIComponent(hypothesisId)}/materials`,
    'POST',
    body,
  )
}

// ---- NEW-253 反例收集 --------------------------------------------------------

export interface Counterexample {
  id: string
  projectId: string
  excerpt: string
  itemRef: string | null
  note: string | null
  status: 'unhandled' | 'handled'
  resolutionNote: string | null
  conclusionAdjusted: boolean | null
  resolvedAt: string | null
  createdAt: string
}

export function listCounterexamples(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; unhandledCount: number; handledCount: number; items: Counterexample[] }> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/counterexamples`,
    signal,
  )
}

export function createCounterexample(
  projectId: string,
  body: { excerpt: string; itemRef?: string; note?: string },
): Promise<Counterexample> {
  return sendJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/counterexamples`,
    'POST',
    body,
  )
}

export function attachCounterexampleSource(counterexampleId: string, itemRef: string): Promise<Counterexample> {
  return sendJson(
    `${API_BASE}/research/counterexamples/${encodeURIComponent(counterexampleId)}/source`,
    'POST',
    { itemRef },
  )
}

export function resolveCounterexample(
  counterexampleId: string,
  body: { conclusionAdjusted: boolean; resolutionNote: string },
): Promise<Counterexample> {
  return sendJson(
    `${API_BASE}/research/counterexamples/${encodeURIComponent(counterexampleId)}/resolve`,
    'POST',
    body,
  )
}

// ---- NEW-254 研究术语表 ------------------------------------------------------

export interface GlossaryTerm {
  id: string
  projectId: string
  term: string
  interpretation: string
  source: string | null
  createdAt: string
  updatedAt: string
}

export function listResearchGlossary(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; items: GlossaryTerm[] }> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/glossary`,
    signal,
  )
}

export function createResearchTerm(
  projectId: string,
  body: { term: string; interpretation: string; source?: string },
): Promise<GlossaryTerm> {
  return sendJson(`${API_BASE}/research/projects/${encodeURIComponent(projectId)}/glossary`, 'POST', body)
}

export function lookupResearchTerm(
  projectId: string,
  term: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; term: string; found: boolean; match: GlossaryTerm | null }> {
  const params = new URLSearchParams({ term })
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/glossary/lookup?${params.toString()}`,
    signal,
  )
}

export function patchResearchTerm(
  termId: string,
  patch: { interpretation?: string; source?: string | null },
): Promise<GlossaryTerm> {
  return sendJson(`${API_BASE}/research/glossary-terms/${encodeURIComponent(termId)}`, 'PATCH', patch)
}

// ---- NEW-255 事件时间线 ------------------------------------------------------

export interface TimelineEvent {
  id: string
  projectId: string
  title: string
  eventAt: string
  reportedAt: string | null
  eventDateParsed: string | null
  reportedDateParsed: string | null
  reportedDaysAfter: number | null
  itemRef: string | null
  note: string | null
  createdAt: string
  updatedAt: string
}

export function listTimelineEvents(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; unparseableCount: number; items: TimelineEvent[] }> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/timeline`,
    signal,
  )
}

export function createTimelineEvent(
  projectId: string,
  body: { title: string; eventAt: string; reportedAt?: string; itemRef?: string; note?: string },
): Promise<TimelineEvent> {
  return sendJson(`${API_BASE}/research/projects/${encodeURIComponent(projectId)}/timeline`, 'POST', body)
}

// ---- NEW-256 研究决策记录 ----------------------------------------------------

export interface DecisionFollowUp {
  id: string
  kind: 'outcome' | 'revision'
  text: string
  createdAt: string
}

export interface DecisionRecord {
  id: string
  projectId: string
  decision: string
  basis: string | null
  materials: { id: string; itemRef: string; addedAt: string }[]
  followUps: DecisionFollowUp[]
  createdAt: string
}

export function listDecisions(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; items: DecisionRecord[] }> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/decisions`,
    signal,
  )
}

export function createDecision(
  projectId: string,
  body: { decision: string; basis?: string; itemRefs?: string[] },
): Promise<DecisionRecord> {
  return sendJson(`${API_BASE}/research/projects/${encodeURIComponent(projectId)}/decisions`, 'POST', body)
}

export function addDecisionFollowUp(
  decisionId: string,
  body: { kind: 'outcome' | 'revision'; text: string },
): Promise<DecisionFollowUp> {
  return sendJson(
    `${API_BASE}/research/decisions/${encodeURIComponent(decisionId)}/followups`,
    'POST',
    body,
  )
}

export function addDecisionMaterial(
  decisionId: string,
  itemRef: string,
): Promise<{ id: string; itemRef: string; outcome: string }> {
  return sendJson(
    `${API_BASE}/research/decisions/${encodeURIComponent(decisionId)}/materials`,
    'POST',
    { itemRef },
  )
}

// ---- NEW-257 资料缺口 --------------------------------------------------------

export interface MaterialGap {
  id: string
  projectId: string
  description: string
  materialType: string | null
  status: 'open' | 'closed'
  closedAt: string | null
  closedItemRef: string | null
  closeNote: string | null
  createdAt: string
  updatedAt: string
}

export function listGaps(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; openCount: number; closedCount: number; items: MaterialGap[] }> {
  return getJson(`${API_BASE}/research/projects/${encodeURIComponent(projectId)}/gaps`, signal)
}

export function createGap(
  projectId: string,
  body: { description: string; materialType?: string },
): Promise<MaterialGap> {
  return sendJson(`${API_BASE}/research/projects/${encodeURIComponent(projectId)}/gaps`, 'POST', body)
}

export function closeGap(
  gapId: string,
  body: { itemRef: string; note?: string },
): Promise<MaterialGap> {
  return sendJson(`${API_BASE}/research/gaps/${encodeURIComponent(gapId)}/close`, 'POST', body)
}

export function reopenGap(gapId: string, reason?: string): Promise<MaterialGap> {
  return sendJson(`${API_BASE}/research/gaps/${encodeURIComponent(gapId)}/reopen`, 'POST', { reason })
}

// ---- NEW-258 研究大纲 --------------------------------------------------------

export interface OutlineItem {
  id: string
  sectionId: string
  kind: 'quote' | 'note' | 'summary'
  content: string
  citation: string | null
  position: number
  createdAt: string
  updatedAt: string
}

export interface OutlineSection {
  id: string
  title: string
  position: number
  createdAt: string
  items: OutlineItem[]
}

export function getOutline(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; sections: OutlineSection[]; note: string }> {
  return getJson(`${API_BASE}/research/projects/${encodeURIComponent(projectId)}/outline`, signal)
}

export function addOutlineSection(projectId: string, title: string): Promise<OutlineSection> {
  return sendJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/outline-sections`,
    'POST',
    { title },
  )
}

export function moveOutlineSection(
  sectionId: string,
  direction: 'up' | 'down',
): Promise<{ moved: number; note: string }> {
  return sendJson(
    `${API_BASE}/research/outline-sections/${encodeURIComponent(sectionId)}/move`,
    'POST',
    { direction },
  )
}

export function addOutlineItem(
  sectionId: string,
  body: { kind: OutlineItem['kind']; content: string; citation?: string },
): Promise<OutlineItem> {
  return sendJson(
    `${API_BASE}/research/outline-sections/${encodeURIComponent(sectionId)}/items`,
    'POST',
    body,
  )
}

export function moveOutlineItem(
  itemId: string,
  direction: 'up' | 'down',
): Promise<{ moved: number; note: string }> {
  return sendJson(
    `${API_BASE}/research/outline-items/${encodeURIComponent(itemId)}/move`,
    'POST',
    { direction },
  )
}

export function assignOutlineItem(
  itemId: string,
  targetSectionId: string,
): Promise<{ id: string; sectionId: string; note: string }> {
  return sendJson(
    `${API_BASE}/research/outline-items/${encodeURIComponent(itemId)}/assign`,
    'POST',
    { targetSectionId },
  )
}

export function getOutlineDraft(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; markdown: string; sectionCount: number; itemCount: number; note: string }> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/outline-draft`,
    signal,
  )
}

// ---- NEW-259 结论变更记录 ----------------------------------------------------

export interface ConclusionChange {
  id: string
  projectId: string
  oldText: string | null
  newText: string
  triggerRefs: string[]
  reason: string | null
  changedAt: string
}

export interface ConclusionCurrent {
  projectId: string
  text: string | null
  updatedAt: string | null
  historyCount: number
}

export function getCurrentConclusion(
  projectId: string,
  signal?: AbortSignal,
): Promise<ConclusionCurrent> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/conclusion`,
    signal,
  )
}

export function setConclusion(
  projectId: string,
  body: { text: string; triggerRefs?: string[]; reason?: string },
): Promise<ConclusionCurrent & { previousText: string | null; latestChange: ConclusionChange }> {
  return sendJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/conclusion`,
    'PUT',
    body,
  )
}

export function getConclusionHistory(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; historyCount: number; items: ConclusionChange[] }> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/conclusion/history`,
    signal,
  )
}

// ---- NEW-260 分享脱敏预览 ----------------------------------------------------

export interface SharePreviewItem {
  id: string
  table: string
  field: string
  itemId: string
  excerpt: string
}

export interface SharePreview {
  projectId: string
  privateNotes: SharePreviewItem[]
  memberNames: { username: string; occurrences: SharePreviewItem[] }[]
  attachments: []
  attachmentsNote: string
  note: string
}

export interface ShareConfirmation {
  id: string
  projectId: string
  manifest: {
    includePrivateNoteIds: string[]
    anonymizeMemberUsernames: string[]
    privateNoteCountAtConfirm: number
    memberNameHitCountAtConfirm: number
  }
  createdAt: string
}

export function getSharePreview(projectId: string, signal?: AbortSignal): Promise<SharePreview> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/share-preview`,
    signal,
  )
}

export function confirmShare(
  projectId: string,
  body: { includePrivateNoteIds: string[]; anonymizeMemberUsernames: string[] },
): Promise<ShareConfirmation> {
  return sendJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/share-confirmations`,
    'POST',
    body,
  )
}

export function listShareConfirmations(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ projectId: string; items: ShareConfirmation[] }> {
  return getJson(
    `${API_BASE}/research/projects/${encodeURIComponent(projectId)}/share-confirmations`,
    signal,
  )
}
