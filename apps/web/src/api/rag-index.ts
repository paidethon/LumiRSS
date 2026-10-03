/** R24 RAG 索引页 — 本组专属 API 调用（overview/删除/失败重试/增量暂停/收敛）。
 *
 * 后端真源：services/bff/src/lumirss/routers/rag.py 的
 * /api/v1/rag/index/* 端点；类型按 BFF 稳定 DTO 手写（本组端点尚未进
 * OpenAPI 生成集——诚实注释，与 api/new391.ts 同一口径，不假装
 * generated）。既有共享端点（rebuild/pause-rebuild/search/exclusions）
 * 继续走 api/client.ts，本文件不复制它们。
 *
 * 注意：BFF 全局 response_model_exclude_none —— 可空字段在响应里是
 * 「缺省」而不是显式 null，因此以下可选字段一律 `?: T | null`。
 * 绝不有任何函数返回或接收原始 embedding 数组。
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

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
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

// ---- DTO（对齐 routers/rag.py + models.py 的 RagIndex* 模型）--------------

export interface RagIndexOverviewSource {
  kind: string
  corpusDocs: number
  indexedDocs: number
  chunks: number
}

export interface RagIndexOverviewStorage {
  /** dbstat = SQLite 页级真实占用；payload = 无 dbstat 编译项时的载荷字节兜底。 */
  basis: 'dbstat' | 'payload'
  vecBytes: number
  chunkBytes: number
  totalBytes: number
}

export interface RagIndexOverviewQueue {
  pending: number
  done: number
  failed: number
  stale: number
}

export interface RagIndexOverviewFailure {
  ref?: string | null
  reason: string
  at?: string | null
}

export interface RagIndexOverviewJob {
  jobId?: string | null
  status?: string | null
  stage?: string | null
  done: number
  remaining?: number | null
  updatedAt?: string | null
}

export interface RagIndexOverview {
  enabled: boolean
  modelId: string
  dim: number
  configuredModel?: string | null
  documents: number
  chunks: number
  sources: RagIndexOverviewSource[]
  excludedFeeds: number
  aiDisabledFeeds: number
  lastUpdatedAt?: string | null
  lastRebuildAt?: string | null
  lastError?: string | null
  storage: RagIndexOverviewStorage
  queue: RagIndexOverviewQueue
  failures: RagIndexOverviewFailure[]
  incrementalPaused: boolean
  calendarPaused: boolean
  vecTable: boolean
  fastembedAvailable: boolean
  job?: RagIndexOverviewJob | null
}

export interface RagIndexDeleteResult {
  removedChunks: number
  removedVecRows: number
}

export interface RagIndexRetryFailedResult {
  requested: number
  updated: number
  chunks: number
  missing: string[]
}

export interface RagIndexConvergeResult {
  indexed: number
  swept: number
  skipped?: string | null
}

// ---- 端点 -------------------------------------------------------------------

/** 总览：当前账号索引集合的真实盘点（数量/模型/磁盘/队列/失败明细）。 */
export function getRagIndexOverview(signal?: AbortSignal): Promise<RagIndexOverview> {
  return getJson(`${API_BASE}/rag/index/overview`, signal)
}

/** 清空本账号派生索引（向量 + 分块元数据）；原文绝不删除。 */
export function deleteRagIndex(): Promise<RagIndexDeleteResult> {
  return sendJson(`${API_BASE}/rag/index`, 'DELETE')
}

/** 只重试失败项；refs 缺省 = 全部失败项，显式 refs = 单项重试。 */
export function retryFailedRagIndex(
  refs?: string[],
): Promise<RagIndexRetryFailedResult> {
  return sendJson(`${API_BASE}/rag/index/retry-failed`, 'POST', refs ? { refs } : {})
}

/** 暂停本账号的增量索引收敛（不影响手动重建/检索）。 */
export function pauseRagIndexIncremental(): Promise<{ paused: boolean }> {
  return sendJson(`${API_BASE}/rag/index/pause`, 'POST')
}

/** 恢复本账号的增量索引收敛（幂等）。 */
export function resumeRagIndexIncremental(): Promise<{ paused: boolean }> {
  return sendJson(`${API_BASE}/rag/index/resume`, 'POST')
}

/** 手动触发一次增量收敛（与后台增量任务同一管线）。 */
export function convergeRagIndex(): Promise<RagIndexConvergeResult> {
  return sendJson(`${API_BASE}/rag/index/converge`, 'POST')
}
