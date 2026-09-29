/** NEW-241..250 原文版本、溯源与证据 — 本组专属 API 调用（独立文件，
 * 不触碰共享 client.ts；URL 全部相对 /api/v1/*，与 client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new24*.py；类型按 BFF
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

// ---- NEW-241 文章更新差异阅读 -----------------------------------------------

export interface ArticleVersionSummary {
  id: string
  label: string
  origin: string
  createdAt: string
  contentChars: number
}

export interface ArticleVersionFull extends ArticleVersionSummary {
  entryRef: string
  contentText: string
}

export interface ParagraphDiff {
  blocks: {
    type: 'unchanged' | 'added' | 'removed' | 'modified'
    text?: string
    oldText?: string
    newText?: string
  }[]
  added: number
  removed: number
  modified: number
  unchanged: number
  identical: boolean
}

export const saveArticleVersion = (entryRef: string, label: string, contentText: string) =>
  sendJson< ArticleVersionSummary >(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/article-versions`,
    'POST',
    { label, contentText },
  )

export const listArticleVersions = (entryRef: string, signal?: AbortSignal) =>
  getJson<{ entryRef: string; items: ArticleVersionSummary[] }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/article-versions`,
    signal,
  )

export const readArticleVersion = (entryRef: string, versionId: string, signal?: AbortSignal) =>
  getJson<ArticleVersionFull>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/article-versions/${encodeURIComponent(versionId)}`,
    signal,
  )

export const diffArticleVersions = (entryRef: string, fromVersion: string, toVersion: string, signal?: AbortSignal) =>
  getJson<ParagraphDiff & { entryRef: string; fromVersion: string; toVersion: string }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/article-versions/diff?fromVersion=${encodeURIComponent(fromVersion)}&toVersion=${encodeURIComponent(toVersion)}`,
    signal,
  )

// ---- NEW-242 来源时间轴 ------------------------------------------------------

export interface TimelineItem {
  kind: 'published' | 'received' | 'updated' | 'saved'
  label: string
  time: string | null
  available: boolean
  source: string
}

export const getSourceTimeline = (entryRef: string, signal?: AbortSignal) =>
  getJson<{ entryRef: string; projectionKnown: boolean; items: TimelineItem[] }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/source-timeline`,
    signal,
  )

export const listTimelineAnnotations = (entryRef: string, signal?: AbortSignal) =>
  getJson<{ items: { kind: string; label: string; note: string; createdAt: string }[] }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/source-timeline/annotations`,
    signal,
  )

export const putTimelineAnnotation = (entryRef: string, kind: string, note: string) =>
  sendJson<{ kind: string; note: string }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/source-timeline/annotations/${kind}`,
    'PUT',
    { note },
  )

// ---- NEW-243 原始 feed 字段查看器 ---------------------------------------------

export interface RawFieldView {
  key: string
  value: unknown
  present: boolean
  appMapping: string
  sourceDescription: string
}

export const getRawFields = (entryRef: string, signal?: AbortSignal) =>
  getJson<{ entryRef: string; fields: RawFieldView[] }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/raw-fields`,
    signal,
  )

export const createRawFieldReport = (entryRef: string, fieldKey: string, problem: string, expected: string) =>
  sendJson<{ id: string }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/raw-fields/reports`,
    'POST',
    { fieldKey, problem, expected },
  )

export const listRawFieldReports = (entryRef: string, signal?: AbortSignal) =>
  getJson<{ items: { id: string; fieldKey: string; problem: string; expected: string; createdAt: string }[] }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/raw-fields/reports`,
    signal,
  )

// ---- NEW-244 链接存活复核 ------------------------------------------------------

export interface LinkRecheckItem {
  id: string
  ref: string
  url: string | null
  status: 'ok' | 'redirect' | 'dead' | 'unknown'
  httpStatus: number | null
  finalUrl: string | null
  detail: string
  checkedAt: string
}

export const runLinkRecheck = (refs: string[]) =>
  sendJson<{ items: LinkRecheckItem[]; count: number }>(
    `${API_BASE}/library/link-recheck`,
    'POST',
    { refs },
  )

export const listLinkRecheckResults = (signal?: AbortSignal) =>
  getJson<{ items: LinkRecheckItem[] }>(`${API_BASE}/library/link-recheck/results`, signal)

// ---- NEW-245 引文出处补全 ------------------------------------------------------

export interface CitationFieldView {
  original: string | null
  supplement: string | null
  effective: string | null
  origin: 'original' | 'supplement' | null
}

export interface CitationView {
  citationRef: string
  title: string
  registeredAt: string
  author: CitationFieldView
  date: CitationFieldView
}

export const registerCitation = (citationRef: string, title: string, author: string | null, dateValue: string | null) =>
  sendJson<CitationView>(`${API_BASE}/citations`, 'POST', {
    citationRef,
    title,
    author,
    dateValue,
  })

export const listCitations = (signal?: AbortSignal) =>
  getJson<{ items: CitationView[] }>(`${API_BASE}/citations`, signal)

export const putCitationSupplement = (citationRef: string, field: 'author' | 'date', value: string) =>
  sendJson<{ citationRef: string; field: string; value: string }>(
    `${API_BASE}/citations/${encodeURIComponent(citationRef)}/supplements/${field}`,
    'PUT',
    { value },
  )

export const deleteCitationSupplement = (citationRef: string, field: 'author' | 'date') =>
  sendJson<null>(
    `${API_BASE}/citations/${encodeURIComponent(citationRef)}/supplements/${field}`,
    'DELETE',
  )

// ---- NEW-246 资料来源链 -------------------------------------------------------

export interface CitationEdge {
  id: string
  fromRef: string
  toRef: string
  note: string
  registeredAt: string
}

export const createCitationEdge = (fromRef: string, toRef: string, note: string) =>
  sendJson<CitationEdge>(`${API_BASE}/citation-edges`, 'POST', { fromRef, toRef, note })

export const deleteCitationEdge = (edgeId: string) =>
  sendJson<null>(`${API_BASE}/citation-edges/${encodeURIComponent(edgeId)}`, 'DELETE')

export const listCitationEdges = (fromRef: string | undefined, signal?: AbortSignal) =>
  getJson<{ items: CitationEdge[] }>(
    fromRef !== undefined
      ? `${API_BASE}/citation-edges?fromRef=${encodeURIComponent(fromRef)}`
      : `${API_BASE}/citation-edges`,
    signal,
  )

export const traceCitationChain = (ref: string, signal?: AbortSignal) =>
  getJson<{
    startRef: string
    chain: { ref: string; missingLink: boolean; edges: CitationEdge[] }[]
    cycle: boolean
    truncated: boolean
  }>(`${API_BASE}/citation-chain?ref=${encodeURIComponent(ref)}`, signal)

// ---- NEW-247 原文变动关注 ------------------------------------------------------

export interface ContentWatchStatus {
  id: string
  entryRef: string
  baselineSha256: string
  baselineChars: number
  status: 'watching' | 'changed'
  changedAt: string | null
  lastCheckedAt: string | null
  checksCount: number
  createdAt: string
}

export const watchContent = (entryRef: string, baselineText: string) =>
  sendJson<ContentWatchStatus>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/content-watch`,
    'POST',
    { baselineText },
  )

export const getContentWatch = (entryRef: string, signal?: AbortSignal) =>
  getJson<ContentWatchStatus>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/content-watch`,
    signal,
  )

export const unwatchContent = (entryRef: string) =>
  sendJson<null>(`${API_BASE}/entries/${encodeURIComponent(entryRef)}/content-watch`, 'DELETE')

export const checkContentWatch = (entryRef: string, currentText: string) =>
  sendJson<{ entryRef: string; status: string; changed: boolean; checkedAt: string }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/content-watch/check`,
    'POST',
    { currentText },
  )

export const getContentWatchDiff = (entryRef: string, signal?: AbortSignal) =>
  getJson<ParagraphDiff & { changedAt: string }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/content-watch/diff`,
    signal,
  )

// ---- NEW-248 来源链接去追踪预览 ------------------------------------------------

export interface DetrackPreview {
  supported: boolean
  reason?: string
  removed: string[]
  keptRequired: string[]
  keptUser: string[]
  cleanedUrl: string
  url: string
}

export const previewDetrack = (url: string) =>
  sendJson<DetrackPreview>(`${API_BASE}/links/detrack-preview`, 'POST', { url })

export const listKeptParams = (signal?: AbortSignal) =>
  getJson<{ items: { param: string; reason: string; createdAt: string }[] }>(
    `${API_BASE}/links/detrack-kept-params`,
    signal,
  )

export const putKeptParam = (param: string, reason: string) =>
  sendJson<{ param: string; reason: string }>(
    `${API_BASE}/links/detrack-kept-params/${encodeURIComponent(param)}`,
    'PUT',
    { reason },
  )

export const deleteKeptParam = (param: string) =>
  sendJson<null>(`${API_BASE}/links/detrack-kept-params/${encodeURIComponent(param)}`, 'DELETE')

export const deleteLicenseRecord = (targetRef: string) =>
  sendJson<null>(`${API_BASE}/licenses/${encodeURIComponent(targetRef)}`, 'DELETE')

// ---- NEW-249 资料引用许可证提示 -------------------------------------------------

export interface LicenseRecordView {
  targetRef: string
  status: 'recorded' | 'source_explicit' | 'explicit_undeclared' | 'unknown'
  licenseText: string | null
  infoSource: string | null
  note: string
  updatedAt: string | null
}

export const putLicenseRecord = (
  targetRef: string,
  licenseText: string,
  infoSource: 'user_record' | 'source_explicit',
  note: string,
) => sendJson<LicenseRecordView>(`${API_BASE}/licenses/${encodeURIComponent(targetRef)}`, 'PUT', {
  licenseText,
  infoSource,
  note,
})

export const previewLicenseNotice = (targetRefs: string[]) =>
  sendJson<{ items: LicenseRecordView[]; unknownCount: number; disclaimer: string }>(
    `${API_BASE}/licenses/notice-preview`,
    'POST',
    { targetRefs },
  )

// ---- NEW-250 证据完整性检查单 ---------------------------------------------------

export interface EvidenceItemView {
  id: string
  citationRef: string
  sourceRef: string | null
  versionId: string | null
  excerpt: string | null
  hasSource: boolean
  hasVersion: boolean
  versionExists: boolean | null
  hasExcerpt: boolean
  missing: string[]
  complete: boolean
  updatedAt: string
}

export const createEvidenceChecklist = (reportLabel: string, citationRefs: string[]) =>
  sendJson<{ reportLabel: string; citationRefs: string[] }>(
    `${API_BASE}/evidence-checklists`,
    'POST',
    { reportLabel, citationRefs },
  )

export const getEvidenceChecklist = (reportLabel: string, signal?: AbortSignal) =>
  getJson<{
    reportLabel: string
    items: EvidenceItemView[]
    total: number
    completeCount: number
    missingCount: number
  }>(
    `${API_BASE}/evidence-checklists/${encodeURIComponent(reportLabel)}`,
    signal,
  )

export const patchEvidenceItem = (
  reportLabel: string,
  citationRef: string,
  patch: { sourceRef?: string; versionId?: string; excerpt?: string },
) =>
  sendJson<EvidenceItemView>(
    `${API_BASE}/evidence-checklists/${encodeURIComponent(reportLabel)}/items/${encodeURIComponent(citationRef)}`,
    'PATCH',
    patch,
  )
