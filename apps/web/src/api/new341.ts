/** NEW-341..350 隐私、会话与可理解的授权 — 本组专属 API 调用。
 *
 * 后端真源：services/bff/src/lumirss/routers/new34*.py / new350*.py；
 * 类型按 BFF 稳定 DTO 手写（本组端点尚未进 OpenAPI 生成集——诚实
 * 注释，不假装 generated）。URL 全部相对 /api/v1/*。
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
  const text = await response.text()
  return (text ? (JSON.parse(text) as T) : (null as T))
}

// ---- NEW-341 个人数据访问记录 ------------------------------------------------

export interface AccessEvent {
  id: number
  purpose: string
  purposeLabel: string
  entry: string
  accessedAt: string
}

export interface AccessLog {
  items: AccessEvent[]
  recordedScope: string
  unrecorded: string[]
  bounded: boolean
}

export const getAccessLog = () => getJson<AccessLog>(`${API_BASE}/privacy/access-log`)

// ---- NEW-342 第三方请求清单 --------------------------------------------------

export interface ThirdPartyItem {
  key: string
  scope: string
  host: string | null
  purpose: string
  optional: boolean
  disabled: boolean
  controlledBy: string | null
  optoutKey: string | null
}

export interface ThirdPartyInventory {
  reading: ThirdPartyItem[]
  ai: ThirdPartyItem[]
  note: string
  optoutLabels: Record<string, string>
  recentActions: { key: string; action: string; createdAt: string }[]
}

export const getThirdPartyRequests = () =>
  getJson<ThirdPartyInventory>(`${API_BASE}/privacy/third-party-requests`)

export async function toggleThirdPartyRequest(key: string, disabled: boolean): Promise<void> {
  await sendJson(`${API_BASE}/privacy/third-party-requests/${key}/toggle`, 'POST', { disabled })
}

// ---- NEW-343 敏感资料标记 ----------------------------------------------------

export interface SensitiveMark {
  entryRef: string
  reason: string
  createdAt: string
}

export const listAiSendBlocks = () =>
  getJson<{ items: SensitiveMark[]; note: string }>(`${API_BASE}/privacy/ai-send-blocks`)

export async function putAiSendBlock(entryRef: string, reason?: string): Promise<void> {
  await sendJson(`${API_BASE}/privacy/ai-send-blocks/${entryRef}`, 'POST', { reason: reason ?? null })
}

export async function deleteAiSendBlock(entryRef: string): Promise<void> {
  await sendJson(`${API_BASE}/privacy/ai-send-blocks/${entryRef}`, 'DELETE')
}

// ---- NEW-344/345 共享链接（范围 + 次数上限） ----------------------------------

export interface ShareLink {
  id: number
  title: string
  scope: 'titles' | 'excerpt' | 'full'
  excerptChars: number
  createdAt: string
  revokedAt: string | null
  maxUses: number | null
  useCount: number
  exhaustedAt: string | null
}

export interface ShareLinkCreated extends ShareLink {
  token: string
  path: string
  note: string
}

export interface ShareLinkPreview {
  title: string
  scope: string
  scopeLabel: string
  items: Record<string, unknown>[]
  neverIncluded: string[]
  note: string
  linkState?: { revoked: boolean; useCount: number; maxUses: number | null; exhaustedAt: string | null }
}

export interface ShareLinkAccess {
  id: number
  accessedAt: string
  result: string
}

export const listShareLinks = () =>
  getJson<{ items: ShareLink[]; note: string }>(`${API_BASE}/privacy/share-links`)

export async function createShareLink(body: {
  title: string
  scope: string
  entryRefs: string[]
  excerptChars?: number
  maxUses?: number | null
}): Promise<ShareLinkCreated> {
  return sendJson<ShareLinkCreated>(`${API_BASE}/privacy/share-links`, 'POST', body)
}

export const previewShareLink = (id: number) =>
  getJson<ShareLinkPreview>(`${API_BASE}/privacy/share-links/${id}/preview`)

export async function revokeShareLink(id: number): Promise<void> {
  await sendJson(`${API_BASE}/privacy/share-links/${id}/revoke`, 'POST')
}

export async function setShareLinkLimit(id: number, maxUses: number | null): Promise<void> {
  await sendJson(`${API_BASE}/privacy/share-links/${id}/limit`, 'POST', { maxUses })
}

export async function topupShareLink(id: number, addUses: number): Promise<void> {
  await sendJson(`${API_BASE}/privacy/share-links/${id}/topup`, 'POST', { addUses })
}

export const listShareLinkAccesses = (id: number) =>
  getJson<{ items: ShareLinkAccess[]; note: string }>(
    `${API_BASE}/privacy/share-links/${id}/accesses`,
  )

// ---- NEW-346 设备信任期限 ----------------------------------------------------

export interface DeviceTrustStatus {
  currentDevice: {
    deviceFingerprint: string
    deviceLabel: string
    trusted: boolean
    trustedUntil: string | null
  }
  grants: {
    deviceFingerprint: string
    deviceLabel: string
    trustedUntil: string
    createdAt: string
    trusted: boolean
  }[]
  note: string
}

export const getDeviceTrust = () =>
  getJson<DeviceTrustStatus>(`${API_BASE}/privacy/device-trust`)

export async function grantDeviceTrust(password: string, hours: number): Promise<void> {
  await sendJson(`${API_BASE}/privacy/device-trust`, 'POST', { password, hours })
}

export async function revokeDeviceTrust(): Promise<void> {
  await sendJson(`${API_BASE}/privacy/device-trust`, 'DELETE')
}

// ---- NEW-347 单项授权撤销中心 ------------------------------------------------

export interface AuthorizationItem {
  kind: string
  ref: string
  label: string
  active: boolean
  detail: string
  affected: string
}

export interface AuthorizationInventory {
  items: AuthorizationItem[]
  note: string
}

export const listAuthorizations = () =>
  getJson<AuthorizationInventory>(`${API_BASE}/privacy/authorizations`)

export async function revokeAuthorization(kind: string, ref: string): Promise<void> {
  await sendJson(`${API_BASE}/privacy/authorizations/${kind}/${ref}/revoke`, 'POST')
}

// ---- NEW-348 数据驻留说明 ----------------------------------------------------

export interface ResidencySection {
  key: string
  title: string
  detail: string
  known: boolean
  adminNote: string | null
  adminNoteUpdatedAt: string | null
}

export interface ResidencyView {
  sections: ResidencySection[]
  unknownKeys: string[]
  unknownHint: string
}

export const getDataResidency = () =>
  getJson<ResidencyView>(`${API_BASE}/privacy/data-residency`)

// ---- NEW-349 隐私检查向导 ----------------------------------------------------

export interface ReviewItem {
  key: string
  category: string
  title: string
  detail: string
  withdraw: { available: boolean; actionKey: string | null; needsRef: boolean; how: string }
}

export interface PrivacyReview {
  items: ReviewItem[]
  note: string
  recentActions: { key: string; ref: string; action: string; createdAt: string }[]
}

export const getPrivacyReview = () =>
  getJson<PrivacyReview>(`${API_BASE}/privacy/review`)

export async function withdrawReviewItem(key: string, ref = ''): Promise<void> {
  await sendJson(`${API_BASE}/privacy/review/${key}/withdraw`, 'POST', { ref })
}

// ---- NEW-350 删除范围预览与回执 ----------------------------------------------

export interface DeletionPreview {
  categories: Record<string, number>
  sharedCopies: { copy: string; rule: string; action: string }[]
  note: string
}

export interface DeletionReceipt {
  id: number
  requestedAt: string
  scheduledDeletionAt: string | null
  actions: { category: string; action: string; count: number }[]
  retained: string[]
}

export const getDeletionPreview = () =>
  getJson<DeletionPreview>(`${API_BASE}/privacy/deletion/preview`)

export async function confirmDeletion(
  password: string,
  confirmText: string,
): Promise<{ receipt: DeletionReceipt; retained: string[] }> {
  return sendJson(`${API_BASE}/privacy/deletion/confirm`, 'POST', { password, confirmText })
}

export const listDeletionReceipts = () =>
  getJson<{ items: DeletionReceipt[] }>(`${API_BASE}/privacy/deletion/receipts`)
