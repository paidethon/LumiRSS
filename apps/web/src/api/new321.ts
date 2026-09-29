/** NEW-321..330 Obsidian 与本地资料互通 — 本组专属 API 调用（独立文件，
 * 不触碰共享 client.ts；URL 全部相对 /api/v1/*，与 client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new32*.py / new330*.py；
 * 类型按 BFF 稳定响应手写（本组端点尚未进 OpenAPI 生成集——诚实注释，
 * 不假装 generated）。Vault 只读不变：所有操作作用于 Lumi 侧导入层与
 * 档案；批注导出返回文件内容，保存由用户自己完成。 */

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

async function toApiError(response: Response): Promise<ApiError> {
  let errorType = 'request_failed'
  let message = `请求失败（${response.status}）`
  try {
    const body = (await response.json()) as {
      error?: { type?: string; message?: string }
    }
    if (body.error?.type) errorType = body.error.type
    if (body.error?.message) message = body.error.message
  } catch {
    // 非 JSON 错误体：保留状态码信息
  }
  return new ApiError(response.status, errorType, message)
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
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

// ---- NEW-321 标签映射 -------------------------------------------------------

export interface TagPreview {
  sourceTags: string[]
  mappings: { sourceTag: string; targetTag: string; mapped: boolean }[]
  hierarchy: Record<string, string[]>
  conflicts: { sourceTag: string; kind: string; detail: string }[]
  merges: { targetTag: string; sourceTags: string[] }[]
}

export interface TagRule {
  sourceTag: string
  targetTag: string
}

export function previewTagMapping(): Promise<TagPreview> {
  return getJson(`${API_BASE}/obsidian/tag-mapping/preview`)
}

export function listTagRules(): Promise<{ rules: TagRule[] }> {
  return getJson(`${API_BASE}/obsidian/tag-mapping/rules`)
}

export function putTagRule(sourceTag: string, targetTag: string): Promise<TagRule> {
  return sendJson(`${API_BASE}/obsidian/tag-mapping/rules`, 'PUT', {
    sourceTag,
    targetTag,
  })
}

export function deleteTagRule(sourceTag: string): Promise<{ deleted: boolean }> {
  return sendJson(
    `${API_BASE}/obsidian/tag-mapping/rules?sourceTag=${encodeURIComponent(sourceTag)}`,
    'DELETE',
  )
}

export function materializeTagMapping(): Promise<{
  notesTagged: number
  tagCount: number
  rulesApplied: number
}> {
  return sendJson(`${API_BASE}/obsidian/tag-mapping/materialize`, 'POST')
}

export function importTagOverview(): Promise<{ tags: { tag: string; count: number }[] }> {
  return getJson(`${API_BASE}/obsidian/tag-mapping/import`)
}

// ---- NEW-322 链接解析报告 ----------------------------------------------------

export interface LinkReportItem {
  noteUuid: string
  raw: string
  status: 'resolved' | 'ambiguous' | 'broken' | 'corrected'
  reason?: string
  candidates: string[]
  targetUuid?: string
}

export function buildLinkReport(): Promise<{
  counts: Record<string, number>
  items: LinkReportItem[]
}> {
  return sendJson(`${API_BASE}/obsidian/link-report`, 'POST', {})
}

export interface LinkCorrection {
  noteUuid: string
  raw: string
  targetUuid: string
}

export function listLinkCorrections(): Promise<{ corrections: LinkCorrection[] }> {
  return getJson(`${API_BASE}/obsidian/link-report/corrections`)
}

export function putLinkCorrection(body: LinkCorrection): Promise<LinkCorrection> {
  return sendJson(`${API_BASE}/obsidian/link-report/corrections`, 'PUT', body)
}

// ---- NEW-323 同步审批 ---------------------------------------------------------

export interface SyncPlan {
  id: string
  status: string
  added: number
  changed: number
  removed: number
  renames: number
  files?: {
    added?: { items: string[] }
    changed?: { items: string[] }
    removed?: { items: string[] }
  }
}

export function previewSync(): Promise<SyncPlan> {
  return sendJson(`${API_BASE}/obsidian/sync/preview`, 'POST')
}

export function applySync(approvalId: string): Promise<{
  id: string
  status: string
  report: { added: number; changed: number; removed: number }
}> {
  return sendJson(`${API_BASE}/obsidian/sync/apply`, 'POST', { approvalId })
}

export function listSyncApprovals(): Promise<{
  approvals: { id: string; status: string; createdAt: string }[]
}> {
  return getJson(`${API_BASE}/obsidian/sync/approvals`)
}

// ---- NEW-324 批注 Markdown 输出 ------------------------------------------------

export interface AnnotationMarkdownExport {
  id: string
  filename: string
  content: string
  entryCount: number
  annotationCount: number
  unresolvedRefs: string[]
  honestyNote: string
}

export function exportAnnotationsMarkdown(entryRefs: string[]): Promise<AnnotationMarkdownExport> {
  return sendJson(`${API_BASE}/annotations/markdown-export`, 'POST', { entryRefs })
}

export function listAnnotationExports(): Promise<{
  exports: { id: string; filename: string; annotationCount: number; createdAt: string }[]
}> {
  return getJson(`${API_BASE}/annotations/markdown-export`)
}

// ---- NEW-325/329 多根目录档案 + 断开连接 ----------------------------------------

export interface RootProfile {
  id: string
  label: string
  rootPath: string
  ignoreGlobs: string[]
  authorized: boolean
  copiesPolicy: string
  lastScanAt: string | null
  lastError: string | null
  noteCount: number
}

export function createRootProfile(body: {
  label: string
  rootPath: string
  ignoreGlobs?: string[]
}): Promise<RootProfile> {
  return sendJson(`${API_BASE}/obsidian/roots`, 'POST', body)
}

export function listRootProfiles(): Promise<{ roots: RootProfile[] }> {
  return getJson(`${API_BASE}/obsidian/roots`)
}

export function scanRootProfile(rootId: string): Promise<{
  added: number
  changed: number
  removed: number
  unchanged: number
}> {
  return sendJson(`${API_BASE}/obsidian/roots/${rootId}/scan`, 'POST')
}

export function listRootNotes(rootId: string): Promise<{
  notes: { id: string; relPath: string; title: string; tags: string[] }[]
}> {
  return getJson(`${API_BASE}/obsidian/roots/${rootId}/notes`)
}

export function disconnectRoot(rootId: string): Promise<RootProfile> {
  return sendJson(`${API_BASE}/obsidian/roots/${rootId}/disconnect`, 'POST')
}

export function decideRootCopies(
  rootId: string,
  action: 'keep' | 'delete',
): Promise<{ copiesPolicy: string; removedCopies: number }> {
  return sendJson(`${API_BASE}/obsidian/roots/${rootId}/copies`, 'POST', { action })
}

export function reconnectRoot(rootId: string): Promise<RootProfile> {
  return sendJson(`${API_BASE}/obsidian/roots/${rootId}/reconnect`, 'POST')
}

// ---- NEW-326 可移植打包 --------------------------------------------------------

export interface BundleManifest {
  id: string
  noteCount: number
  attachmentCount: number
  violationCount: number
  violations: { kind: string; detail: string }[]
}

export function createBundle(noteRefs: string[]): Promise<BundleManifest> {
  return sendJson(`${API_BASE}/obsidian/bundles`, 'POST', { noteRefs })
}

export function bundleDownloadUrl(bundleId: string): string {
  return `${API_BASE}/obsidian/bundles/${bundleId}/download`
}

// ---- NEW-327 属性列映射 --------------------------------------------------------

export interface PropertyFields {
  fields: { field: string; noteCount: number }[]
  columns: {
    field: string
    label: string
    visible: boolean
    filterable: boolean
  }[]
}

export function listPropertyColumns(): Promise<PropertyFields> {
  return getJson(`${API_BASE}/obsidian/property-columns`)
}

export function putPropertyColumn(body: {
  field: string
  label?: string
  visible?: boolean
  filterable?: boolean
  position?: number
}): Promise<{ field: string }> {
  return sendJson(`${API_BASE}/obsidian/property-columns`, 'PUT', body)
}

export function filterNotesByProperty(
  field: string,
  value: string,
): Promise<{
  notes: { relPath: string; title: string; properties: Record<string, string> }[]
}> {
  return getJson(
    `${API_BASE}/obsidian/property-columns/notes?field=${encodeURIComponent(field)}&value=${encodeURIComponent(value)}`,
  )
}

// ---- NEW-328 冲突收件箱 --------------------------------------------------------

export interface SyncConflict {
  id: string
  source: { title: string; excerpt: string }
  personal: { title: string; note: string }
  status: string
}

export function putPersonalCorrection(body: {
  noteUuid: string
  personalTitle?: string
  personalNote?: string
}): Promise<{ noteUuid: string }> {
  return sendJson(`${API_BASE}/obsidian/conflict-inbox/corrections`, 'PUT', body)
}

export function detectConflicts(): Promise<{ checked: number; opened: number; refreshed: number }> {
  return sendJson(`${API_BASE}/obsidian/conflict-inbox/detect`, 'POST')
}

export function listOpenConflicts(): Promise<{ conflicts: SyncConflict[] }> {
  return getJson(`${API_BASE}/obsidian/conflict-inbox`)
}

export function resolveConflict(
  conflictId: string,
  decision: 'keep_independent' | 'adopt_source',
): Promise<SyncConflict> {
  return sendJson(
    `${API_BASE}/obsidian/conflict-inbox/${conflictId}/resolve`,
    'POST',
    { decision },
  )
}

// ---- NEW-330 重定位向导 --------------------------------------------------------

export interface RelocationPlan {
  id: string
  status: string
  newPath: string
  counts: {
    relocated: number
    fresh: number
    changed: number
    vanished: number
    ambiguous: number
    collision: number
  }
  relocated: { from: string; to: string }[]
}

export function previewRelocation(rootId: string, newPath: string): Promise<RelocationPlan> {
  return sendJson(`${API_BASE}/obsidian/roots/${rootId}/relocate/preview`, 'POST', {
    newPath,
  })
}

export function applyRelocation(rootId: string, relocationId: string): Promise<{
  relocatedApplied: number
}> {
  return sendJson(
    `${API_BASE}/obsidian/roots/${rootId}/relocate/${relocationId}/apply`,
    'POST',
  )
}
