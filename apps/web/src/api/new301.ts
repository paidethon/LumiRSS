/** NEW-301..310 API 来源、Webhook 与自动接入 — 本组专属 API 调用
 * （独立文件，不触碰共享 client.ts；URL 全部相对 /api/v1/*，与
 * client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new301*.py … new310*.py；
 * 类型按 BFF 稳定 DTO 手写（本组端点尚未进 OpenAPI 生成集——诚实
 * 注释，不假装 generated）。 */

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

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

async function sendJson<T>(
  path: string,
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(extraHeaders ?? {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return null as T
  const text = await response.text()
  return (text ? (JSON.parse(text) as T) : (null as T))
}

// ---- 来源小清单（组合各工具来源选择器；uuid/name/表达式/暂停态） --------

export interface ApiSourceRef {
  uuid: string
  name: string
  writePaused?: boolean
  pauseReason?: string | null
}

export function listSourceRefs(): Promise<{ items: ApiSourceRef[] }> {
  return getJson<{ items: ApiSourceRef[] }>(`${API_BASE}/api-sources`)
}

// ---- NEW-301 映射样本 -----------------------------------------------------

export interface MappingSample {
  id: number
  label: string
  sampleJson: unknown
  createdAt: string
}

export const new301Api = {
  listSamples: (uuid: string) =>
    getJson<{ items: MappingSample[] }>(sampleListUrl(uuid)),
  save: (uuid: string, label: string, sampleJson: unknown) =>
    sendJson<{ id: number; label: string }>(
      sampleListUrl(uuid),
      'POST',
      { label, sampleJson },
    ),
  remove: (uuid: string, sampleId: number) =>
    sendJson<null>(sampleIdUrl(uuid, sampleId), 'DELETE'),
  preview: (
    uuid: string,
    sampleId: number,
    fieldMap: Record<string, string>,
  ) =>
    sendJson<{ items: Record<string, unknown>[]; totalAvailable: number }>(
      sampleIdUrl(uuid, sampleId) + '/preview',
      'POST',
      { fieldMap },
    ),
  bind: (uuid: string, fieldMap: Record<string, string>) =>
    sendJson<{ note: string }>(
      `${API_BASE}/api-sources/${encodeURIComponent(uuid)}/mapping-bind`,
      'POST',
      { fieldMap },
    ),
}

function sourceUrl(uuid: string, suffix: string): string {
  return `${API_BASE}/api-sources/${encodeURIComponent(uuid)}${suffix}`
}

function sampleListUrl(uuid: string): string {
  return sourceUrl(uuid, '/mapping-samples')
}

function sampleIdUrl(uuid: string, sampleId: number, suffix = ''): string {
  return `${sampleListUrl(uuid)}/${sampleId}${suffix}`
}

// ---- NEW-302 分页试抓台 -----------------------------------------------------

export interface ProbePage {
  page: number | string
  url: string
  itemCount?: number
  error?: string
  duplicate?: boolean
}

export interface ProbeResult {
  sourceUuid?: string
  probedAt: string
  stopReason: string
  pageCount: number
  itemCount: number
  duplicatePages: number
  gapPages: number
  pages: ProbePage[]
}

export const new302Api = {
  run: (uuid: string, maxPages: number) =>
    sendJson<ProbeResult>(sourceUrl(uuid, '/pagination-probe'), 'POST', { maxPages }),
  last: (uuid: string) =>
    getJson<ProbeResult>(sourceUrl(uuid, '/pagination-probe')),
}

// ---- NEW-303 Webhook 接收收件箱 ---------------------------------------------

export interface WebhookEndpointRow {
  uuid: string
  label: string
  enabled: boolean
  createdAt: string
}

export interface InboxRow {
  id: number
  endpointUuid: string
  eventId: string
  title: string
  summary: string
  status: 'pending' | 'accepted' | 'rejected'
  receivedAt: string
  decidedAt: string | null
}

export const new303Api = {
  createEndpoint: (label: string) =>
    sendJson<{
      uuid: string
      label: string
      secret: string
      ingestPath: string
      createdAt: string
    }>(`${API_BASE}/webhooks/endpoints`, 'POST', { label }),
  listEndpoints: () =>
    getJson<{ items: WebhookEndpointRow[] }>(
      `${API_BASE}/webhooks/endpoints`,
    ),
  removeEndpoint: (uuid: string) =>
    sendJson<null>(
      `${API_BASE}/webhooks/endpoints/${encodeURIComponent(uuid)}`,
      'DELETE',
    ),
  inbox: (status?: string) =>
    getJson<{ items: InboxRow[] }>(
      `${API_BASE}/webhooks/inbox${
        status ? `?status=${encodeURIComponent(status)}` : ''
      }`,
    ),
  decide: (id: number, accept: boolean) =>
    sendJson<{ id: number; status: string; decidedAt: string | null }>(
      `${API_BASE}/webhooks/inbox/${id}/${accept ? 'accept' : 'reject'}`,
      'POST',
    ),
}

// ---- NEW-304 管理员签名钥轮换 ----------------------------------------------

export interface WebhookKeyRow {
  keyId: string
  state: string
  createdAt: string
  windowEndsAt: string | null
  verifiedToday: number
  verifiedTotal: number
}

export const new304Api = {
  snapshot: () =>
    getJson<{ keys: WebhookKeyRow[]; honestyNote: string }>(
      `${API_BASE}/admin/webhook-keys`,
    ),
  rotate: (stepUpToken: string, windowMinutes: number) =>
    sendJson<{
      keyId: string
      secret: string
      windowMinutes: number
      previousKeyId: string | null
    }>(`${API_BASE}/admin/webhook-keys/rotate`, 'POST', { windowMinutes }, {
      'X-Lumi-Step-Up': stepUpToken,
    }),
}

// ---- NEW-305 死信处理 -------------------------------------------------------

export interface DeadLetterRow {
  id: number
  endpointUuid: string
  eventId: string
  reason: string
  payloadSummary: Record<string, unknown>
  status: 'pending' | 'replayed'
  failedAt: string
  replayedAt: string | null
}

export const new305Api = {
  list: (status?: string) =>
    getJson<{ items: DeadLetterRow[] }>(
      `${API_BASE}/webhooks/dead-letters${
        status ? `?status=${encodeURIComponent(status)}` : ''
      }`,
    ),
  replay: (id: number, rawPayload?: string) =>
    sendJson<{
      replayed: boolean
      stored?: number
      reason?: string
      note?: string
    }>(
      `${API_BASE}/webhooks/dead-letters/${id}/replay`,
      'POST',
      rawPayload ? { rawPayload } : {},
    ),
}

// ---- NEW-306 写暂停状态/恢复 -----------------------------------------------

export interface SchemaPauseStatus {
  writePaused: boolean
  pauseReason: string | null
  drift: { missing?: string[]; typeChanged?: string[] } | null
}

export const new306Api = {
  status: (uuid: string) =>
    getJson<SchemaPauseStatus>(sourceUrl(uuid, '/schema-pause')),

  resume: (uuid: string, fieldMap?: Record<string, string>) =>
    sendJson<{
      resumed: boolean
      note?: string
      sampledItems?: number
    }>(
      sourceUrl(uuid, '/schema-resume'),
      'POST',
      { fieldMap: fieldMap ?? undefined },
    ),
}

// ---- NEW-307 每日条目配额 ---------------------------------------------------

export interface IntakeQuotaSnapshot {
  sourceUuid: string
  configured: boolean
  maxItemsPerDay: number | null
  used: number
  pending: number
  remaining: number | null
  dayKey: string
  windowReset: string
  honestyNote: string
}

export const new307Api = {
  get: (uuid: string) =>
    getJson<IntakeQuotaSnapshot>(sourceUrl(uuid, '/intake-quota')),
  put: (uuid: string, maxItemsPerDay: number) =>
    sendJson<{ maxItemsPerDay: number }>(
      sourceUrl(uuid, '/intake-quota'),
      'PUT',
      { maxItemsPerDay },
    ),
  remove: (uuid: string) =>
    sendJson<null>(sourceUrl(uuid, '/intake-quota'), 'DELETE'),
}

// ---- NEW-308 外发订阅 -------------------------------------------------------

export interface OutSubscriptionRow {
  id: number
  eventType: string
  targetUrl: string
  targetHost: string
  state: 'pending' | 'active' | 'paused' | 'revoked'
  createdAt: string
  verifiedAt: string | null
}

export interface OutSubscriptionCreated {
  id: number
  eventType: string
  targetUrl: string
  state: string
  secret: string
  verifyToken: string
  createdAt: string
}

export const new308Api = {
  list: () =>
    getJson<{ items: OutSubscriptionRow[]; eventTypes: string[] }>(
      `${API_BASE}/webhooks/out-subscriptions`,
    ),
  create: (eventType: string, targetUrl: string) =>
    sendJson<OutSubscriptionCreated>(
      `${API_BASE}/webhooks/out-subscriptions`,
      'POST',
      { eventType, targetUrl },
    ),
  verify: (id: number, token: string) =>
    sendJson<{ id: number; state: string }>(
      `${API_BASE}/webhooks/out-subscriptions/${id}/verify`,
      'POST',
      { token },
    ),
  pause: (id: number) =>
    sendJson<{ id: number; state: string }>(
      `${API_BASE}/webhooks/out-subscriptions/${id}/pause`,
      'POST',
    ),
  resume: (id: number) =>
    sendJson<{ id: number; state: string }>(
      `${API_BASE}/webhooks/out-subscriptions/${id}/resume`,
      'POST',
    ),
  revoke: (id: number) =>
    sendJson<null>(`${API_BASE}/webhooks/out-subscriptions/${id}`, 'DELETE'),
  dispatch: (eventType: string, data: Record<string, unknown>) =>
    sendJson<{ results: { subscriptionId: number; ok: boolean }[] }>(
      `${API_BASE}/webhooks/out-subscriptions/dispatch`,
      'POST',
      { eventType, data },
    ),
}

// ---- NEW-309 投递回执 -------------------------------------------------------

export interface DeliveryRow {
  id: number
  subscriptionId: number
  eventType: string
  eventUuid: string
  idempotencyKey: string
  attempt: number
  status: 'success' | 'failed' | 'exhausted'
  responseStatus: number | null
  responseExcerpt: string | null
  nextRetryAt: string | null
  createdAt: string
  finishedAt: string | null
}

export const new309Api = {
  list: (subscriptionId?: number) =>
    getJson<{ items: DeliveryRow[] }>(
      `${API_BASE}/webhooks/deliveries${
        subscriptionId !== undefined
          ? `?subscriptionId=${encodeURIComponent(String(subscriptionId))}`
          : ''
      }`,
    ),
  retry: (id: number) =>
    sendJson<DeliveryRow>(
      `${API_BASE}/webhooks/deliveries/${id}/retry`,
      'POST',
      {},
    ),
  processDue: () =>
    sendJson<{ processed: number; due: number}>(
      `${API_BASE}/webhooks/deliveries/process-due`,
      'POST',
      {},
    ),
}

// ---- NEW-310 接入配置转移包 -------------------------------------------------

export interface TransferSourceEntry {
  credentialRef: string
  name: string
  endpoint: string
  itemsExpr: string
  fieldMap: Record<string, string>
  pagination: Record<string, unknown>
  maxRunsPerHour: number
}

export interface TransferBundle {
  version: number
  kind: string
  exportedAt: string
  sources: TransferSourceEntry[]
  honestyNote: string
}

export const new310Api = {
  export: () =>
    getJson<TransferBundle>(`${API_BASE}/api-sources/transfer-bundle`),
  importBundle: (
    bundle: unknown,
    credentials: Record<string, string>,
  ) =>
    sendJson<{
      created: { uuid: string; name: string; credentialNote: string }[]
      merged: { uuid: string; name: string }[]
      skipped: { name: string; reason: string }[]
      digest: string
    }>(`${API_BASE}/api-sources/transfer-bundle/import`, 'POST', {
      bundle,
      credentials,
    }),
}
