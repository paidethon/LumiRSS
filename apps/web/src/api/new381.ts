/** NEW-381..390 长期保存与格式互通 — 本组专属 API 调用。
 *
 * 后端真源：services/bff/src/lumirss/routers/new38*.py / new390*.py；
 * 类型按 BFF 稳定 DTO 手写（本组端点尚未进 OpenAPI 生成集——诚实
 * 注释，不假装 generated）。URL 全部相对 /api/v1/*。
 * 口令类入参（NEW-387）只在请求体内出现，绝不写 localStorage/日志。
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
  return new ApiError(
    response.status,
    'request_failed',
    messageOf(parsed, `请求失败（${response.status}）`),
  )
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

async function sendRaw<T>(path: string, body: string): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body,
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

async function sendJson<T>(
  path: string,
  method: 'POST',
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

// ---- NEW-381/382 书目记录（Zotero RDF / RIS） -----------------------------

export interface BibRecord {
  id: string
  format: 'zotero_rdf' | 'ris'
  externalId: string
  title: string
  creators: string[]
  pubYear: string
  publication: string
  publisher: string
  url: string
  doi: string
  itemType: string
  tags: string[]
  unsupportedFields: string[]
  createdAt: string
}

export interface BibPreviewItem extends BibRecord {
  duplicate: boolean
  duplicateOf: string | null
  duplicateReason: string
}

export interface BibPreview {
  format: string
  total: number
  duplicates: number
  unsupportedFields: string[]
  items: BibPreviewItem[]
}

export async function getRecords(format?: string): Promise<{ records: BibRecord[] }> {
  const query = format ? `?format=${encodeURIComponent(format)}` : ''
  return getJson(`${API_BASE}/preservation/records${query}`)
}

export const previewZoteroRdf = (content: string): Promise<BibPreview> =>
  sendRaw(`${API_BASE}/preservation/zotero/preview`, content)

export function importZoteroRdf(content: string): Promise<{
  batchId: string
  total: number
  imported: number
  duplicates: number
  failed: number
  unsupportedFields: string[]
}> {
  return sendRaw(`${API_BASE}/preservation/zotero/import`, content)
}

export const previewRis = (content: string): Promise<BibPreview> =>
  sendRaw(`${API_BASE}/preservation/ris/preview`, content)

export function importRis(content: string): Promise<{
  batchId: string
  total: number
  imported: number
  duplicates: number
  failed: number
  unsupportedFields: string[]
}> {
  return sendRaw(`${API_BASE}/preservation/ris/import`, content)
}

// ---- NEW-383 离线站点 -------------------------------------------------------

export interface OfflineSiteManifest {
  id: string
  itemCount: number
  items: { kind: string; ref: string; title: string; path: string }[]
  violations: { slug: string; target: string }[]
  violationCount: number
  externalLinks: string[]
  missing: string[]
  sha256: string
  createdAt?: string
}

export const listOfflineSites = () =>
  getJson<{ sites: OfflineSiteManifest[] }>(`${API_BASE}/preservation/offline-sites`)

export function createOfflineSite(bibIds: string[], clipRefs: string[]): Promise<OfflineSiteManifest> {
  return sendJson(`${API_BASE}/preservation/offline-sites`, 'POST', {
    bibIds,
    clipRefs,
  })
}

// ---- NEW-384 JSON Feed ------------------------------------------------------

export interface FeedExportEntry {
  id: string
  scope: string
  clipCount: number
  bibCount: number
  fieldsIncluded: string[]
  authorizationScope: string
  createdAt: string
}

export const listFeedExports = () =>
  getJson<{ exports: FeedExportEntry[] }>(`${API_BASE}/preservation/json-feed/exports`)

export function createJsonFeed(scopes: string[]): Promise<{ itemCount: number }> {
  return sendJson(`${API_BASE}/preservation/json-feed`, 'POST', { scopes })
}

// ---- NEW-386 格式对照 -------------------------------------------------------

export interface FormatFieldView {
  bytes: number
  fields: Record<string, 'kept' | 'changed' | 'lost' | 'na'>
  lostFields: string[]
  changedFields: string[]
}

export interface ComparisonEntry {
  id: string
  itemIds: string[]
  createdAt: string
}

export const listComparisons = () =>
  getJson<{ comparisons: ComparisonEntry[] }>(`${API_BASE}/preservation/format-compare`)

export interface CompareResponse {
  comparisonId: string
  compared: number
  missing: string[]
  items: {
    id: string
    externalId: string
    title: string
    formats: Record<string, FormatFieldView>
  }[]
}

export function compareFormats(itemIds: string[]): Promise<CompareResponse> {
  return sendJson(`${API_BASE}/preservation/format-compare`, 'POST', { itemIds })
}

// ---- NEW-387 加密导出 -------------------------------------------------------

export interface EncryptedExportEntry {
  id: string
  itemCount: number
  payloadBytes: number
  kdf: string
  kdfIterations: number
  cipher: string
  payloadSha256: string
  decryptVerified: boolean
  createdAt: string
}

export const listEncryptedExports = () =>
  getJson<{ exports: EncryptedExportEntry[] }>(
    `${API_BASE}/preservation/encrypted-exports`,
  )

export function createEncryptedExport(
  itemIds: string[],
  passphrase: string,
): Promise<{
  id: string
  itemCount: number
  payloadBase64: string
  decryptVerified: boolean
  format: { kdf: string; cipher: string; note: string }
}> {
  return sendJson(`${API_BASE}/preservation/encrypted-exports`, 'POST', {
    itemIds,
    passphrase,
  })
}

export function verifyEncryptedExport(
  payloadBase64: string,
  passphrase: string,
): Promise<{ decryptVerified: boolean; itemCount: number; note: string }> {
  return sendJson(`${API_BASE}/preservation/encrypted-exports/verify`, 'POST', {
    payloadBase64,
    passphrase,
  })
}

// ---- NEW-388 索引导出 -------------------------------------------------------

export interface IndexExportEntry {
  id: string
  recordCount: number
  tagCount: number
  sourceCount: number
  catalogSha256: string
  createdAt: string
}

export const listIndexExports = () =>
  getJson<{ exports: IndexExportEntry[] }>(
    `${API_BASE}/preservation/index-export/exports`,
  )

export interface IndexCatalog {
  recordCount: number
  records: {
    externalId: string
    title: string
    sha256: string
  }[]
  tags: Record<string, number>
  sources: Record<string, number>
  excluded: string[]
  catalogSha256: string
  note: string
}

export const buildIndexCatalog = () =>
  getJson<IndexCatalog>(`${API_BASE}/preservation/index-export`)

// ---- NEW-389 分卷 -----------------------------------------------------------

export interface VolumeSet {
  setId: string
  volumeCount: number
  maxVolumeBytes: number
  totalBytes: number
  itemCount: number
  createdAt: string
}

export const listVolumeSets = () =>
  getJson<{ sets: VolumeSet[] }>(`${API_BASE}/preservation/volumes/sets`)

export function exportVolumes(
  itemIds: string[],
  maxVolumeBytes: number,
): Promise<{ setManifest: { setId: string; volumeCount: number; itemCount: number }; volumes: unknown[] }> {
  return sendJson(`${API_BASE}/preservation/volumes/export`, 'POST', {
    itemIds,
    maxVolumeBytes,
  })
}

export function checkVolumes(
  setManifest: unknown,
  volumes: unknown[],
): Promise<{
  complete: boolean
  missingVolumes: number[]
  missingItems: string[]
}> {
  return sendJson(`${API_BASE}/preservation/volumes/check`, 'POST', {
    setManifest,
    volumes,
  })
}

// ---- NEW-390 对账 -----------------------------------------------------------

export interface Reconciliation {
  id: string
  source: string
  expectedCount: number
  results: {
    externalId: string
    recordId?: string
    title: string
    status: 'added' | 'matched' | 'failed' | 'missing'
    detail: string
  }[]
  confirmed: string[]
  pendingCount: number
  status: 'open' | 'completed'
  counts: Record<string, number>
  createdAt: string
}

export const listReconciliations = () =>
  getJson<{ reconciliations: Reconciliation[] }>(
    `${API_BASE}/preservation/reconciliations`,
  )

export function confirmReconciliation(
  id: string,
  externalIds: string[],
): Promise<Reconciliation & { acceptedNow: number }> {
  return sendJson(
    `${API_BASE}/preservation/reconciliations/${encodeURIComponent(id)}/confirm`,
    'POST',
    { externalIds },
  )
}
