/** NEW-221..230 队列和阅读计划的用户决策 —— BFF HTTP 调用（feature 本地）。
 *
 * 与 api/client.ts 同一约定（相对 /api/v1/*、cookie 会话、稳定错误
 * 信封 → ApiError），但作为 NEW 文件独立成模块，避免触碰 9k 行共享
 * client；复用其 ApiError 类型与既有 getTodayQueue。 */

import { ApiError } from '../../api/client'
import type { QueueItemView } from '../../api/types'

const API_BASE = '/api/v1'

async function toApiError(response: Response): Promise<ApiError> {
  let type = 'unknown_error'
  let message = `请求失败（${response.status}）。`
  try {
    const data = (await response.json()) as {
      error?: { type?: string; message?: string }
      detail?: unknown
    }
    if (data?.error?.type) {
      type = data.error.type
      message = data.error.message ?? message
    } else if (Array.isArray(data?.detail)) {
      type = 'invalid_request'
      message = '请求参数不合法。'
    }
  } catch {
    // 非 JSON 错误体 → 保留 fallback。
  }
  return new ApiError(response.status, type, message)
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as T
}

async function send<T>(
  path: string,
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    ...(body !== undefined
      ? { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } }
      : {}),
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

// ---- NEW-221 分时段阅读队列 -------------------------------------------------

export interface QueueSlot {
  id: string
  name: string
  position: number
  createdAt: string
  lastOpenedAt: string | null
  pendingCount: number
  doneCount: number
}

export interface QueueSlotItem {
  id: string
  slotId: string
  slotName?: string | null
  itemRef: string
  position: number
  status: 'pending' | 'done' | 'carried'
  doneAt: string | null
  carriedAt: string | null
  carriedToSlot: string | null
  title: string | null
}

export interface QueueSlotDetail extends QueueSlot {
  items: QueueSlotItem[]
}

export interface QueueSlotOpen extends QueueSlotDetail {
  resume: { pendingCount: number; nextItemRef: string | null; nextTitle: string | null }
}

export const listQueueSlots = (signal?: AbortSignal) =>
  request<{ slots: QueueSlot[] }>(`${API_BASE}/queue/slots`, signal)

export const createQueueSlot = (name: string) =>
  send<QueueSlot>(`${API_BASE}/queue/slots`, 'POST', { name })

export const deleteQueueSlot = (slotId: string) =>
  send<void>(`${API_BASE}/queue/slots/${encodeURIComponent(slotId)}`, 'DELETE')

export const openQueueSlot = (slotId: string) =>
  send<QueueSlotOpen>(`${API_BASE}/queue/slots/${encodeURIComponent(slotId)}/open`, 'POST')

export const getQueueSlot = (slotId: string, signal?: AbortSignal) =>
  request<QueueSlotDetail>(
    `${API_BASE}/queue/slots/${encodeURIComponent(slotId)}`,
    signal,
  )

export const addQueueSlotItem = (slotId: string, itemRef: string) =>
  send<QueueSlotItem & { outcome: string }>(
    `${API_BASE}/queue/slots/${encodeURIComponent(slotId)}/items`,
    'POST',
    { itemRef },
  )

export const setQueueSlotItemDone = (itemId: string, done: boolean) =>
  send<QueueSlotItem>(
    `${API_BASE}/queue/slot-items/${encodeURIComponent(itemId)}/done`,
    'POST',
    { done },
  )

export const carryOverQueueSlot = (slotId: string, targetSlotId: string) =>
  send<{ moved: number }>(
    `${API_BASE}/queue/slots/${encodeURIComponent(slotId)}/carry-over`,
    'POST',
    { targetSlotId },
  )

// ---- NEW-222 队列依赖关系 ---------------------------------------------------

export interface PrereqEntry {
  id: string
  prereqRef: string
  title: string | null
  met: boolean
  basis: string
}

export interface PrereqItemView {
  itemRef: string
  prereqs: PrereqEntry[]
  unmetCount: number
  advisory: boolean
  note: string
}

export const getItemPrereqs = (itemRef: string, signal?: AbortSignal) =>
  request<PrereqItemView>(
    `${API_BASE}/queue/prereqs?itemRef=${encodeURIComponent(itemRef)}`,
    signal,
  )

export const addQueuePrereq = (itemRef: string, prereqRef: string) =>
  send<{ id: string; outcome: string }>(`${API_BASE}/queue/prereqs`, 'POST', {
    itemRef,
    prereqRef,
  })

export const deleteQueuePrereq = (prereqId: string) =>
  send<void>(`${API_BASE}/queue/prereqs/${encodeURIComponent(prereqId)}`, 'DELETE')

// ---- NEW-223 队列工作量预览 ---------------------------------------------------

export interface SpeedView {
  charsPerMinute: number
  customized: boolean
  updatedAt: string | null
  note: string | null
}

export interface EstimateItem {
  itemRef: string
  title: string | null
  minutes: number | null
}

export interface EstimateView {
  charsPerMinute: number
  items: EstimateItem[]
  totalKnownMinutes: number
  unknownCount: number
  basis: string
  note: string
}

export interface CompressionOption {
  key: string
  label: string
  refs: string[]
  estimatedMinutes: number
}

export const getReadingSpeed = (signal?: AbortSignal) =>
  request<SpeedView>(`${API_BASE}/queue/workload/speed`, signal)

export const setReadingSpeed = (charsPerMinute: number) =>
  send<SpeedView>(`${API_BASE}/queue/workload/speed`, 'PUT', { charsPerMinute })

export const estimateWorkload = (refs: string[]) =>
  send<EstimateView>(`${API_BASE}/queue/workload/estimate`, 'POST', { refs })

export const suggestCompressions = (refs: string[]) =>
  send<{ options: CompressionOption[]; note: string }>(
    `${API_BASE}/queue/workload/compressions`,
    'POST',
    { refs },
  )

// ---- NEW-224 阅读预约清单 -----------------------------------------------------

export interface ReadingReminder {
  id: string
  itemRef: string
  remindAt: string
  note: string | null
  status: 'active' | 'done' | 'cancelled'
  remindedAt: string | null
  title: string | null
  due?: boolean | null
}

export const listReminders = (signal?: AbortSignal) =>
  request<{ items: ReadingReminder[]; channel: string; note: string }>(
    `${API_BASE}/reading/reminders`,
    signal,
  )

export const createReminder = (itemRef: string, remindAt: string, note?: string) =>
  send<ReadingReminder>(`${API_BASE}/reading/reminders`, 'POST', {
    itemRef,
    remindAt,
    ...(note ? { note } : {}),
  })

export const rescheduleReminder = (id: string, remindAt: string) =>
  send<ReadingReminder>(
    `${API_BASE}/reading/reminders/${encodeURIComponent(id)}/reschedule`,
    'POST',
    { remindAt },
  )

export const cancelReminder = (id: string) =>
  send<ReadingReminder>(
    `${API_BASE}/reading/reminders/${encodeURIComponent(id)}/cancel`,
    'POST',
  )

export const completeReminder = (id: string) =>
  send<ReadingReminder>(
    `${API_BASE}/reading/reminders/${encodeURIComponent(id)}/complete`,
    'POST',
  )

// ---- NEW-225 积压处理向导 ------------------------------------------------------

export interface WizardGroup {
  feedUrl: string
  feedTitle: string | null
  unreadCount: number
  sample: { title: string }[]
}

export interface WizardPreview {
  olderThanDays: number
  groups: WizardGroup[]
  keptDecisionsExcluded: number
  truncated: boolean
  effectiveExclusions: string[]
}

export interface ArchivePreview {
  count: number
  confirmToken: string
  effectiveExclusions: string[]
}

export const wizardPreview = (olderThanDays: number) =>
  send<WizardPreview>(`${API_BASE}/backlog/wizard/preview`, 'POST', { olderThanDays })

export const wizardKeep = (feedUrl: string, olderThanDays: number) =>
  send<{ outcome: string }>(`${API_BASE}/backlog/wizard/keep`, 'POST', {
    feedUrl,
    olderThanDays,
  })

export const wizardArchivePreview = (feedUrl: string, olderThanDays: number) =>
  send<ArchivePreview>(`${API_BASE}/backlog/wizard/archive-preview`, 'POST', {
    feedUrl,
    olderThanDays,
  })

export const wizardArchiveApply = (
  feedUrl: string,
  olderThanDays: number,
  confirmToken: string,
) =>
  send<{ applied: number; failed: number; undoAvailable: boolean }>(
    `${API_BASE}/backlog/wizard/archive-apply`,
    'POST',
    { feedUrl, olderThanDays, confirmToken },
  )

export const wizardStage = (
  feedUrl: string,
  olderThanDays: number,
  targetSlotId: string,
) =>
  send<{ stagedCount: number; skippedAlreadyInSlot: number }>(
    `${API_BASE}/backlog/wizard/stage`,
    'POST',
    { feedUrl, olderThanDays, targetSlotId },
  )

// ---- NEW-226 队列容量上限 ------------------------------------------------------

export interface CapacitySettings {
  capacity: number | null
  enabled: boolean
  note: string | null
}

export interface CapacityCandidate {
  id: string
  itemRef: string
  status: string
  title: string | null
}

export interface CapacityPendingView {
  capacity: number | null
  enabled: boolean
  queueCount: number
  items: CapacityCandidate[]
}

export const getQueueCapacity = (signal?: AbortSignal) =>
  request<CapacitySettings>(`${API_BASE}/queue/capacity`, signal)

export const setQueueCapacity = (capacity: number, enabled: boolean) =>
  send<CapacitySettings>(`${API_BASE}/queue/capacity`, 'PUT', { capacity, enabled })

export const offerQueueItem = (itemRef: string) =>
  send<{ id?: string; itemRef: string; outcome: string; note?: string | null }>(
    `${API_BASE}/queue/capacity/offer`,
    'POST',
    { itemRef },
  )

export const listCapacityPending = (signal?: AbortSignal) =>
  request<CapacityPendingView>(`${API_BASE}/queue/capacity/pending`, signal)

export const replaceWithCandidate = (candidateId: string, replacedItemId: string) =>
  send<{ removedItemId: string }>(
    `${API_BASE}/queue/capacity/pending/${encodeURIComponent(candidateId)}/replace`,
    'POST',
    { replacedItemId },
  )

export const dismissCandidate = (candidateId: string) =>
  send<{ status: string }>(
    `${API_BASE}/queue/capacity/pending/${encodeURIComponent(candidateId)}/dismiss`,
    'POST',
  )

// ---- NEW-227 章节级阅读计划 -----------------------------------------------------

export interface PlanSection {
  id: string
  position: number
  label: string
  sessionNo: number | null
  status: 'pending' | 'done'
  doneAt: string | null
}

export interface SectionPlan {
  id: string
  itemRef: string
  sections: PlanSection[]
  progress: {
    totalSections: number
    doneSections: number
    pendingSections: number
  }
}

export const getSectionPlan = (itemRef: string, signal?: AbortSignal) =>
  request<SectionPlan>(
    `${API_BASE}/reading/section-plans?itemRef=${encodeURIComponent(itemRef)}`,
    signal,
  )

export const createSectionPlan = (itemRef: string, sections: { label: string; sessionNo?: number | null }[]) =>
  send<SectionPlan>(`${API_BASE}/reading/section-plans`, 'POST', { itemRef, sections })

export const deleteSectionPlan = (itemRef: string) =>
  send<void>(
    `${API_BASE}/reading/section-plans?itemRef=${encodeURIComponent(itemRef)}`,
    'DELETE',
  )

export const setPlanSectionDone = (sectionId: string, done: boolean) =>
  send<PlanSection>(
    `${API_BASE}/reading/section-plan-sections/${encodeURIComponent(sectionId)}/done`,
    'POST',
    { done },
  )

export const assignPlanSection = (sectionId: string, sessionNo: number | null) =>
  send<PlanSection>(
    `${API_BASE}/reading/section-plan-sections/${encodeURIComponent(sectionId)}`,
    'PATCH',
    sessionNo === null ? { clearSession: true } : { sessionNo },
  )

// ---- NEW-228 阅读中断便签 -------------------------------------------------------

export interface InterruptionNote {
  id: string
  itemRef: string
  resumeHint: string | null
  thought: string
  createdAt: string
  updatedAt: string
  archivedAt: string | null
  title: string | null
}

export const getActiveNote = (itemRef: string, signal?: AbortSignal) =>
  request<{ itemRef: string; note: InterruptionNote | null; archivedCount: number }>(
    `${API_BASE}/reading/interruption-notes?itemRef=${encodeURIComponent(itemRef)}`,
    signal,
  )

export const upsertNote = (itemRef: string, thought: string, resumeHint?: string) =>
  send<InterruptionNote>(`${API_BASE}/reading/interruption-notes`, 'PUT', {
    itemRef,
    thought,
    ...(resumeHint ? { resumeHint } : {}),
  })

export const archiveNote = (itemRef: string) =>
  send<InterruptionNote>(
    `${API_BASE}/reading/interruption-notes/archive?itemRef=${encodeURIComponent(itemRef)}`,
    'POST',
  )

export const listActiveNotes = (signal?: AbortSignal) =>
  request<{ items: InterruptionNote[] }>(
    `${API_BASE}/reading/interruption-notes/all`,
    signal,
  )

// ---- NEW-229 阅读约定卡 ---------------------------------------------------------

export interface ReadingPact {
  id: string
  pactKey: string
  itemRef: string
  materialTitle: string | null
  deadline: string
  counterpartUsername: string
  myStatus: 'pending' | 'confirmed' | 'archived'
  confirmedAt: string | null
  counterpartVisibility: string
}

export const listPacts = (signal?: AbortSignal) =>
  request<{ items: ReadingPact[]; note: string; counterpartVisibility: string }>(
    `${API_BASE}/reading/pacts`,
    signal,
  )

export const createPact = (input: {
  itemRef: string
  deadline: string
  counterpartUsername: string
  materialTitle?: string
}) => send<ReadingPact>(`${API_BASE}/reading/pacts`, 'POST', input)

export const joinPact = (input: {
  pactKey: string
  itemRef: string
  deadline: string
  counterpartUsername: string
  materialTitle?: string
}) => send<ReadingPact>(`${API_BASE}/reading/pacts/join`, 'POST', input)

export const confirmPact = (id: string, confirmed: boolean) =>
  send<ReadingPact>(`${API_BASE}/reading/pacts/${encodeURIComponent(id)}/confirm`, 'POST', {
    confirmed,
  })

export const archivePact = (id: string, archived: boolean) =>
  send<ReadingPact>(`${API_BASE}/reading/pacts/${encodeURIComponent(id)}/archive`, 'POST', {
    archived,
  })

// ---- NEW-230 队列重复主题提醒 ----------------------------------------------------

export interface TopicReportEntry {
  topic: string
  itemCount: number
  positions: number[]
  minGap: number | null
}

export interface TopicReport {
  topics: TopicReportEntry[]
  duplicatedTopics: TopicReportEntry[]
  advisory: boolean
  note: string
}

export const setQueueTopics = (itemRef: string, topics: string[]) =>
  send<{ itemRef: string; topics: string[] }>(`${API_BASE}/queue/topics`, 'PUT', {
    itemRef,
    topics,
  })

export const getQueueTopics = (itemRef: string, signal?: AbortSignal) =>
  request<{ itemRef: string; topics: string[] }>(
    `${API_BASE}/queue/topics?itemRef=${encodeURIComponent(itemRef)}`,
    signal,
  )

export const getTopicReport = (signal?: AbortSignal) =>
  request<TopicReport>(`${API_BASE}/queue/topics/report`, signal)

/** 今日队列成员（材料选择器的数据源；复用既有 client）。 */
export type { QueueItemView }
