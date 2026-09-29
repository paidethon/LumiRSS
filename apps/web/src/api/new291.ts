/** NEW-291..300 邮件资料与通讯阅读 — 本组专属 API 调用（独立文件，
 * 不触碰共享 client.ts；URL 全部相对 /api/v1/*，与 client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new29*.py、new300*.py；
 * 类型按 BFF 稳定 DTO 手写（本组端点尚未进 OpenAPI 生成集——诚实注释，
 * 不假装 generated）。 */

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

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
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
  try {
    const body = (await response.json()) as { error?: { type?: string; message?: string } }
    if (body.error?.type) errorType = body.error.type
    if (body.error?.message) message = body.error.message
  } catch {
    // 非 JSON 错误体：保留状态码信息
  }
  return new ApiError(response.status, errorType, message)
}

// ---- NEW-291 EML 导入 -------------------------------------------------------

export interface AttachmentMeta {
  filename: string
  contentType: string
  size: number
  sha256: string
}

export interface ImportedItem {
  id: string
  filename: string
  subject: string
  fromAddr: string
  snippet: string
  tags: string[]
  sourceLabel: string
  sourceOrigin?: string
  attachments: AttachmentMeta[]
  messageId: string
}

export interface ImportResult {
  imported: ImportedItem[]
  failed: { filename: string; reason: string }[]
  skipped: { filename: string; reason: string; messageId: string }[]
  conflicts: { conflictId: string; filename: string; reason: string; existingId: string }[]
  honestyNote: string
}

export interface EmailMaterialSummary {
  id: string
  messageId: string
  subject: string
  fromName: string
  fromAddr: string
  to: string
  date: string
  snippet: string
  sourceLabel: string
  threadId: string
  linkMode: string
  tags: string[]
  attachments: AttachmentMeta[]
  rawBytes: number
  createdAt: string
}

export interface EmailMaterialDetail extends EmailMaterialSummary {
  bodyText: string
  bodyHtmlSanitized: string
  headers: Record<string, string>
}

export function importEmails(
  files: { filename: string; content: string }[],
  rules?: ImportRule[],
): Promise<ImportResult> {
  return sendJson(`${API_BASE}/email-materials/import`, 'POST', { files, rules })
}

export async function listEmailMaterials(signal?: AbortSignal): Promise<EmailMaterialSummary[]> {
  const payload = await getJson<{ items: EmailMaterialSummary[]; total: number }>(
    `${API_BASE}/email-materials`,
    signal,
  )
  return payload.items ?? []
}

export function getEmailMaterial(id: string, signal?: AbortSignal): Promise<EmailMaterialDetail> {
  return getJson(`${API_BASE}/email-materials/${encodeURIComponent(id)}`, signal)
}

// ---- NEW-292 会话串联 -------------------------------------------------------

export interface ThreadMember {
  id: string
  subject: string
  fromAddr: string
  date: string
  snippet: string
  linkMode: string
}

export interface ThreadView {
  threadId: string
  subjectHint: string
  members: ThreadMember[]
  honestyNote: string
}

export function linkThread(materialId: string, targetId: string): Promise<ThreadView> {
  return sendJson(`${API_BASE}/email-materials/${encodeURIComponent(materialId)}/thread-link`, 'POST', {
    targetId,
  })
}

export function getThread(threadId: string, signal?: AbortSignal): Promise<ThreadView> {
  return getJson(`${API_BASE}/email-threads/${encodeURIComponent(threadId)}`, signal)
}

// ---- NEW-293 引用折叠 -------------------------------------------------------

export interface QuoteSegment {
  index: number
  kind: 'own' | 'quoted'
  lines: number
  text: string
  reviewed: boolean
}

export interface QuoteSegmentsView {
  materialId: string
  segments: QuoteSegment[]
  quotedCount: number
  quotedLines: number
  reviewedCount: number
  honestyNote: string
}

export function getQuoteSegments(materialId: string, signal?: AbortSignal): Promise<QuoteSegmentsView> {
  return getJson(
    `${API_BASE}/email-materials/${encodeURIComponent(materialId)}/quote-segments`,
    signal,
  )
}

export function markQuoteReviewed(materialId: string, segmentIndex: number): Promise<QuoteSegmentsView> {
  return sendJson(
    `${API_BASE}/email-materials/${encodeURIComponent(materialId)}/quote-reviews`,
    'POST',
    { segmentIndex },
  )
}

// ---- NEW-294 来源映射 -------------------------------------------------------

export interface SourceMap {
  fromAddr: string
  sourceLabel: string
  updatedAt: string
}

export async function listSourceMaps(signal?: AbortSignal): Promise<SourceMap[]> {
  const payload = await getJson<{ items: SourceMap[] }>(`${API_BASE}/email-source-maps`, signal)
  return payload.items ?? []
}

export function putSourceMap(fromAddr: string, sourceLabel: string): Promise<SourceMap> {
  return sendJson(
    `${API_BASE}/email-source-maps/${encodeURIComponent(fromAddr)}`,
    'PUT',
    { sourceLabel },
  )
}

export function deleteSourceMap(fromAddr: string): Promise<null> {
  return sendJson(`${API_BASE}/email-source-maps/${encodeURIComponent(fromAddr)}`, 'DELETE')
}

// ---- NEW-295 隐私遮罩 -------------------------------------------------------

export interface MaskInfo {
  id: string
  kind: string
  kindLabel: string
}

export interface ShareView {
  materialId: string
  maskedBodyText: string
  masks: MaskInfo[]
  originalPrivate: boolean
  honestyNote: string
}

export function addMask(materialId: string, kind: string, value: string): Promise<unknown> {
  return sendJson(`${API_BASE}/email-materials/${encodeURIComponent(materialId)}/masks`, 'POST', {
    kind,
    value,
  })
}

export function getShareView(materialId: string, signal?: AbortSignal): Promise<ShareView> {
  return getJson(
    `${API_BASE}/email-materials/${encodeURIComponent(materialId)}/share-view`,
    signal,
  )
}

export function deleteMask(maskId: string): Promise<null> {
  return sendJson(`${API_BASE}/email-masks/${encodeURIComponent(maskId)}`, 'DELETE')
}

// ---- NEW-296 附件条目 -------------------------------------------------------

export interface AttachmentItem {
  id: string
  materialId: string
  ord: number
  filename: string
  contentType: string
  size: number
  parentSubject: string
  createdAt: string
}

export function promoteAttachment(materialId: string, ord: number): Promise<AttachmentItem> {
  return sendJson(
    `${API_BASE}/email-materials/${encodeURIComponent(materialId)}/attachments/${ord}/promote`,
    'POST',
  )
}

export async function listAttachmentItems(signal?: AbortSignal): Promise<AttachmentItem[]> {
  const payload = await getJson<{ items: AttachmentItem[] }>(
    `${API_BASE}/email-attachment-items`,
    signal,
  )
  return payload.items ?? []
}

export function deleteAttachmentItem(itemId: string): Promise<null> {
  return sendJson(`${API_BASE}/email-attachment-items/${encodeURIComponent(itemId)}`, 'DELETE')
}

// ---- NEW-297 导入规则 -------------------------------------------------------

export interface ImportRule {
  kind: 'subject_clean' | 'tag' | 'source_map'
  config: Record<string, string>
}

export interface PreviewSample {
  filename: string
  status: 'ok' | 'failed'
  reason?: string
  subjectRaw?: string
  subject?: string
  tags?: string[]
  fromAddr?: string
  sourceLabel?: string
  sourceOrigin?: string
}

export function previewImportRules(
  files: { filename: string; content: string }[],
  rules: ImportRule[],
): Promise<{ samples: PreviewSample[]; honestyNote: string }> {
  return sendJson(`${API_BASE}/email-imports/preview`, 'POST', { files, rules })
}

// ---- NEW-298 重复识别复核 ----------------------------------------------------

export interface DuplicateConflict {
  id: string
  messageId: string
  existingId: string
  digestsDiffer: boolean
  filename: string
  status: 'pending' | 'kept_existing' | 'kept_incoming' | 'kept_both'
  resultId: string
  incomingPreview?: { subject: string; fromAddr: string; snippet: string; attachmentCount: number }
}

export async function listDuplicates(signal?: AbortSignal): Promise<DuplicateConflict[]> {
  const payload = await getJson<{ items: DuplicateConflict[] }>(
    `${API_BASE}/email-duplicates`,
    signal,
  )
  return payload.items ?? []
}

export function resolveDuplicate(conflictId: string, choice: string): Promise<{ status: string; resultId: string }> {
  return sendJson(
    `${API_BASE}/email-duplicates/${encodeURIComponent(conflictId)}/resolve`,
    'POST',
    { choice },
  )
}

// ---- NEW-299 退订信息卡 -------------------------------------------------------

export interface UnsubCard {
  materialId: string
  available: boolean
  methods: { type: string; target: string }[]
  oneClickDeclared: boolean
  listHelp: string
  opens: { method: string; target: string; opened_at: string }[]
  honestyNote: string
}

export function getUnsubCard(materialId: string, signal?: AbortSignal): Promise<UnsubCard> {
  return getJson(
    `${API_BASE}/email-materials/${encodeURIComponent(materialId)}/unsubscribe`,
    signal,
  )
}

export function recordUnsubOpen(
  materialId: string,
  method: string,
  target: string,
): Promise<{ note: string }> {
  return sendJson(
    `${API_BASE}/email-materials/${encodeURIComponent(materialId)}/unsubscribe-open`,
    'POST',
    { method, target },
  )
}

// ---- NEW-300 脱敏导出 -------------------------------------------------------

export interface RemovedField {
  field: string
  reason: string
}

export interface EmailExport {
  exportId: string
  options: { includeAddresses: boolean; includeFullHeaders: boolean }
  subject: string
  from: string
  to: string
  headers: Record<string, string>
  bodyText: string
  attachments: AttachmentMeta[]
  maskedRegions: { kindLabel: string }[]
  removedFields: RemovedField[]
  honestyNote: string
}

export function exportEmail(
  materialId: string,
  includeAddresses: boolean,
  includeFullHeaders: boolean,
): Promise<EmailExport> {
  return sendJson(`${API_BASE}/email-materials/${encodeURIComponent(materialId)}/export`, 'POST', {
    includeAddresses,
    includeFullHeaders,
  })
}
