/** LumiRSS API client — 只访问相对 /api/v1/*，所有 BFF HTTP 调用集中在此。
 * 读：getFeeds / getEntries / getEntry；写：setEntryState（set 语义）。 */

import { toApiView, type UiView } from '../lib/read-later'
import type {
  ApiErrorResponse,
  Category,
  EntryDetail,
  EntryListResponse,
  Feed,
  FeedPreviewMetadata,
  FreshRssUiInfo,
  OpmlImportPreview,
  OpmlImportResult,
  Subscription,
} from './types'

const API_BASE = '/api/v1'

/** 安全的错误对象：UI 只显示它的 message，永远不显示原始响应体。 */
export class ApiError extends Error {
  readonly status: number
  readonly type: string

  constructor(status: number, type: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.type = type
  }
}

function isAbortError(error: unknown): boolean {
  // DOMException（AbortError）在部分运行时不继承 Error，只用 name 判断。
  return (
    typeof error === 'object' &&
    error !== null &&
    (error as { name?: unknown }).name === 'AbortError'
  )
}

/** 把非 2xx 响应转成 ApiError；容错 BFF error envelope 与其它形状。 */
async function toApiError(response: Response): Promise<ApiError> {
  let type = 'http_error'
  let message = `请求失败（HTTP ${response.status}），请稍后重试。`
  try {
    const body: unknown = await response.json()
    if (
      typeof body === 'object' &&
      body !== null &&
      'error' in body &&
      typeof (body as ApiErrorResponse).error === 'object' &&
      (body as ApiErrorResponse).error !== null
    ) {
      const err = (body as ApiErrorResponse).error
      if (typeof err.type === 'string' && typeof err.message === 'string') {
        type = err.type
        message = err.message
      }
    }
  } catch {
    // 非 JSON（如 HTML 错误页 / 422 detail 数组）→ 使用安全 fallback。
  }
  return new ApiError(response.status, type, message)
}

/** 发起请求并把非 2xx / 网络失败转成 ApiError；返回原始 Response，
 * 由调用方决定是否解析 JSON（PATCH 204 无响应体，不能 json()）。 */
async function rawRequest(
  path: string,
  init?: {
    method?: string
    body?: BodyInit
    contentType?: string
    signal?: AbortSignal
  },
): Promise<Response> {
  if (init?.signal?.aborted) {
    throw new DOMException('The request was aborted.', 'AbortError')
  }
  let response: Response
  try {
    response = await fetch(path, {
      method: init?.method,
      body: init?.body,
      headers:
        init?.contentType !== undefined
          ? { 'Content-Type': init.contentType }
          : undefined,
      signal: init?.signal,
    })
  } catch (error) {
    if (isAbortError(error)) {
      // 正常的 query cancellation：原样上抛，TanStack Query 自己处理，
      // 不算网络错误，不进入 error UI。
      throw error
    }
    throw new ApiError(0, 'network_error', '无法连接到服务器，请稍后重试。')
  }
  if (!response.ok) {
    throw await toApiError(response)
  }
  return response
}

async function request<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await rawRequest(path, { signal })
  return (await response.json()) as T
}

export async function getFeeds(signal?: AbortSignal): Promise<Feed[]> {
  return request<Feed[]>(`${API_BASE}/feeds`, signal)
}

/** 0013 Gate 1：分类列表（含空分类，与 feeds 的 category 同一契约）。 */
export async function getCategories(signal?: AbortSignal): Promise<Category[]> {
  return request<Category[]>(`${API_BASE}/categories`, signal)
}

/** 0013 Gate 3：管理视角订阅列表（含 opaque subscriptionRef，前端只透传）。 */
export async function getSubscriptions(signal?: AbortSignal): Promise<Subscription[]> {
  return request<Subscription[]>(`${API_BASE}/subscriptions`, signal)
}

/** 0013 Gate 2：直接 RSS/Atom 预览（无副作用；不接 AbortSignal ——
 * POST 语义与 Mutation 一致，避免预览中途被取消造成状态不一致）。 */
export async function previewFeed(feedUrl: string): Promise<FeedPreviewMetadata> {
  const response = await rawRequest(`${API_BASE}/feed-preview`, {
    method: 'POST',
    body: JSON.stringify({ feedUrl }),
    contentType: 'application/json',
  })
  return (await response.json()) as FeedPreviewMetadata
}

export async function getEntries(
  params: {
    view: UiView
    feedUrl: string | null
    sourceType?: string | null
    categoryId?: string | null
    cursor?: string | null
  },
  signal?: AbortSignal,
): Promise<EntryListResponse> {
  const query = new URLSearchParams()
  // view 始终显式携带，与 query key 的 scope 保持一致（与 cursor scope
  // 构造性一致，规避 invalid_cursor 400）。read-later 是前端 workspace
  // 语义（无 BFF 契约）：翻译为 view=all 全量拉取，列表侧客户端过滤。
  query.set('view', toApiView(params.view))
  if (params.feedUrl !== null) {
    query.set('feedUrl', params.feedUrl)
  }
  // 0011：sourceType/categoryId 服务端过滤（§13）——与 feedUrl 互斥
  // 由 BFF 校验（前端构造时保证只有一个存在）。
  if (params.sourceType != null) {
    query.set('sourceType', params.sourceType)
  }
  if (params.categoryId != null) {
    query.set('categoryId', params.categoryId)
  }
  if (params.cursor != null) {
    // cursor 是 opaque string：原样传递，绝不 decode / parse / 修改。
    query.set('cursor', params.cursor)
  }
  return request<EntryListResponse>(`${API_BASE}/entries?${query}`, signal)
}

/** 读单篇文章 Detail。entryRef 虽是 URL-safe base64url，仍统一
 * encodeURIComponent（路径段安全）。signal 供 useQuery cancellation。 */
export async function getEntry(
  entryRef: string,
  signal?: AbortSignal,
): Promise<EntryDetail> {
  return request<EntryDetail>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}`,
    signal,
  )
}

/** 写文章状态（set 语义，非 toggle）。
 *
 * 注意：刻意不接 AbortSignal——Query cancellation 与 Mutation 严格区分；
 * PATCH 一旦发出就允许正常完成，不因切换 Entry / 组件卸载而 abort。 */
export async function setEntryState(
  entryRef: string,
  patch: { read: boolean } | { starred: boolean },
): Promise<void> {
  // 成功 = 204 No Content：不解析响应体。
  await rawRequest(`${API_BASE}/entries/${encodeURIComponent(entryRef)}/state`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
    contentType: 'application/json',
  })
}

/** 0013 Gate 1：订阅一个 feed URL（server-confirmed；成功返回新订阅）。
 * 与 setEntryState 同理：不接 AbortSignal，mutation 一旦发出就允许完成。 */
export async function subscribeFeed(
  feedUrl: string,
  body: { categoryId?: string | null; title?: string | null } = {},
): Promise<Subscription> {
  const response = await rawRequest(`${API_BASE}/subscriptions`, {
    method: 'POST',
    body: JSON.stringify({
      feedUrl,
      ...(body.categoryId != null ? { categoryId: body.categoryId } : {}),
      ...(body.title != null ? { title: body.title } : {}),
    }),
    contentType: 'application/json',
  })
  return (await response.json()) as Subscription
}

/** 0013 Gate 3：把订阅移动到已有分类或新建分类（PATCH 204，无响应体）。
 * 与 setEntryState 同理：不接 AbortSignal，mutation 一旦发出就允许完成。 */
export async function moveSubscription(
  subscriptionRef: string,
  body: { categoryId: string } | { newCategoryLabel: string },
): Promise<void> {
  await rawRequest(`${API_BASE}/subscriptions/${encodeURIComponent(subscriptionRef)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
}

/** 0013 Gate 3：取消订阅（破坏性操作，确认流程由 UI 负责；DELETE 204）。 */
export async function unsubscribeFeed(subscriptionRef: string): Promise<void> {
  await rawRequest(`${API_BASE}/subscriptions/${encodeURIComponent(subscriptionRef)}`, {
    method: 'DELETE',
  })
}

/** 0013 Gate 3：重命名分类（PATCH 204；409 冲突/默认分类不可改）。 */
export async function renameCategory(categoryId: string, label: string): Promise<void> {
  await rawRequest(`${API_BASE}/categories/${encodeURIComponent(categoryId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ label }),
    contentType: 'application/json',
  })
}

/** 0013 Gate 4：导出 OPML（BFF 代理 FreshRSS subscription/export；
 * 浏览器不接触 FreshRSS 凭据）。成功即触发下载；失败抛 ApiError。 */
export async function exportOpml(): Promise<void> {
  const response = await rawRequest(`${API_BASE}/opml/export`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `LumiRSS-subscriptions-${new Date().toISOString().slice(0, 10)}.opml`
  anchor.click()
  URL.revokeObjectURL(url)
}

/** 0013 Gate 4：OPML 导入预览（无副作用；原始字节上传，BFF 负责
 * bounded read + defusedxml 安全解析）。不接 AbortSignal——与其它
 * mutation 语义一致，一旦发出就允许完成。 */
export async function previewOpmlImport(file: File): Promise<OpmlImportPreview> {
  const response = await rawRequest(`${API_BASE}/opml/import/preview`, {
    method: 'POST',
    body: file,
    contentType: file.type || 'application/xml',
  })
  return (await response.json()) as OpmlImportPreview
}

/** 0013 Gate 4：确认导入（merge 语义；文件重新上传、服务端重新解析
 * 并重新读取 FreshRSS，预览仅供参考）。成功后由调用方 invalidate。 */
export async function importOpml(file: File): Promise<OpmlImportResult> {
  const response = await rawRequest(`${API_BASE}/opml/import`, {
    method: 'POST',
    body: file,
    contentType: file.type || 'application/xml',
  })
  return (await response.json()) as OpmlImportResult
}

/** 0013 Gate 4：FreshRSS 高级逃生入口（未配置 → null；BFF 永不暴露
 * 内部 base URL）。 */
export async function getFreshRssUiUrl(signal?: AbortSignal): Promise<FreshRssUiInfo> {
  return request<FreshRssUiInfo>(`${API_BASE}/freshrss-ui`, signal)
}
