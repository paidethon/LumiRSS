/** NEW-231..240 笔记、标注与原文锚定 — 本组专属 API 调用（独立文件，
 * 不触碰共享 client.ts；URL 全部相对 /api/v1/*，与 client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new23*.py；类型按 BFF
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

// ---- NEW-231 笔记修订对照 -----------------------------------------------------

export interface NoteVersionSummary {
  id: string
  title: string
  origin: string
  createdAt: string
}

export interface NoteVersionListResponse {
  noteId: string
  current: { ref: string; title: string; updatedAt: string }
  items: NoteVersionSummary[]
}

export interface NoteVersionDiff {
  noteId: string
  fromVersion: string
  toVersion: string
  unified: string
  addedLines: number
  removedLines: number
  identical: boolean
}

export interface NoteRestoreResult {
  noteId: string
  restoredFrom: string
  preRestoreVersionId: string
  restoredAt: string
}

export function listNoteVersions(
  noteId: string,
  signal?: AbortSignal,
): Promise<NoteVersionListResponse> {
  return getJson(`${API_BASE}/library/notes/${encodeURIComponent(noteId)}/versions`, signal)
}

export function snapshotNoteVersion(noteId: string): Promise<{ id: string; origin: string }> {
  return sendJson(`${API_BASE}/library/notes/${encodeURIComponent(noteId)}/versions`, 'POST')
}

export function diffNoteVersions(
  noteId: string,
  fromVersion: string,
  toVersion?: string,
): Promise<NoteVersionDiff> {
  const params = new URLSearchParams({ fromVersion })
  if (toVersion) params.set('toVersion', toVersion)
  return getJson(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/versions/diff?${params.toString()}`,
  )
}

export function restoreNoteVersion(noteId: string, versionRef: string): Promise<NoteRestoreResult> {
  return sendJson(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/versions/${encodeURIComponent(versionRef)}/restore`,
    'POST',
  )
}

export function listNoteRestores(
  noteId: string,
  signal?: AbortSignal,
): Promise<{ noteId: string; items: { id: string; versionId: string; versionOrigin: string; restoredAt: string }[] }> {
  return getJson(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/versions/restores`,
    signal,
  )
}

// ---- NEW-232 失效标注重定位 ---------------------------------------------------

export interface ReanchorAnchor {
  paraId: string
  prefix?: string
  exact?: string
  suffix?: string
}

export function reanchorAnnotation(
  annotationId: string,
  anchor: ReanchorAnchor,
  excerpt?: string,
): Promise<{ id: string; anchor: ReanchorAnchor; excerpt: string }> {
  return sendJson(
    `${API_BASE}/annotations/${encodeURIComponent(annotationId)}/re-anchor`,
    'POST',
    { anchor, excerpt: excerpt ?? null },
  )
}

export interface ReanchorHistoryEntry {
  id: string
  oldAnchor: Record<string, unknown>
  oldExcerpt: string
  newAnchor: Record<string, unknown>
  newExcerpt: string
  source: string
  reanchoredAt: string
}

export function listReanchorHistory(
  annotationId: string,
  signal?: AbortSignal,
): Promise<{ annotationId: string; items: ReanchorHistoryEntry[] }> {
  return getJson(
    `${API_BASE}/annotations/${encodeURIComponent(annotationId)}/re-anchor-history`,
    signal,
  )
}

// ---- NEW-233 标注汇总阅读页 ---------------------------------------------------

export interface AnnotationSummaryItem {
  id: string
  excerpt: string
  note: string
  color: string
  paraId: string
  stale: boolean
  backHref: string
}

export interface AnnotationSummaryResponse {
  entries: {
    entryRef: string
    title: string
    source: string
    annotationCount: number
    annotations: AnnotationSummaryItem[]
  }[]
  entryCount: number
  totalAnnotations: number
  truncated: boolean
}

export function annotationSummary(
  entryRef?: string,
  signal?: AbortSignal,
): Promise<AnnotationSummaryResponse> {
  const suffix = entryRef ? `?entryRef=${encodeURIComponent(entryRef)}` : ''
  return getJson(`${API_BASE}/annotations/summary${suffix}`, signal)
}

// ---- NEW-234 个人批注层 -------------------------------------------------------

export interface AnnotationLayer {
  id: string
  name: string
  createdAt: string
  itemCount: number
}

export function listAnnotationLayers(signal?: AbortSignal): Promise<{ items: AnnotationLayer[] }> {
  return getJson(`${API_BASE}/annotation-layers`, signal)
}

export function createAnnotationLayer(name: string): Promise<AnnotationLayer> {
  return sendJson(`${API_BASE}/annotation-layers`, 'POST', { name })
}

export function deleteAnnotationLayer(layerId: string): Promise<null> {
  return sendJson(`${API_BASE}/annotation-layers/${encodeURIComponent(layerId)}`, 'DELETE')
}

export function assignAnnotationLayer(
  layerId: string,
  annotationIds: string[],
): Promise<{ added: string[]; skipped: { annotationId: string; reason: string }[] }> {
  return sendJson(`${API_BASE}/annotation-layers/${encodeURIComponent(layerId)}/items`, 'POST', {
    annotationIds,
  })
}

export function layerAnnotations(
  layerId: string,
  signal?: AbortSignal,
): Promise<{ items: { id: string; entryRef: string; excerpt: string; note: string; color: string }[] }> {
  return getJson(
    `${API_BASE}/annotation-layers/${encodeURIComponent(layerId)}/annotations`,
    signal,
  )
}

export function exportAnnotationLayer(layerId: string, includeNotes: boolean): Promise<string> {
  return fetch(`${API_BASE}/annotation-layers/${encodeURIComponent(layerId)}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ includeNotes }),
  }).then(async (response) => {
    if (!response.ok) throw new Error(`导出失败（${response.status}）`)
    return response.text()
  })
}

// ---- NEW-235 笔记模板填空 -----------------------------------------------------

export interface NoteFieldTemplate {
  id: string
  name: string
  fields: { key: string; label: string }[]
}

export function listNoteTemplates(signal?: AbortSignal): Promise<{ items: NoteFieldTemplate[] }> {
  return getJson(`${API_BASE}/note-templates`, signal)
}

export function createNoteTemplate(name: string, fields: { key: string; label: string }[]): Promise<NoteFieldTemplate> {
  return sendJson(`${API_BASE}/note-templates`, 'POST', { name, fields })
}

export function putNoteTemplateFill(
  noteId: string,
  templateId: string,
  values: Record<string, string>,
): Promise<{ noteId: string; templateId: string; values: Record<string, string> }> {
  return sendJson(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/template-fill`,
    'PUT',
    { templateId, values },
  )
}

export function getNoteTemplateFill(
  noteId: string,
  signal?: AbortSignal,
): Promise<{ noteId: string; templateId: string | null; fields: { key: string; label: string }[]; values: Record<string, string> }> {
  return getJson(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/template-fill`,
    signal,
  )
}

// ---- NEW-236 批注回复提醒（显式共享面） --------------------------------------

export interface AnnotationReplyThread {
  id: string
  annotationId: string
  entryRef: string
  excerpt: string
  note: string
  sharedWithUsername: string
  createdAt: string
  updatedAt: string
  dismissedAt: string | null
  unreadForRecipient: number
  replyCount: number
  replies?: { id: string; authorUsername: string; body: string; createdAt: string }[]
}

export function shareAnnotation(annotationId: string, withUsername: string): Promise<AnnotationReplyThread> {
  return sendJson(
    `${API_BASE}/annotations/${encodeURIComponent(annotationId)}/share`,
    'POST',
    { withUsername },
  )
}

export function replyInbox(
  includeDismissed = false,
  signal?: AbortSignal,
): Promise<{ items: AnnotationReplyThread[] }> {
  return getJson(
    `${API_BASE}/annotation-replies${includeDismissed ? '?includeDismissed=true' : ''}`,
    signal,
  )
}

export function replyThreadDetail(
  threadId: string,
  signal?: AbortSignal,
): Promise<AnnotationReplyThread> {
  return getJson(`${API_BASE}/annotation-replies/${encodeURIComponent(threadId)}`, signal)
}

export function addThreadReply(threadId: string, body: string): Promise<AnnotationReplyThread> {
  return sendJson(
    `${API_BASE}/annotation-replies/${encodeURIComponent(threadId)}/replies`,
    'POST',
    { body },
  )
}

export function dismissThread(threadId: string): Promise<null> {
  return sendJson(
    `${API_BASE}/annotation-replies/${encodeURIComponent(threadId)}/dismiss`,
    'POST',
  )
}

// ---- NEW-237 引用卡片组装 -----------------------------------------------------

export interface QuoteCardPreview {
  title: string
  markdown: string
  sources: { index: number; entryRef: string; title: string; source: string; date: string; backHref: string }[]
  quoteCount: number
  unknownIds: string[]
}

export function previewQuoteCard(
  annotationIds: string[],
  includeNotes: boolean,
  title?: string,
): Promise<QuoteCardPreview> {
  return sendJson(`${API_BASE}/annotation-cards/preview`, 'POST', {
    annotationIds,
    includeNotes,
    title: title ?? null,
  })
}

export async function exportQuoteCard(
  annotationIds: string[],
  includeNotes: boolean,
  title?: string,
): Promise<string> {
  const response = await fetch(`${API_BASE}/annotation-cards/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ annotationIds, includeNotes, title: title ?? null }),
  })
  if (!response.ok) throw new Error(`导出失败（${response.status}）`)
  return response.text()
}

// ---- NEW-238 标注批量迁移 -----------------------------------------------------

export interface LayerMigrationPreview {
  fromLayerId: string | null
  toLayerId: string
  fromLayer: string | null
  toLayer: string
  items: { annotationId: string; entryRef: string; excerpt: string; color: string; fromLayer: string | null; toLayer: string }[]
  count: number
}

export function previewLayerMigration(
  fromLayerId: string | null,
  toLayerId: string,
  annotationIds?: string[],
): Promise<LayerMigrationPreview> {
  return sendJson(`${API_BASE}/annotation-layers/migrate/preview`, 'POST', {
    fromLayerId,
    toLayerId,
    annotationIds: annotationIds ?? null,
  })
}

export function applyLayerMigration(
  fromLayerId: string | null,
  toLayerId: string,
  annotationIds?: string[],
): Promise<{ moved: string[]; skipped: unknown[]; count: number }> {
  return sendJson(`${API_BASE}/annotation-layers/migrate/apply`, 'POST', {
    fromLayerId,
    toLayerId,
    annotationIds: annotationIds ?? null,
  })
}

// ---- NEW-239 标注冲突解决器 ---------------------------------------------------

export interface NoteConflictSide {
  noteId: string
  title: string
  contentMd: string
  version: number
  updatedAt: string
}

export async function submitConflictedEdit(
  noteId: string,
  input: { title: string; contentMd: string; baseVersion: number; deviceLabel?: string },
): Promise<
  | { outcome: 'applied'; note: NoteConflictSide }
  | { outcome: 'conflict'; pendingEditId: string; server: NoteConflictSide; incoming: { title: string; contentMd: string; deviceLabel: string } }
> {
  // 409 是合法回包（冲突语义，编辑已暂存），不是抛错路径。
  const response = await fetch(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/conflicted-edits`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
  )
  const body = (await response.json().catch(() => null)) as
    | { outcome?: string; error?: { message?: string } }
    | null
  if (response.ok && body?.outcome === 'applied') {
    return body as unknown as { outcome: 'applied'; note: NoteConflictSide }
  }
  if (response.status === 409 && body?.outcome === 'conflict') {
    return body as unknown as {
      outcome: 'conflict'
      pendingEditId: string
      server: NoteConflictSide
      incoming: { title: string; contentMd: string; deviceLabel: string }
    }
  }
  throw new Error(body?.error?.message ?? `请求失败（${response.status}）`)
}

export async function fetchConflictSides(
  noteId: string,
  signal?: AbortSignal,
): Promise<{ server: NoteConflictSide; pending: { id: string; title: string; contentMd: string; deviceLabel: string; baseVersion: number }[] }> {
  const response = await fetch(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/conflicted-edits`,
    { signal },
  )
  if (!response.ok) throw new Error(`请求失败（${response.status}）`)
  return (await response.json()) as {
    server: NoteConflictSide
    pending: { id: string; title: string; contentMd: string; deviceLabel: string; baseVersion: number }[]
  }
}

export async function resolveConflictRaw(
  noteId: string,
  pendingEditId: string,
  resolution: string,
  merged?: { title: string; contentMd: string },
): Promise<{ ok: boolean; status: number; body: unknown }> {
  const response = await fetch(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/conflicted-edits/${encodeURIComponent(pendingEditId)}/resolve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(
        merged ? { resolution, title: merged.title, contentMd: merged.contentMd } : { resolution },
      ),
    },
  )
  const body = response.status === 204 ? null : await response.json().catch(() => null)
  return { ok: response.ok, status: response.status, body }
}

// ---- NEW-240 笔记附件清单 -----------------------------------------------------

export interface NoteAttachmentItem {
  id: string
  filename: string
  mimeType: string
  sizeBytes: number
  createdAt: string
}

export function listNoteAttachments(
  noteId: string,
  signal?: AbortSignal,
): Promise<{
  noteId: string
  items: NoteAttachmentItem[]
  usage: { count: number; totalBytes: number; fileCapBytes: number; noteCapBytes: number; fileCapCount: number }
}> {
  return getJson(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/attachments`,
    signal,
  )
}

export async function addNoteAttachment(
  noteId: string,
  filename: string,
  contentBase64: string,
  mimeType?: string,
): Promise<NoteAttachmentItem> {
  return sendJson(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/attachments`,
    'POST',
    { filename, mimeType: mimeType ?? null, contentBase64 },
  )
}

export function removeNoteAttachment(noteId: string, attachmentId: string): Promise<null> {
  return sendJson(
    `${API_BASE}/library/notes/${encodeURIComponent(noteId)}/attachments/${encodeURIComponent(attachmentId)}`,
    'DELETE',
  )
}
