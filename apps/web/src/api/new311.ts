/** NEW-311..320 剪藏与书签资料组 — 本组专属 API 调用（独立文件，不触
 * 碰共享 client.ts；URL 全部相对 /api/v1/*，与 client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new31*.py / new320*.py；
 * 类型按 BFF 稳定 DTO 手写（本组端点尚未进 OpenAPI 生成集——诚实注
 * 释，不假装 generated）。 */

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

async function sendRawText<T>(path: string, html: string): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'text/html' },
    body: html,
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

// ---- NEW-311 书签目录导入 -------------------------------------------------

export interface ImportFolder {
  path: string
  count: number
}

export interface ImportDuplicate {
  url: string
  title: string
  folderPath: string
  inFile: boolean
  inLibrary: boolean
}

export interface ImportPreview {
  total: number
  validTotal: number
  folderMap: ImportFolder[]
  duplicates: ImportDuplicate[]
  invalid: { url: string; title: string; reason: string }[]
  honestyNote: string
}

export interface ImportSetResult {
  id: string
  total: number
  imported: number
  skipped: number
  folders: string[]
}

export function previewBookmarkImport(html: string): Promise<ImportPreview> {
  return sendRawText<ImportPreview>(
    `${API_BASE}/library/bookmarks/import/preview`,
    html,
  )
}

export function confirmBookmarkImport(
  html: string,
  options: { folders?: string[]; includeDuplicates?: boolean; sourceName?: string },
): Promise<ImportSetResult> {
  const params = new URLSearchParams()
  for (const folder of options.folders ?? []) params.append('folder', folder)
  if (options.includeDuplicates) params.set('includeDuplicates', 'true')
  if (options.sourceName) params.set('sourceName', options.sourceName)
  const query = params.toString()
  return sendRawText<ImportSetResult>(
    `${API_BASE}/library/bookmarks/import/sets${query ? `?${query}` : ''}`,
    html,
  )
}

// ---- NEW-312 选区剪藏包 ----------------------------------------------------

export interface SelectionInput {
  text: string
  note?: string
}

export interface SelectionPackage {
  id: string
  url: string
  pageTitle: string
  clipRef: string | null
  createdAt: string
  selections: { seq: number; text: string; note: string }[]
}

export function createSelectionPackage(body: {
  url: string
  pageTitle: string
  selections: SelectionInput[]
  clipRef?: string | null
}): Promise<SelectionPackage> {
  return sendJson<SelectionPackage>(
    `${API_BASE}/library/clip-selections`,
    'POST',
    body,
  )
}

export function listSelectionPackages(url?: string): Promise<{ packages: SelectionPackage[] }> {
  const query = url ? `?url=${encodeURIComponent(url)}` : ''
  return getJson(`${API_BASE}/library/clip-selections${query}`)
}

// ---- NEW-313 候选对照 -------------------------------------------------------

export interface ExtractCandidate {
  id: string
  strategy: 'article' | 'fulltext'
  title: string
  charCount: number
  preview: string
  chosen: boolean
}

export interface ExtractCompare {
  clipRef: string
  candidates: ExtractCandidate[]
  honestyNote: string
}

export function compareExtractCandidates(clipUuid: string): Promise<ExtractCompare> {
  return sendJson(`${API_BASE}/library/clips/${clipUuid}/extract-compare`, 'POST')
}

export function chooseExtractCandidate(
  clipUuid: string,
  candidateId: string,
): Promise<{ chosenId: string; note: string }> {
  return sendJson(
    `${API_BASE}/library/clips/${clipUuid}/extract-compare/${candidateId}/choose`,
    'POST',
  )
}

// ---- NEW-314 快照文字检索层 --------------------------------------------------

export interface TextLayerStatus {
  assetRef: string
  built: boolean
  blockCount: number
}

export interface TextLayerHit {
  seq: number
  anchor: string
  text: string
}

export function buildTextLayer(assetUuid: string): Promise<{ blockCount: number }> {
  return sendJson(`${API_BASE}/library/snapshots/${assetUuid}/text-layer`, 'POST')
}

export function searchTextLayer(
  assetUuid: string,
  q: string,
): Promise<{ hits: TextLayerHit[]; hitCount: number; truncated: boolean }> {
  return getJson(
    `${API_BASE}/library/snapshots/${assetUuid}/text-layer?q=${encodeURIComponent(q)}`,
  )
}

// ---- NEW-315 链接批量替换 ----------------------------------------------------

export interface ReplaceChange {
  ref: string
  title: string
  before: string
  after: string
}

export interface ReplaceApplyResult {
  id: string
  changed: number
  conflicts: { ref: string; url: string; reason: string }[]
}

export function previewLinkReplace(
  fromDomain: string,
  toDomain: string,
): Promise<{ changes: ReplaceChange[] }> {
  return sendJson(`${API_BASE}/library/bookmarks/link-replace/preview`, 'POST', {
    fromDomain,
    toDomain,
  })
}

export function applyLinkReplace(
  fromDomain: string,
  toDomain: string,
): Promise<ReplaceApplyResult> {
  return sendJson(`${API_BASE}/library/bookmarks/link-replace/apply`, 'POST', {
    fromDomain,
    toDomain,
  })
}

export function undoReplaceBatch(batchId: string): Promise<{ restored: number }> {
  return sendJson(
    `${API_BASE}/library/bookmarks/link-replace/batches/${batchId}/undo`,
    'POST',
  )
}

// ---- NEW-316 书签意图 --------------------------------------------------------

export interface BookmarkIntent {
  ref: string
  title: string
  url: string | null
  reason: string
  whenToUse: string
}

export function putBookmarkIntent(
  bookmarkUuid: string,
  intent: { reason?: string; whenToUse?: string },
): Promise<BookmarkIntent> {
  return sendJson(
    `${API_BASE}/library/bookmarks/${bookmarkUuid}/intent`,
    'PUT',
    intent,
  )
}

export function listBookmarkIntents(params: {
  q?: string
  when?: string
}): Promise<{ items: BookmarkIntent[]; total: number }> {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.when) search.set('when', params.when)
  const query = search.toString()
  return getJson(`${API_BASE}/library/bookmark-intents${query ? `?${query}` : ''}`)
}

// ---- NEW-317 重复合并 ---------------------------------------------------------

export interface DuplicateGroup {
  key: string
  items: { ref: string; url: string; title: string; textChars: number }[]
}

export function listDuplicateGroups(): Promise<{ groups: DuplicateGroup[] }> {
  return getJson(`${API_BASE}/library/clip-duplicates`)
}

export function mergeClips(body: {
  keepRef: string
  mergeRefs: string[]
  metaPolicy: 'kept' | 'newest'
}): Promise<{ keptRef: string; mergedRefs: string[]; carriedSelections: number }> {
  return sendJson(`${API_BASE}/library/clips/merge`, 'POST', body)
}

// ---- NEW-318 图片选择器 --------------------------------------------------------

export interface ManifestImage {
  src: string
  alt: string
  bytes: number | null
}

export interface ImageManifest {
  images: ManifestImage[]
  imageCount: number
  honestyNote: string
}

export interface CuratedClipResult {
  clip: { ref: string; title: string; contentHtml: string }
  created: boolean
  selectedCount: number
  unknownSelections: string[]
}

export function fetchImageManifest(url: string): Promise<ImageManifest> {
  return sendJson(`${API_BASE}/library/clips/image-manifest`, 'POST', { url })
}

export function createCuratedClip(
  url: string,
  selectedImages: string[],
): Promise<CuratedClipResult> {
  return sendJson(`${API_BASE}/library/clips/curated`, 'POST', {
    url,
    selectedImages,
  })
}

// ---- NEW-319 重新提取 ----------------------------------------------------------

export interface ReextractRequest {
  id: string
  status: 'pending' | 'done' | 'failed'
  title: string
  charCount: number
  error: string | null
  applied: boolean
}

export function requestReextract(clipUuid: string): Promise<ReextractRequest> {
  return sendJson(`${API_BASE}/library/clips/${clipUuid}/reextract`, 'POST')
}

export function listReextractions(clipUuid: string): Promise<{ requests: ReextractRequest[] }> {
  return getJson(`${API_BASE}/library/clips/${clipUuid}/reextract`)
}

export function applyReextract(
  clipUuid: string,
  requestId: string,
): Promise<{ appliedAt: string; note: string }> {
  return sendJson(
    `${API_BASE}/library/clips/${clipUuid}/reextract/${requestId}/apply`,
    'POST',
  )
}

// ---- NEW-320 失效替代关联 -------------------------------------------------------

export interface ReplacementHistoryItem {
  id: string
  newUrl: string
  reason: string
  current: boolean
}

export function addReplacementLink(
  bookmarkUuid: string,
  body: { newUrl: string; reason: string },
): Promise<{ id: string; oldUrl: string | null; newUrl: string }> {
  return sendJson(
    `${API_BASE}/library/bookmarks/${bookmarkUuid}/replacement`,
    'POST',
    body,
  )
}

export function listReplacementLinks(
  bookmarkUuid: string,
): Promise<{ oldUrl: string | null; oldLinkPreserved: boolean; history: ReplacementHistoryItem[] }> {
  return getJson(`${API_BASE}/library/bookmarks/${bookmarkUuid}/replacement`)
}
