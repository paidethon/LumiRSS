/** NEW-331..340 共读空间协作组 — 本组专属 API 调用（独立文件，不触
 * 碰共享 client.ts；URL 全部相对 /api/v1/*，与 client.ts 同口径）。
 *
 * 后端真源：services/bff/src/lumirss/routers/new33*.py / new340*.py；
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

// ---- 基底：空间 / 成员 / 栏目（NEW-331） -----------------------------------

export interface SpaceMember {
  id: string
  spaceId: string
  userId: string
  username: string
  role: string
  expiresAt: string | null
  revokedAt: string | null
  active: boolean
  expired: boolean
  createdAt: string
}

export interface SpaceSection {
  id: string
  spaceId: string
  name: string
  position: number
  createdAt: string
}

export interface Space {
  id: string
  name: string
  description: string
  ownerUserId: string
  requireApproval: boolean
  discussionTemplates: string[]
  archivedAt: string | null
  createdAt: string
  updatedAt: string
  myRole: string | null
  members?: SpaceMember[]
  sections?: SpaceSection[]
}

export async function createSpace(payload: {
  name: string
  description?: string
  requireApproval?: boolean
  discussionTemplates?: string[]
}): Promise<Space> {
  return sendJson(`${API_BASE}/spaces`, 'POST', payload)
}

export async function listSpaces(): Promise<{ items: Space[] }> {
  return getJson(`${API_BASE}/spaces`)
}

export async function getSpace(spaceId: string): Promise<Space> {
  return getJson(`${API_BASE}/spaces/${spaceId}`)
}

export async function addSpaceMember(spaceId: string, username: string): Promise<SpaceMember> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/members`, 'POST', { username })
}

export async function removeSpaceMember(spaceId: string, memberId: string): Promise<null> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/members/${memberId}`, 'DELETE')
}

export async function addSpaceSection(spaceId: string, name: string): Promise<SpaceSection> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/sections`, 'POST', { name })
}

export async function updateSpaceSettings(
  spaceId: string,
  requireApproval: boolean,
): Promise<Space> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/settings`, 'PUT', { requireApproval })
}

// ---- NEW-331 会议资料单 -----------------------------------------------------

export interface MeetingItem {
  id: string
  meetingId: string
  entryRef: string
  title: string
  excerpt: string
  question: string | null
  addedBy: string
  addedByUsername: string
  createdAt: string
}

export interface MeetingOutcome {
  id: string
  meetingId: string
  entryRef: string | null
  summary: string
  createdBy: string
  createdByUsername: string
  createdAt: string
}

export interface Meeting {
  id: string
  spaceId: string
  title: string
  status: string
  createdBy: string
  createdByUsername: string
  closedAt: string | null
  createdAt: string
  items?: MeetingItem[]
  outcomes?: MeetingOutcome[]
}

export async function createMeeting(spaceId: string, title: string): Promise<Meeting> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/meetings`, 'POST', { title })
}

export async function listMeetings(spaceId: string): Promise<{ items: Meeting[] }> {
  return getJson(`${API_BASE}/spaces/${spaceId}/meetings`)
}

export async function getMeeting(spaceId: string, meetingId: string): Promise<Meeting> {
  return getJson(`${API_BASE}/spaces/${spaceId}/meetings/${meetingId}`)
}

export async function addMeetingItem(
  spaceId: string,
  meetingId: string,
  payload: { entryRef: string; title: string; excerpt?: string; question?: string },
): Promise<MeetingItem> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/meetings/${meetingId}/items`, 'POST', payload)
}

export async function closeMeeting(spaceId: string, meetingId: string): Promise<Meeting> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/meetings/${meetingId}/close`, 'POST')
}

export async function addMeetingOutcome(
  spaceId: string,
  meetingId: string,
  payload: { summary: string; entryRef?: string },
): Promise<Meeting> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/meetings/${meetingId}/outcomes`, 'POST', payload)
}

// ---- NEW-332 投稿审批 -------------------------------------------------------

export interface Contribution {
  id: string
  spaceId: string
  entryRef: string
  title: string
  excerpt: string
  note: string | null
  sectionId: string | null
  status: 'pending' | 'approved' | 'rejected'
  reviewNote: string | null
  reviewedByUsername: string | null
  reviewedAt: string | null
  submittedBy: string
  submittedByUsername: string
  createdAt: string
}

export async function submitContribution(
  spaceId: string,
  payload: { entryRef: string; title: string; excerpt?: string; note?: string },
): Promise<Contribution> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/contributions`, 'POST', payload)
}

export async function listContributions(
  spaceId: string,
  scope: 'visible' | 'mine',
): Promise<{ items: Contribution[] }> {
  return getJson(`${API_BASE}/spaces/${spaceId}/contributions?scope=${scope}`)
}

export async function reviewContribution(
  spaceId: string,
  contributionId: string,
  payload: { approve: boolean; reviewNote?: string },
): Promise<Contribution> {
  return sendJson(
    `${API_BASE}/spaces/${spaceId}/contributions/${contributionId}/review`,
    'POST',
    payload,
  )
}

// ---- NEW-333 版本通知 -------------------------------------------------------

export interface VersionNotice {
  id: string
  spaceId: string
  entryRef: string
  versionLabel: string
  summary: string
  reportedByUsername: string
  createdAt: string
  myAcknowledgedAt?: string | null
  acks?: { noticeId: string; userId: string; acknowledgedAt: string | null }[]
}

export async function reportVersionNotice(
  spaceId: string,
  payload: { entryRef: string; versionLabel: string; summary?: string },
): Promise<VersionNotice> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/version-notices`, 'POST', payload)
}

export async function listVersionNotices(
  spaceId: string,
  scope: 'all' | 'pending',
): Promise<{ items: VersionNotice[] }> {
  return getJson(`${API_BASE}/spaces/${spaceId}/version-notices?scope=${scope}`)
}

export async function acknowledgeVersionNotice(
  spaceId: string,
  noticeId: string,
): Promise<VersionNotice> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/version-notices/${noticeId}/ack`, 'POST')
}

// ---- NEW-334 成员到期 -------------------------------------------------------

export async function setMemberExpiry(
  spaceId: string,
  memberId: string,
  expiresAt: string | null,
): Promise<SpaceMember> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/members/${memberId}/expiry`, 'PUT', {
    expiresAt,
  })
}

export async function sweepMemberExpiry(
  spaceId: string,
): Promise<{ expired: { userId: string; username: string; expiresAt: string }[] }> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/members/sweep`, 'POST')
}

export interface ExpiryLogEntry {
  id: string
  username: string
  action: string
  detail: string
  createdAt: string
}

export async function listExpiryLog(spaceId: string): Promise<{ items: ExpiryLogEntry[] }> {
  return getJson(`${API_BASE}/spaces/${spaceId}/member-expiry-log`)
}

// ---- NEW-335 分歧记录 -------------------------------------------------------

export interface DisagreementPosition {
  id: string
  authorUserId: string
  authorUsername: string
  conclusion: string
  citations: { ref: string; note: string }[]
  createdAt: string
  updatedAt: string
}

export interface DisagreementEvidence {
  id: string
  positionId: string | null
  addedByUsername: string
  note: string
  ref: string | null
  createdAt: string
}

export interface Disagreement {
  id: string
  spaceId: string
  entryRef: string | null
  title: string
  status: string
  createdByUsername: string
  closedAt: string | null
  createdAt: string
  positions?: DisagreementPosition[]
  evidence?: DisagreementEvidence[]
}

export async function createDisagreement(
  spaceId: string,
  payload: { title: string; entryRef?: string },
): Promise<Disagreement> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/disagreements`, 'POST', payload)
}

export async function listDisagreements(spaceId: string): Promise<{ items: Disagreement[] }> {
  return getJson(`${API_BASE}/spaces/${spaceId}/disagreements`)
}

export async function getDisagreement(
  spaceId: string,
  disagreementId: string,
): Promise<Disagreement> {
  return getJson(`${API_BASE}/spaces/${spaceId}/disagreements/${disagreementId}`)
}

export async function upsertMyPosition(
  spaceId: string,
  disagreementId: string,
  payload: { conclusion: string; citations?: { ref?: string; note?: string }[] },
): Promise<Disagreement> {
  return sendJson(
    `${API_BASE}/spaces/${spaceId}/disagreements/${disagreementId}/positions/my`,
    'PUT',
    payload,
  )
}

export async function addEvidence(
  spaceId: string,
  disagreementId: string,
  payload: { note: string; ref?: string; positionId?: string },
): Promise<Disagreement> {
  return sendJson(
    `${API_BASE}/spaces/${spaceId}/disagreements/${disagreementId}/evidence`,
    'POST',
    payload,
  )
}

// ---- NEW-336 讨论待答/已解答 ------------------------------------------------

export interface DiscussionReply {
  id: string
  authorUsername: string
  body: string
  helpful: boolean
  createdAt: string
}

export interface Discussion {
  id: string
  spaceId: string
  entryRef: string | null
  title: string
  question: string
  status: 'open' | 'resolved'
  resolvedReplyId: string | null
  resolvedAt: string | null
  askedByUsername: string
  createdAt: string
  replies?: DiscussionReply[]
}

export async function askDiscussion(
  spaceId: string,
  payload: { title: string; question: string; entryRef?: string },
): Promise<Discussion> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/discussions`, 'POST', payload)
}

export async function listDiscussions(
  spaceId: string,
  status?: 'open' | 'resolved',
): Promise<{ items: Discussion[] }> {
  const suffix = status ? `?status=${status}` : ''
  return getJson(`${API_BASE}/spaces/${spaceId}/discussions${suffix}`)
}

export async function getDiscussion(spaceId: string, discussionId: string): Promise<Discussion> {
  return getJson(`${API_BASE}/spaces/${spaceId}/discussions/${discussionId}`)
}

export async function replyDiscussion(
  spaceId: string,
  discussionId: string,
  body: string,
): Promise<Discussion> {
  return sendJson(
    `${API_BASE}/spaces/${spaceId}/discussions/${discussionId}/replies`,
    'POST',
    { body },
  )
}

export async function setReplyHelpful(
  spaceId: string,
  discussionId: string,
  replyId: string,
  helpful: boolean,
): Promise<Discussion> {
  return sendJson(
    `${API_BASE}/spaces/${spaceId}/discussions/${discussionId}/replies/${replyId}/helpful`,
    'POST',
    { helpful },
  )
}

export async function resolveDiscussion(
  spaceId: string,
  discussionId: string,
  replyId: string | null,
): Promise<Discussion> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/discussions/${discussionId}/resolve`, 'POST', {
    replyId,
  })
}

// ---- NEW-337 活动摘要 -------------------------------------------------------

export interface ActivitySummaryView {
  spaceId: string
  from: string
  to: string
  scope: string
  note: string
  counts: Record<string, Record<string, number>>
  recent: Record<string, { id: string; title: string; status?: string; actor?: string; at: string }[]>
}

export async function getActivity(
  spaceId: string,
  from: string,
  to: string,
): Promise<ActivitySummaryView> {
  return getJson(
    `${API_BASE}/spaces/${spaceId}/activity?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
  )
}

// ---- NEW-338 附件共享清单 ---------------------------------------------------

export interface AttachmentShare {
  id: string
  ownerUsername: string
  attachmentRef: string
  name: string
  mimeType: string
  sizeBytes: number | null
  createdAt: string
  revokedAt: string | null
  revokedByUsername: string | null
}

export async function shareAttachment(
  spaceId: string,
  payload: { attachmentRef: string; name: string; mimeType?: string; sizeBytes?: number },
): Promise<AttachmentShare> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/attachment-shares`, 'POST', payload)
}

export async function listAttachmentShares(
  spaceId: string,
  includeRevoked: boolean,
): Promise<{ items: AttachmentShare[] }> {
  return getJson(
    `${API_BASE}/spaces/${spaceId}/attachment-shares?includeRevoked=${includeRevoked}`,
  )
}

export async function revokeAttachmentShare(
  spaceId: string,
  shareId: string,
): Promise<AttachmentShare> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/attachment-shares/${shareId}`, 'DELETE')
}

// ---- NEW-339 共读模板 -------------------------------------------------------

export interface SpaceTemplate {
  id: string
  name: string
  description: string
  sourceSpaceId: string | null
  sections: { name: string; position: number }[]
  roleRules: { requireApproval?: boolean }
  discussionTemplates: string[]
  createdByUsername: string
  createdAt: string
  previewNote?: string
}

export async function createTemplateFromSpace(
  spaceId: string,
  payload: { name: string; description?: string; discussionTemplates?: string[] },
): Promise<SpaceTemplate> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/template`, 'POST', payload)
}

export async function listSpaceTemplates(): Promise<{ items: SpaceTemplate[] }> {
  return getJson(`${API_BASE}/space-templates`)
}

export async function previewSpaceTemplate(templateId: string): Promise<SpaceTemplate> {
  return getJson(`${API_BASE}/space-templates/${templateId}/preview`)
}

export async function createSpaceFromTemplate(
  templateId: string,
  payload: { name: string; description?: string },
): Promise<Space> {
  return sendJson(`${API_BASE}/space-templates/${templateId}/create-space`, 'POST', payload)
}

// ---- NEW-340 归档 -----------------------------------------------------------

export interface ArchivePreview {
  spaceId: string
  openTasks: { kind: string; id: string; title: string; actor?: string }[]
  openTaskCount: number
  note: string
}

export interface ArchiveResult {
  spaceId: string
  action: string
  archivedAt: string | null
  tasks: { kind: string; title: string }[]
  forced: boolean
  keptMembers: string[]
}

export async function previewArchive(spaceId: string): Promise<ArchivePreview> {
  return getJson(`${API_BASE}/spaces/${spaceId}/archive/preview`)
}

export async function archiveSpace(spaceId: string, force: boolean): Promise<ArchiveResult> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/archive`, 'POST', { force })
}

export async function restoreSpace(
  spaceId: string,
  keepMemberIds: string[],
): Promise<ArchiveResult> {
  return sendJson(`${API_BASE}/spaces/${spaceId}/restore`, 'POST', { keepMemberIds })
}
