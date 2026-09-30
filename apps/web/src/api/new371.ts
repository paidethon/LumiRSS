/** NEW-371..380 运行治理组 — 本组专属 API 调用。
 *
 * 后端真源：services/bff/src/lumirss/routers/new37*.py / new380*.py；
 * 类型按 BFF 稳定 DTO 手写（组内端点尚未进 OpenAPI 生成集——诚实注
 * 释，不假装 generated）。URL 全部相对 /api/v1/*；敏感 mutation 携带
 * takeStepUpHeaders()（lib/step-up 的单次令牌），403 step_up_required
 * 映射为 client.ApiError（type=step_up_required，extra 携带服务端声
 * 明的作用域），供管理台统一的密码对话框流程消费。
 */

import { ApiError } from './client'
import { takeStepUpHeaders } from '../lib/step-up'

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
  let extra: Record<string, string> | null = null
  if (parsed !== null && typeof parsed === 'object') {
    const err = (parsed as { error?: { type?: string; operation?: string; targetUserId?: string } }).error
    if (err?.type) type = err.type
    if (err?.operation) {
      extra = { operation: err.operation, ...(err.targetUserId ? { targetUserId: err.targetUserId } : {}) }
    }
  }
  return new ApiError(response.status, type, message, null, extra)
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
  stepUp = false,
): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (stepUp) Object.assign(headers, takeStepUpHeaders())
  const response = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) throw await toApiError(response)
  const text = await response.text()
  return (text ? (JSON.parse(text) as T) : (null as T))
}

// ---- NEW-371 后台任务日历 ----------------------------------------------------

export interface TaskKindView {
  kind: string
  label: string
  intervalSeconds: number | null
  scheduled: boolean
  slotState: string
  plannedNext: string | null
  pause: { active: boolean; reason: string; impact: string; createdAt: string }
  pauseEnforced: boolean
  enforcedBy: 'loop' | 'declared'
  impact: string | null
  pauseNote?: string
}

export interface TaskCalendar {
  kinds: TaskKindView[]
  recentRuns: { kind: string; status: string; startedAt: string; error: string | null }[]
  ownScopeResults: { kind: string; status: string; startedAt: string }[]
  notes: string[]
}

export const getTaskCalendar = () => getJson<TaskCalendar>(`${API_BASE}/admin/task-calendar`)

export const pauseTaskKind = (kind: string, reason: string, impact: string) =>
  sendJson<{ kind: string; paused: boolean }>(
    `${API_BASE}/admin/task-calendar/${kind}/pause`,
    'POST',
    { reason, impact },
    true,
  )

export const resumeTaskKind = (kind: string) =>
  sendJson<{ kind: string; paused: boolean }>(
    `${API_BASE}/admin/task-calendar/${kind}/resume`,
    'POST',
    undefined,
    true,
  )

// ---- NEW-372 任务优先级 ------------------------------------------------------

export interface TaskPriorityRow {
  userId: string
  username: string | null
  priority: number
  priorityLabel: string
  updatedAt: string | null
}

export interface TaskPriorityList {
  items: TaskPriorityRow[]
  appliesAt: string
  preemption: boolean
}

export const getTaskPriorities = () => getJson<TaskPriorityList>(`${API_BASE}/admin/task-priorities`)

export const setTaskPriority = (userId: string, priority: string) =>
  sendJson<{ userId: string; priority: number; appliesAt: string; preemption: boolean }>(
    `${API_BASE}/admin/task-priorities/${userId}`,
    'PUT',
    { priority },
  )

export const clearTaskPriority = (userId: string) =>
  sendJson<{ cleared: boolean }>(`${API_BASE}/admin/task-priorities/${userId}`, 'DELETE')

// ---- NEW-373 维护通知演练 ----------------------------------------------------

export interface RolePreview {
  role: string
  banner: { title: string; notice: string; startsAt: string; endsAt: string }
  roleNote: string
}

export interface MaintenanceDrill {
  drillId: string
  scheduled: false
  scheduledNote: string
  preview: Record<string, RolePreview>
}

export interface MaintenanceWindow {
  id: string
  title: string
  notice: string
  startsAt: string
  endsAt: string
  status: string
}

export interface WindowFields {
  title: string
  notice: string
  startsAt: string
  endsAt: string
}

export const createMaintenanceDrill = (fields: WindowFields) =>
  sendJson<MaintenanceDrill>(`${API_BASE}/admin/maintenance/drill`, 'POST', fields)

export const scheduleMaintenanceWindow = (fields: WindowFields) =>
  sendJson<MaintenanceWindow>(`${API_BASE}/admin/maintenance/windows`, 'POST', fields, true)

export const settleMaintenanceWindow = (id: string, status: 'completed' | 'cancelled') =>
  sendJson<{ id: string; status: string }>(
    `${API_BASE}/admin/maintenance/windows/${id}/settle`,
    'POST',
    { status },
  )

export const getMaintenanceNotice = () =>
  getJson<{ active: boolean; current: MaintenanceWindow | null; upcoming: MaintenanceWindow | null }>(
    `${API_BASE}/maintenance/notice`,
  )

// ---- NEW-374 用户资源账单 ----------------------------------------------------

export interface ResourceBill {
  userId: string
  counts: Record<string, number>
  storage: { databaseBytes: number; assetBytes: number; totalBytes: number }
  compute: { aiCallsToday: number | null; recentBackupSeconds: number | null }
  computedAt: string
  contentNote: string
  recentViews?: { viewerId: string; viewedAt: string }[]
}

export const getOwnResourceBill = () => getJson<ResourceBill>(`${API_BASE}/account/resource-bill`)

export const getAdminResourceBill = (userId: string) =>
  getJson<ResourceBill>(`${API_BASE}/admin/users/${userId}/resource-bill`)

// ---- NEW-375 配额变更批次 ----------------------------------------------------

export interface QuotaBatchPreview {
  batchId: string
  status: string
  count: number
  preview: {
    userId: string
    username?: string | null
    outcome: string
    reason?: string
    currentCaps: Record<string, number> | null
    proposed: Record<string, number> | null
    clear?: boolean
    overQuotaImpact: {
      aiCallsToday: number
      newDailyCap: number
      projectedDeniedMin: number
      note: string
    } | null
  }[]
}

export const previewQuotaBatch = (changes: { userId: string; caps?: Record<string, number>; clear?: boolean }[]) =>
  sendJson<QuotaBatchPreview>(`${API_BASE}/admin/quota-batches/preview`, 'POST', { changes })

export const executeQuotaBatch = (batchId: string) =>
  sendJson<{ batchId: string; status: string; results: { userId: string; outcome: string; detail: string | null }[] }>(
    `${API_BASE}/admin/quota-batches/${batchId}/execute`,
    'POST',
    undefined,
    true,
  )

// ---- NEW-376 实例配置草案 ----------------------------------------------------

export interface ConfigDraft {
  draftId: string
  key: string
  keyLabel?: string
  currentValue: string
  draftValue: string
  validation: { ok: boolean; checks: string[] }
  effectiveNotes: string[]
  status: string
  differs?: boolean
}

export const getConfigDraftSchema = () =>
  getJson<{ keys: { key: string; type: string; label: string }[] }>(
    `${API_BASE}/admin/config-drafts/schema`,
  )

export const createConfigDraft = (key: string, value: string) =>
  sendJson<ConfigDraft>(`${API_BASE}/admin/config-drafts`, 'POST', { key, value })

export const applyConfigDraft = (draftId: string) =>
  sendJson<{ draftId: string; status: string }>(
    `${API_BASE}/admin/config-drafts/${draftId}/apply`,
    'POST',
    undefined,
    true,
  )

export const discardConfigDraft = (draftId: string) =>
  sendJson<{ draftId: string; status: string }>(
    `${API_BASE}/admin/config-drafts/${draftId}/discard`,
    'POST',
  )

// ---- NEW-377 后台任务阻塞定位 ------------------------------------------------

export interface TaskBlocker {
  category: string
  scope?: string
  userId?: string
  aiCallsToday?: number
  dailyCap?: number
  pending?: number
  errorProbes?: number
  scopeKind?: string
  expiresAt?: string
  count?: number
  reason?: string
  safeAction: string
}

export interface TaskBlockerReport {
  blockers: TaskBlocker[]
  counts: Record<string, number>
  safeActions: Record<string, string>
  diagnosedAt: string
  notes: string[]
}

export const getTaskBlockers = () => getJson<TaskBlockerReport>(`${API_BASE}/admin/task-blockers`)

// ---- NEW-378 实例功能依赖图 --------------------------------------------------

export interface FeatureDep {
  key: string
  kind: string
  status: 'configured' | 'missing' | 'unknown'
  detail: string
  probedAt: string | null
}

export interface FeatureDependencyGraph {
  features: { key: string; label: string; deps: FeatureDep[]; ready: boolean }[]
  probedAt?: string
  notes: string[]
}

export const getFeatureDependencies = () =>
  getJson<FeatureDependencyGraph>(`${API_BASE}/admin/feature-dependencies`)

export const probeFeatureDependencies = () =>
  sendJson<FeatureDependencyGraph>(`${API_BASE}/admin/feature-dependencies/probe`, 'POST')

// ---- NEW-379 用户问题工单 ----------------------------------------------------

export interface SupportTicketRow {
  id: string
  subject: string
  status: string
  assignedTo: string | null
  createdAt: string
}

export interface SupportTicketDetail extends SupportTicketRow {
  body: string
  submittedBy: string
  replies: { authorId: string; authorRole: string; body: string; createdAt: string }[]
}

export const listSupportTickets = () =>
  getJson<{ items: SupportTicketRow[]; counts: Record<string, number> }>(
    `${API_BASE}/admin/tickets`,
  )

export const getSupportTicket = (id: string) =>
  getJson<SupportTicketDetail>(`${API_BASE}/admin/tickets/${id}`)

export const assignSupportTicket = (id: string, adminUserId: string) =>
  sendJson<{ id: string; status: string; assignedTo: string }>(
    `${API_BASE}/admin/tickets/${id}/assign`,
    'POST',
    { adminUserId },
  )

export const replySupportTicket = (id: string, body: string) =>
  sendJson<{ id: string; status: string }>(`${API_BASE}/admin/tickets/${id}/replies`, 'POST', { body })

export const closeSupportTicket = (id: string) =>
  sendJson<{ id: string; status: string }>(`${API_BASE}/admin/tickets/${id}/close`, 'POST')

// ---- NEW-380 运维交接摘要 ----------------------------------------------------

export interface HandoffPayload {
  generatedAt: string
  schemaVersion: number
  deploy: { available: boolean; reason: string | null; imageTag: string | null }
  openItems: {
    tickets: { id: string; subject: string; status: string }[]
    taskPauses: { kind: string }[]
    quotaBatchesDraft: { batchId: string }[]
    configDrafts: { draftId: string; key: string }[]
    maintenanceWindows: { id: string; title: string }[]
    dependencyGaps: { dep: string; detail: string }[]
    recentBlockers: { category: string; diagnosedAt: string }[]
  }
  secretsInventory: { key: string; configured: boolean }[]
  redactionNote: string
}

export const createHandoffSummary = () =>
  sendJson<{ summaryId: string; confirmed: boolean; payload: HandoffPayload }>(
    `${API_BASE}/admin/handoff-summaries`,
    'POST',
  )

export const confirmHandoffSummary = (id: string) =>
  sendJson<{ summaryId: string; confirmed: boolean }>(
    `${API_BASE}/admin/handoff-summaries/${id}/confirm`,
    'POST',
    undefined,
    true,
  )

export const exportHandoffSummary = (id: string) =>
  getJson<{ summaryId: string; exportedAt: string; payload: HandoffPayload; redactionNote: string }>(
    `${API_BASE}/admin/handoff-summaries/${id}/export`,
  )
