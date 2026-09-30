/** NEW-391..400 通知、发布变化与帮助闭环 — 本组专属 API 调用。
 *
 * 后端真源：services/bff/src/lumirss/routers/new391..400_*.py；
 * 类型按 BFF 稳定 DTO 手写（组内端点尚未进 OpenAPI 生成集——诚实注
 * 释，不假装 generated）。URL 全部相对 /api/v1/*；无 step-up 面。
 */

import { ApiError } from './client'

const API_BASE = '/api/v1'

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
  let type = 'request_failed'
  let message = messageOf(parsed, `请求失败（${response.status}）`)
  if (parsed !== null && typeof parsed === 'object') {
    const err = (parsed as { error?: { type?: string } }).error
    if (err?.type) type = err.type
  }
  return new ApiError(response.status, type, message, null, null)
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
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const response = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) throw await toApiError(response)
  const text = await response.text()
  return (text ? (JSON.parse(text) as T) : (null as T))
}

// ---- NEW-391 通知收件箱 ------------------------------------------------------

export type NotificationKind =
  | 'task_completed'
  | 'task_failed'
  | 'share_event'
  | 'help_answered'

export interface NotificationItem {
  id: string
  kind: NotificationKind
  source: string
  title: string
  body: string
  ref: string
  actionable: boolean
  invalidReason: string | null
  revokedAt: string | null
  occurredAt: string
  createdAt: string
  readAt: string | null
}

export interface NotificationList {
  items: NotificationItem[]
  counts: Record<string, number>
  unread: number
}

export const fetchNotifications = (params: {
  kind?: NotificationKind
  unreadOnly?: boolean
}) => {
  const query = new URLSearchParams()
  if (params.kind) query.set('kind', params.kind)
  if (params.unreadOnly) query.set('unreadOnly', 'true')
  const suffix = query.toString()
  return getJson<NotificationList>(
    `${API_BASE}/notifications${suffix ? `?${suffix}` : ''}`,
  )
}

export const markNotificationRead = (id: string) =>
  sendJson<NotificationItem>(`${API_BASE}/notifications/${id}/read`, 'POST')

export const markAllNotificationsRead = (kind: NotificationKind | null) =>
  sendJson<{ marked: number }>(
    `${API_BASE}/notifications/read-all`,
    'POST',
    kind ? { kind } : {},
  )

export const dismissNotification = (id: string) =>
  sendJson<{ dismissed: boolean }>(`${API_BASE}/notifications/${id}`, 'DELETE')

export const registerRevocation = (id: string, reason: string) =>
  sendJson<{ notificationId: string; invalidReason: string; revokedAt: string }>(
    `${API_BASE}/notifications/${id}/revocation`,
    'POST',
    { reason },
  )

// ---- NEW-392 聚合规则 --------------------------------------------------------

export interface AggregationRule {
  id: string
  kind: string
  source: string
  label: string
  enabled: boolean
  createdAt: string
}

export interface GroupedNotifications {
  groups: {
    kind: string
    source: string
    total: number
    unread: number
    items: NotificationItem[]
  }[]
  flat: NotificationItem[]
  ruleCount: number
}

export const fetchAggregationRules = () =>
  getJson<{ rules: AggregationRule[] }>(
    `${API_BASE}/notifications/aggregation-rules`,
  )

export const createAggregationRule = (kind: string, source: string, label: string) =>
  sendJson<AggregationRule>(`${API_BASE}/notifications/aggregation-rules`, 'POST', {
    kind,
    source,
    label: label || null,
  })

export const setAggregationRuleEnabled = (id: string, enabled: boolean) =>
  sendJson<AggregationRule>(
    `${API_BASE}/notifications/aggregation-rules/${id}/enabled`,
    'POST',
    { enabled },
  )

export const deleteAggregationRule = (id: string) =>
  sendJson<{ deleted: boolean }>(
    `${API_BASE}/notifications/aggregation-rules/${id}`,
    'DELETE',
  )

export const fetchGroupedNotifications = () =>
  getJson<GroupedNotifications>(`${API_BASE}/notifications/grouped`)

// ---- NEW-393 静默时段 --------------------------------------------------------

export interface QuietHoursSetting {
  enabled: boolean
  startHHMM: string | null
  endHHMM: string | null
  timeZone: string | null
  updatedAt: string | null
}

export interface QuietSummary {
  enabled: boolean
  inQuiet: boolean
  quietEndsAt: string | null
  windowStart: string | null
  unreadTotal: number
  unreadDuringWindow: number
  byKind: Record<string, number>
  note: string
}

export const fetchQuietHours = () =>
  getJson<QuietHoursSetting>(`${API_BASE}/notifications/quiet-hours`)

export const putQuietHours = (body: {
  startHHMM: string
  endHHMM: string
  timeZone: string
  enabled: boolean
}) => sendJson<QuietHoursSetting>(`${API_BASE}/notifications/quiet-hours`, 'PUT', body)

export const fetchQuietSummary = () =>
  getJson<QuietSummary>(`${API_BASE}/notifications/quiet-summary`)

// ---- NEW-395 体验清单 --------------------------------------------------------

export interface ExperienceFeature {
  id: string
  title: string
  entry: string
  adminOnly: boolean
  mark: { status: 'learned' | 'later'; updatedAt: string } | null
}

export const fetchExperience = () =>
  getJson<{ version: string | null; features: ExperienceFeature[]; note?: string }>(
    `${API_BASE}/whats-new/experience`,
  )

export const markExperience = (featureId: string, status: 'learned' | 'later') =>
  sendJson<{ featureId: string; status: string }>(
    `${API_BASE}/whats-new/experience/${featureId}/mark`,
    'POST',
    { status },
  )

// ---- NEW-396 回退偏好 --------------------------------------------------------

export interface InteractionModeSurface {
  key: string
  label: string
  newLabel: string
  classicLabel: string
  mode: 'new' | 'classic'
  chosenMode: string | null
  effectiveMode: string
  expired: boolean
  expiresAt: string | null
  compatDays: number
  setAt: string | null
}

export const fetchInteractionModes = () =>
  getJson<{ surfaces: InteractionModeSurface[]; note: string }>(
    `${API_BASE}/interaction-modes`,
  )

export const putInteractionMode = (surface: string, mode: 'new' | 'classic') =>
  sendJson<InteractionModeSurface>(`${API_BASE}/interaction-modes/${surface}`, 'PUT', {
    mode,
  })

// ---- NEW-397 服务状态 --------------------------------------------------------

export interface ServiceStatusSurface {
  key: string
  label: string
  status: string
  detail: string
  checkedAt: string | null
  history: { status: string; checkedAt: string }[]
}

export interface ServiceStatusPage {
  surfaces: ServiceStatusSurface[]
  notes: string[]
}

export const fetchServiceStatus = () =>
  getJson<ServiceStatusPage>(`${API_BASE}/status/services`)

export const runServiceStatusCheck = () =>
  sendJson<ServiceStatusPage>(`${API_BASE}/status/services/check`, 'POST')

// ---- NEW-398 处理单 ----------------------------------------------------------

export interface RunbookSpec {
  code: string
  title: string
  verified: string
  steps: { index: number; title: string; detail: string }[]
}

export interface RunbookSessionDetail {
  id: string
  code: string
  title: string
  status: string
  steps: { index: number; title: string; detail: string }[]
  outcomes: { stepIndex: number; outcome: string; note: string; recordedAt: string }[]
  escalatedNote: string
  material: {
    code: string
    version: string
    steps: { stepIndex: number; outcome: string }[]
    userNote: string
    generatedAt: string
  } | null
}

export const fetchRunbooks = () =>
  getJson<{ runbooks: RunbookSpec[] }>(`${API_BASE}/support/runbooks`)

export const openRunbookSession = (code: string) =>
  sendJson<RunbookSessionDetail>(`${API_BASE}/support/runbooks/${code}/sessions`, 'POST')

export const recordRunbookStep = (
  sessionId: string,
  stepIndex: number,
  outcome: 'tried' | 'helped' | 'no_effect' | 'skipped',
  note: string,
) =>
  sendJson<{ sessionId: string; stepIndex: number; outcome: string }>(
    `${API_BASE}/support/runbooks/sessions/${sessionId}/steps`,
    'POST',
    { stepIndex, outcome, note: note || null },
  )

export const escalateRunbookSession = (sessionId: string, note: string) =>
  sendJson<{ id: string; status: string; material: RunbookSessionDetail['material'] }>(
    `${API_BASE}/support/runbooks/sessions/${sessionId}/escalate`,
    'POST',
    { note },
  )

// ---- NEW-399 文档反馈 --------------------------------------------------------

export interface DocFeedbackEntry {
  id: string
  docPath: string
  anchor: string
  anchorFound: boolean | null
  version: string
  question: string
  status: 'open' | 'revised'
  revisionNote: string
  reply: string
  createdAt: string
  resolvedAt: string | null
}

export const submitDocFeedback = (body: {
  docPath: string
  anchor: string
  question: string
}) => sendJson<DocFeedbackEntry>(`${API_BASE}/help/feedback`, 'POST', body)

export const fetchOwnDocFeedback = () =>
  getJson<{ items: DocFeedbackEntry[] }>(`${API_BASE}/help/feedback`)

export const fetchAdminDocFeedback = (status: 'open' | 'revised' | null) =>
  getJson<{ items: DocFeedbackEntry[] }>(
    `${API_BASE}/admin/help/feedback${status ? `?status=${status}` : ''}`,
  )

export const resolveDocFeedback = (
  id: string,
  revisionNote: string,
  reply: string,
) =>
  sendJson<DocFeedbackEntry>(
    `${API_BASE}/admin/help/feedback/${id}/resolve`,
    'POST',
    { revisionNote, reply },
  )

// ---- NEW-400 使用清理 --------------------------------------------------------

export interface CleanupModule {
  key: string
  label: string
  description: string
  enabledCount: number
  closure: { retention: 'keep' | 'delete'; detail: string; closedAt: string } | null
}

export const fetchModuleCleanup = () =>
  getJson<{ modules: CleanupModule[]; note: string }>(
    `${API_BASE}/settings/module-cleanup`,
  )

export const closeModule = (key: string, retention: 'keep' | 'delete') =>
  sendJson<{ moduleId: string; retention: string; detail: string; closedAt: string }>(
    `${API_BASE}/settings/module-cleanup/${key}/close`,
    'POST',
    { retention },
  )
