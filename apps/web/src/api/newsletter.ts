/** 邮件简报（外发摘要）发送账本 — 已发送内容页专属 API。
 *
 * 后端真源：services/bff/src/lumirss/routers/newsletter.py +
 * lumirss/newsletter_issues.py。类型按 BFF 稳定 DTO 手写（本组端点
 * 尚未进 OpenAPI 生成集——router include 由主 Agent 统一接入，接入后
 * api:generate 即覆盖；诚实注释，不假装 generated）。URL 全部相对
 * /api/v1/*。
 *
 * 领域说明：「外部邮件订阅收件箱」（bridge 列表收信）与「外发简报」
 * （digest 邮件发送）是两件事；本模块只负责后者。draft / scheduled
 * 过滤值当前诚实返回空列表（无草稿机制；计划发送是 digest 设置而非
 * 期号记录）。失败行可重试，重试只投递尚未成功的收件人。收件人
 * 地址可能被服务端脱敏（a***@domain），前端原样展示，不反推。
 */

import { ApiError } from './client'

const API_BASE = '/api/v1'

export type NewsletterIssueStatus = 'sent' | 'draft' | 'scheduled' | 'failed'

export interface NewsletterIssueRecipient {
  /** 非管理员视角为脱敏形态（如 a***@domain），原样展示。 */
  address: string
  status: string
  error: string | null
  sentAt: string | null
}

export interface NewsletterIssueSummary {
  id: number
  subject: string
  status: NewsletterIssueStatus
  /** digest 来源（mail / read_later / starred）。 */
  source: string
  /** manual（立即发送/重试）| scheduled（定时调度）。 */
  origin: string
  itemCount: number
  recipientCount: number
  error: string | null
  createdAt: string
  sentAt: string | null
}

export interface NewsletterIssueList {
  items: NewsletterIssueSummary[]
}

export interface NewsletterIssueDetail extends NewsletterIssueSummary {
  /** false = 无正文快照（失败行/历史形态）——诚实降级，不伪造。 */
  bodyAvailable: boolean
  text: string | null
  html: string | null
  dedupeKey: string
  providerReceipt: string
  recipients: NewsletterIssueRecipient[]
}

export interface NewsletterRetryResult {
  issueId: number
  status: string
  sentCount: number
  skippedCount: number
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
  let parsed: unknown = null
  try {
    const text = await response.text()
    parsed = text ? (JSON.parse(text) as unknown) : null
  } catch {
    // 非 JSON 错误体
  }
  let type = 'request_failed'
  const message = messageOf(parsed, `请求失败（${response.status}）`)
  if (parsed !== null && typeof parsed === 'object') {
    const err = (parsed as { error?: { type?: string } }).error
    if (err?.type) type = err.type
  }
  return new ApiError(response.status, type, message)
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw await toApiError(response)
  const text = await response.text()
  return (text ? (JSON.parse(text) as T) : (null as T))
}

/** 发送账本列表（新→旧，有界）。status 非法值由 BFF 稳定 422。 */
export function listNewsletterIssues(
  status: NewsletterIssueStatus,
  signal?: AbortSignal,
): Promise<NewsletterIssueList> {
  return getJson<NewsletterIssueList>(
    `${API_BASE}/newsletter/issues?status=${encodeURIComponent(status)}`,
    signal,
  )
}

/** 单条详情：正文快照仅在 bodyAvailable 时存在。 */
export function getNewsletterIssue(
  issueId: number,
  signal?: AbortSignal,
): Promise<NewsletterIssueDetail> {
  return getJson<NewsletterIssueDetail>(
    `${API_BASE}/newsletter/issues/${issueId}`,
    signal,
  )
}

/** 重试一次失败的发送（BFF 只投递账目中未成功收件人）。 */
export function retryNewsletterIssue(issueId: number): Promise<NewsletterRetryResult> {
  return postJson<NewsletterRetryResult>(
    `${API_BASE}/newsletter/issues/${issueId}/retry`,
  )
}
