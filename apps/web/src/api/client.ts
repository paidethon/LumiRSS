/** LumiRSS API client — 只访问相对 /api/v1/*，所有 BFF HTTP 调用集中在此。
 * 读：getFeeds / getEntries / getEntry；写：setEntryState（set 语义）。 */

import { toApiView, type UiView } from '../lib/read-later'
import { sessionExpired } from '../store/auth'
import type {
  AiProfile,
  AiPurposeKey,
  AiPurposes,
  AiSettings,
  AiSettingsUpdate,
  ApiErrorResponse,
  ApiVersion,
  AuthStatusView,
  BackupCapabilities,
  BackupJob,
  Bookmark,
  BookmarkImportResult,
  BookmarkListResponse,
  ClipDetail,
  ClipFetchResult,
  ClipListResponse,
  TranslationSegmentsView,
  Category,
  EntryConversation,
  EntryDetail,
  EntryListResponse,
  EntrySummary,
  EntryTranslation,
  Feed,
  FeedPreviewMetadata,
  FreshRssUiInfo,
  OpmlImportPreview,
  OpmlImportResult,
  OperationsStatus,
  RemoteBackupsResponse,
  RestorePreview,
  RestoreResult,
  RssHubConfig,
  RssHubRoutesResponse,
  SearchResponse,
  ServerSettings,
  SnapshotListResponse,
  SnapshotView,
  SourceDiscoveryResponse,
  Subscription,
  WebDavSettings,
  WebDavTestResult,
  Workspace,
  WorkspaceItem,
  WorkspaceItemsResolvedResponse,
  WorkspaceItemsResponse,
  WorkspaceListResponse,
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
    const error = await toApiError(response)
    // 会话过期/缺失：翻转全局登录门（幂等；basic 模式的 401 没有
    // 这个 type，不会误触发）。离线/网络错误在上面已另行处理，
    // 绝不把「连不上」当成「未登录」。
    if (error.status === 401 && error.type === 'session_required') {
      sessionExpired()
    }
    throw error
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

// ---- 会话认证（LUMIRSS_AUTH_MODE=session） ----
// Cookie 由浏览器自动携带（HttpOnly），客户端代码永远接触不到 token。

/** 启动探测：当前认证模式 + 是否已登录（公开端点）。 */
export async function getAuthSession(): Promise<AuthStatusView> {
  return request<AuthStatusView>(`${API_BASE}/auth/session`)
}

/** 登录（单用户：只输密码）。成功 = Set-Cookie 由浏览器保存。 */
export async function loginPassword(password: string): Promise<AuthStatusView> {
  const response = await rawRequest(`${API_BASE}/auth/login`, {
    method: 'POST',
    body: JSON.stringify({ password }),
    contentType: 'application/json',
  })
  return (await response.json()) as AuthStatusView
}

/** 登出当前设备（服务端撤销本 session + 过期 Cookie）。 */
export async function logoutCurrent(): Promise<void> {
  await rawRequest(`${API_BASE}/auth/logout`, { method: 'POST' })
}

/** 所有设备登出（撤销全部 session，含当前）。 */
export async function logoutEverywhere(): Promise<void> {
  await rawRequest(`${API_BASE}/auth/logout-all`, { method: 'POST' })
}

/** 修改密码：验证当前密码 → 全部 session 失效 → 本设备自动换发新
 * session（不会立刻弹回登录页）。 */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<AuthStatusView> {
  const response = await rawRequest(`${API_BASE}/auth/password`, {
    method: 'POST',
    body: JSON.stringify({ currentPassword, newPassword }),
    contentType: 'application/json',
  })
  return (await response.json()) as AuthStatusView
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
): Promise<EntryListResponse> {  const query = new URLSearchParams()
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

/** 0022 全局搜索：q 必填；cursor opaque 原样透传；过滤器由页面构造。 */
export async function searchEntries(
  params: {
    q: string
    cursor?: string | null
    limit?: number
    feedUrl?: string | null
    categoryId?: string | null
    state?: 'unread' | null
    favorite?: boolean | null
    from?: string | null
    to?: string | null
  },
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const query = new URLSearchParams()
  query.set('q', params.q)
  if (params.cursor != null) {
    // cursor 是 opaque string：原样传递，绝不 decode / parse / 修改。
    query.set('cursor', params.cursor)
  }
  if (params.limit != null) {
    query.set('limit', String(params.limit))
  }
  if (params.feedUrl != null) {
    query.set('feedUrl', params.feedUrl)
  }
  if (params.categoryId != null) {
    query.set('categoryId', params.categoryId)
  }
  if (params.state != null) {
    query.set('state', params.state)
  }
  if (params.favorite != null) {
    query.set('favorite', params.favorite ? 'true' : 'false')
  }
  if (params.from != null) {
    query.set('from', params.from)
  }
  if (params.to != null) {
    query.set('to', params.to)
  }
  return request<SearchResponse>(`${API_BASE}/search?${query}`, signal)
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

/** 0014：网站 → RSS/Atom 候选发现（无副作用；不接 AbortSignal——与其它
 * mutation 语义一致，一旦发出就允许完成）。 */
export async function discoverFeeds(url: string): Promise<SourceDiscoveryResponse> {
  const response = await rawRequest(`${API_BASE}/source-discovery`, {
    method: 'POST',
    body: JSON.stringify({ url }),
    contentType: 'application/json',
  })
  return (await response.json()) as SourceDiscoveryResponse
}

/** 0014：RSSHub 路由目录（Lumi-owned 静态 catalog；configured 报告服务端
 * 是否配置了 RSSHub 实例）。 */
export async function getRssHubRoutes(signal?: AbortSignal): Promise<RssHubRoutesResponse> {
  return request<RssHubRoutesResponse>(`${API_BASE}/rsshub/routes`, signal)
}

/** 0014：RSSHub 路由预览（无副作用 mutation；路径构造与抓取全部在 BFF，
 * 浏览器不直连 RSSHub）。响应形状与 feed-preview 一致。 */
export async function previewRssHub(
  routeId: string,
  params: Record<string, string>,
): Promise<FeedPreviewMetadata> {
  const response = await rawRequest(`${API_BASE}/rsshub/preview`, {
    method: 'POST',
    body: JSON.stringify({ routeId, params }),
    contentType: 'application/json',
  })
  return (await response.json()) as FeedPreviewMetadata
}

/** 0015：AI 设置（浏览器安全视图；configured 只报告 key 存在与否）。 */
export async function getAiSettings(signal?: AbortSignal): Promise<AiSettings> {
  return request<AiSettings>(`${API_BASE}/settings/ai`, signal)
}

/** 0015：保存非机密 AI 设置（服务端校验；key 永远不可经由本接口读写）。 */
export async function updateAiSettings(update: AiSettingsUpdate): Promise<AiSettings> {
  const response = await rawRequest(`${API_BASE}/settings/ai`, {
    method: 'PUT',
    body: JSON.stringify(update),
    contentType: 'application/json',
  })
  return (await response.json()) as AiSettings
}

/** BFF 构建溯源（关于页版本对照；无 env / 路径 / secret）。 */
export async function getApiVersion(signal?: AbortSignal): Promise<ApiVersion> {
  return request<ApiVersion>(`${API_BASE}/version`, signal)
}

// ---- AI Profiles（浏览器管理的多配置 + 用途分配；key 写只读） ----

/** 所有 AI Profile（元数据 + keyConfigured 布尔，绝不回显 key）。 */
export async function getAiProfiles(signal?: AbortSignal): Promise<AiProfile[]> {
  return request<AiProfile[]>(`${API_BASE}/settings/ai/profiles`, signal)
}

export interface AiProfileInput {
  label: string
  baseUrl?: string
  model?: string
  enabled?: boolean
}

export async function createAiProfile(input: AiProfileInput): Promise<AiProfile> {
  const response = await rawRequest(`${API_BASE}/settings/ai/profiles`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as AiProfile
}

export async function updateAiProfile(
  profileId: string,
  patch: Partial<AiProfileInput>,
): Promise<AiProfile> {
  const response = await rawRequest(
    `${API_BASE}/settings/ai/profiles/${encodeURIComponent(profileId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(patch),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as AiProfile
}

export async function deleteAiProfile(profileId: string): Promise<void> {
  await rawRequest(
    `${API_BASE}/settings/ai/profiles/${encodeURIComponent(profileId)}`,
    { method: 'DELETE' },
  )
}

/** 设置/替换一个 Profile 的 API Key（write-only：204 无响应体，绝不回读）。 */
export async function setAiProfileSecret(
  profileId: string,
  value: string,
): Promise<void> {
  await rawRequest(
    `${API_BASE}/settings/ai/profiles/${encodeURIComponent(profileId)}/secret`,
    {
      method: 'PUT',
      body: JSON.stringify({ value }),
      contentType: 'application/json',
    },
  )
}

export async function clearAiProfileSecret(profileId: string): Promise<void> {
  await rawRequest(
    `${API_BASE}/settings/ai/profiles/${encodeURIComponent(profileId)}/secret`,
    { method: 'DELETE' },
  )
}

/** 默认（legacy）Key：浏览器可写 SecretsStore；env AI_API_KEY 保持回退。 */
export async function setDefaultAiSecret(value: string): Promise<void> {
  await rawRequest(`${API_BASE}/settings/ai/key`, {
    method: 'PUT',
    body: JSON.stringify({ value }),
    contentType: 'application/json',
  })
}

export async function clearDefaultAiSecret(): Promise<void> {
  await rawRequest(`${API_BASE}/settings/ai/key`, { method: 'DELETE' })
}

export async function getAiPurposes(signal?: AbortSignal): Promise<AiPurposes> {
  return request<AiPurposes>(`${API_BASE}/settings/ai/purposes`, signal)
}

export async function updateAiPurposes(
  patch: Partial<Record<AiPurposeKey, string>>,
): Promise<AiPurposes> {
  const response = await rawRequest(`${API_BASE}/settings/ai/purposes`, {
    method: 'PUT',
    body: JSON.stringify(patch),
    contentType: 'application/json',
  })
  return (await response.json()) as AiPurposes
}

/** 0017：读取 portable 设置（GET 无副作用；stored=false = 服务端无文档）。 */
export async function getServerSettings(signal?: AbortSignal): Promise<ServerSettings> {
  return request<ServerSettings>(`${API_BASE}/settings`, signal)
}

/** 0017：部分更新 portable 设置（服务端严格校验；失败抛 ApiError）。
 * 刻意不接 AbortSignal——与其它 mutation 语义一致，发出后允许完成。 */
export async function patchServerSettings(
  patch: Record<string, string | number | boolean>,
): Promise<ServerSettings> {
  const response = await rawRequest(`${API_BASE}/settings`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
    contentType: 'application/json',
  })
  return (await response.json()) as ServerSettings
}

/** 0015：读摘要状态——GET 语义：BFF 绝不调用 AI provider（零成本）。 */
export async function getEntrySummary(
  entryRef: string,
  signal?: AbortSignal,
): Promise<EntrySummary> {
  return request<EntrySummary>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/summary`,
    signal,
  )
}

/** 0015：显式生成摘要（可能产生一次有界 provider 调用；精确缓存命中零成本）。
 * 与其它 mutation 一致：不接 AbortSignal，发出后允许完成。 */
export async function generateEntrySummary(entryRef: string): Promise<EntrySummary> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/summary`,
    { method: 'POST' },
  )
  return (await response.json()) as EntrySummary
}

/** 0016：读翻译状态——GET 语义：BFF 绝不调用 AI provider（零成本）。 */
export async function getEntryTranslation(
  entryRef: string,
  signal?: AbortSignal,
): Promise<EntryTranslation> {
  return request<EntryTranslation>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation`,
    signal,
  )
}

/** 0016：显式生成翻译（可能产生一次有界 provider 调用；精确缓存命中零
 * 成本）。不接 AbortSignal，与其它 mutation 语义一致。 */
export async function generateEntryTranslation(entryRef: string): Promise<EntryTranslation> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation`,
    { method: 'POST' },
  )
  return (await response.json()) as EntryTranslation
}

/** 0016：读文章限定对话——GET 语义：只读 Lumi 消息存储，绝不调用
 * provider（零成本）。 */
export async function getEntryConversation(
  entryRef: string,
  signal?: AbortSignal,
): Promise<EntryConversation> {
  return request<EntryConversation>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/conversation`,
    signal,
  )
}

/** 0016：发送一条文章限定问题（一次有界 provider 调用；成功后问题与
 * 回答持久化并返回完整对话）。不接 AbortSignal，与其它 mutation 一致。 */
export async function sendConversationMessage(
  entryRef: string,
  question: string,
): Promise<EntryConversation> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/conversation/messages`,
    {
      method: 'POST',
      body: JSON.stringify({ question }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as EntryConversation
}

// ---- 0018 Operations / RSSHub Control Center ----

export async function getOperationsStatus(signal?: AbortSignal): Promise<OperationsStatus> {
  return request<OperationsStatus>(`${API_BASE}/operations/status`, signal)
}

export async function getRssHubConfig(signal?: AbortSignal): Promise<RssHubConfig> {
  return request<RssHubConfig>(`${API_BASE}/rsshub/config`, signal)
}

export async function patchRssHubConfig(values: Record<string, number | string | boolean>): Promise<RssHubConfig> {
  const response = await rawRequest(`${API_BASE}/rsshub/config`, {
    method: 'PATCH',
    body: JSON.stringify({ values }),
    contentType: 'application/json',
  })
  return (await response.json()) as RssHubConfig
}

export async function setRssHubSecret(key: string, value: string): Promise<void> {
  await rawRequest(`${API_BASE}/rsshub/config/secrets/${encodeURIComponent(key)}`, {
    method: 'PUT',
    body: JSON.stringify({ value }),
    contentType: 'application/json',
  })
}

export async function clearRssHubSecret(key: string): Promise<void> {
  await rawRequest(`${API_BASE}/rsshub/config/secrets/${encodeURIComponent(key)}`, {
    method: 'DELETE',
  })
}

export async function applyRssHubConfig(): Promise<void> {
  await rawRequest(`${API_BASE}/rsshub/config/apply`, { method: 'POST' })
}

// ---- 0018 WebDAV / Backup / Restore ----

export async function getWebDavSettings(signal?: AbortSignal): Promise<WebDavSettings> {
  return request<WebDavSettings>(`${API_BASE}/backups/webdav`, signal)
}

export async function updateWebDavSettings(body: {
  serverUrl?: string
  username?: string
  password?: string
  remoteDir?: string
  tlsVerify?: boolean
  clearPassword?: boolean
}): Promise<WebDavSettings> {
  const response = await rawRequest(`${API_BASE}/backups/webdav`, {
    method: 'PUT',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  return (await response.json()) as WebDavSettings
}

export async function testWebDav(): Promise<WebDavTestResult> {
  const response = await rawRequest(`${API_BASE}/backups/webdav/test`, { method: 'POST' })
  return (await response.json()) as WebDavTestResult
}

export async function listBackups(signal?: AbortSignal): Promise<BackupJob[]> {
  return request<BackupJob[]>(`${API_BASE}/backups`, signal)
}

export async function getBackupJob(id: string, signal?: AbortSignal): Promise<BackupJob> {
  return request<BackupJob>(`${API_BASE}/backups/${encodeURIComponent(id)}`, signal)
}

export async function getBackupCapabilities(signal?: AbortSignal): Promise<BackupCapabilities> {
  return request<BackupCapabilities>(`${API_BASE}/backups/capabilities`, signal)
}
export interface TranslationSegmentBlockInput {
  index: number
  text: string
}

export async function lookupTranslationSegments(
  entryRef: string,
  blocks: TranslationSegmentBlockInput[],
  signal?: AbortSignal,
): Promise<TranslationSegmentsView> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/segments/lookup`,
    { method: 'POST', body: JSON.stringify({ blocks }), signal, contentType: 'application/json' },
  )
  return (await response.json()) as TranslationSegmentsView
}

export async function generateTranslationSegments(
  entryRef: string,
  blocks: TranslationSegmentBlockInput[],
  signal?: AbortSignal,
): Promise<TranslationSegmentsView> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/segments/generate`,
    { method: 'POST', body: JSON.stringify({ blocks }), signal, contentType: 'application/json' },
  )
  return (await response.json()) as TranslationSegmentsView
}

export async function saveLibreTranslateKey(value: string): Promise<void> {
  await rawRequest(`${API_BASE}/settings/translation/libretranslate-key`, {
    method: 'PUT',
    body: JSON.stringify({ value }),
    contentType: 'application/json',
  })
}

export async function clearLibreTranslateKey(): Promise<void> {
  await rawRequest(`${API_BASE}/settings/translation/libretranslate-key`, {
    method: 'DELETE',
  })
}

export async function testLibreTranslate(): Promise<{ status: 'ok' | 'failed'; message: string | null }> {
  const response = await rawRequest(`${API_BASE}/settings/translation/libretranslate-test`, {
    method: 'POST',
  })
  return (await response.json()) as { status: 'ok' | 'failed'; message: string | null }
}

export interface RssHubCredentialEntry {
  id: string
  name: string
  domain: string
  route: string
  envKey: string
  kind: string
  configured: boolean
  createdAt: string
  updatedAt: string
}

export interface RssHubCredentialInput {
  name: string
  domain: string
  envKey: string
  kind: string
  value: string
  route: string
}

export interface RssHubDetectCandidate {
  url: string
  source: string
  reachable: boolean
  latencyMs: number | null
}

export async function detectRssHub(signal?: AbortSignal): Promise<{
  configured: boolean
  candidates: RssHubDetectCandidate[]
}> {
  return request<{ configured: boolean; candidates: RssHubDetectCandidate[] }>(
    `${API_BASE}/rsshub/detect`,
    signal,
  )
}

export async function listRssHubCredentials(signal?: AbortSignal): Promise<RssHubCredentialEntry[]> {
  return request<RssHubCredentialEntry[]>(`${API_BASE}/rsshub/credentials`, signal)
}

export async function createRssHubCredential(input: RssHubCredentialInput): Promise<RssHubCredentialEntry> {
  const response = await rawRequest(`${API_BASE}/rsshub/credentials`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as RssHubCredentialEntry
}

export async function deleteRssHubCredential(id: string): Promise<void> {
  await rawRequest(`${API_BASE}/rsshub/credentials/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

export async function materializeRssHubEnvFile(): Promise<{
  fileName: string
  dirName: string
  lineCount: number
  secretCount: number
  customCredentialCount: number
  note: string
}> {
  const response = await rawRequest(`${API_BASE}/rsshub/config/env-file`, {
    method: 'POST',
  })
  return (await response.json()) as {
    fileName: string
    dirName: string
    lineCount: number
    secretCount: number
    customCredentialCount: number
    note: string
  }
}

export async function createBackup(target: 'local' | 'webdav'): Promise<BackupJob> {
  const response = await rawRequest(`${API_BASE}/backups`, {
    method: 'POST',
    body: JSON.stringify({ target }),
    contentType: 'application/json',
  })
  return (await response.json()) as BackupJob
}

export async function listRemoteBackups(signal?: AbortSignal): Promise<RemoteBackupsResponse> {
  return request<RemoteBackupsResponse>(`${API_BASE}/backups/remote`, signal)
}

export async function previewRestore(source: {
  source: 'local' | 'remote'
  jobId?: string
  fileName?: string
}): Promise<RestorePreview> {
  const response = await rawRequest(`${API_BASE}/restore/preview`, {
    method: 'POST',
    body: JSON.stringify(source),
    contentType: 'application/json',
  })
  return (await response.json()) as RestorePreview
}

export async function executeRestore(restoreSessionId: string, confirmation: string): Promise<RestoreResult> {
  const response = await rawRequest(`${API_BASE}/restore`, {
    method: 'POST',
    body: JSON.stringify({ restoreSessionId, confirmation }),
    contentType: 'application/json',
  })
  return (await response.json()) as RestoreResult
}

// ---- phase2 M1：稍后读 = 服务端保留工作区（read-later）的成员同步 ----
// Primary 拥有这三个契约函数（read-later 双写依赖）；书签/工作区完整
// API 面由 library 域各函数另行补充。

export async function listWorkspaceItems(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<WorkspaceItemsResponse> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/items`,
    { method: 'GET', signal },
  )
  return (await response.json()) as WorkspaceItemsResponse
}

export async function addWorkspaceItem(workspaceId: string, itemRef: string): Promise<WorkspaceItem> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/items`,
    {
      method: 'POST',
      body: JSON.stringify({ itemRef }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as WorkspaceItem
}

export async function removeWorkspaceItem(workspaceId: string, itemRef: string): Promise<void> {
  await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/items/${encodeURIComponent(itemRef)}`,
    { method: 'DELETE' },
  )
}

// ---- phase2 M1：书签（library/bookmarks）——GET 分页 / POST 幂等创建 /
// PATCH 编辑 / DELETE / Netscape HTML 导入导出。ref 形如 `library:<uuid>`，
// 路径参数取 uuid 部分（本模块负责剥离，UI 只透传 ref）。 ----

/** `library:<uuid>` → `<uuid>`（容错裸 uuid，原样返回）。 */
function toBookmarkId(bookmarkRef: string): string {
  return bookmarkRef.startsWith('library:') ? bookmarkRef.slice('library:'.length) : bookmarkRef
}

export async function listBookmarks(
  params: { cursor?: string | null; limit?: number; q?: string | null } = {},
  signal?: AbortSignal,
): Promise<BookmarkListResponse> {
  const query = new URLSearchParams()
  // cursor 是 opaque string：原样传递，绝不 decode / parse / 修改。
  if (params.cursor != null) {
    query.set('cursor', params.cursor)
  }
  if (params.limit != null) {
    query.set('limit', String(params.limit))
  }
  if (params.q != null && params.q !== '') {
    query.set('q', params.q)
  }
  const qs = query.toString()
  return request<BookmarkListResponse>(`${API_BASE}/library/bookmarks?${qs}`, signal)
}

/** 创建书签（url | rssItemRef 二选一）；重复 url/rssItemRef 幂等返回同一
 * ref。不接 AbortSignal——与其它 mutation 语义一致，发出后允许完成。 */
export async function createBookmark(body: {
  url?: string | null
  rssItemRef?: string | null
  title: string
  note?: string | null
}): Promise<Bookmark> {
  const response = await rawRequest(`${API_BASE}/library/bookmarks`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  return (await response.json()) as Bookmark
}

export async function updateBookmark(
  bookmarkRef: string,
  patch: { title?: string | null; note?: string | null },
): Promise<Bookmark> {
  const response = await rawRequest(
    `${API_BASE}/library/bookmarks/${encodeURIComponent(toBookmarkId(bookmarkRef))}`,
    {
      method: 'PATCH',
      body: JSON.stringify(patch),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as Bookmark
}

export async function deleteBookmark(bookmarkRef: string): Promise<void> {
  await rawRequest(
    `${API_BASE}/library/bookmarks/${encodeURIComponent(toBookmarkId(bookmarkRef))}`,
    { method: 'DELETE' },
  )
}

/** Netscape 书签 HTML 导入（原始文件上传；BFF 负责解析与逐条结果）。
 * Content-Type 固定 text/html（Netscape 格式即 HTML）。 */
export async function importBookmarks(file: File): Promise<BookmarkImportResult> {
  const response = await rawRequest(`${API_BASE}/library/bookmarks/import`, {
    method: 'POST',
    body: file,
    contentType: 'text/html',
  })
  return (await response.json()) as BookmarkImportResult
}

// ---- phase2 M1：工作区（workspaces）——列表 / 创建 / contents 解析 /
// 重排序。read-later 为保留工作区（reserved=true，BFF 拒绝删除/重排）。 ----

export async function listWorkspaces(signal?: AbortSignal): Promise<WorkspaceListResponse> {
  return request<WorkspaceListResponse>(`${API_BASE}/workspaces`, signal)
}

export async function createWorkspace(name: string): Promise<Workspace> {
  const response = await rawRequest(`${API_BASE}/workspaces`, {
    method: 'POST',
    body: JSON.stringify({ name }),
    contentType: 'application/json',
  })
  return (await response.json()) as Workspace
}

/** 工作区内容（ResolvedItem 统一视图：rss + library 解析后的卡片数据）。 */
export async function getWorkspaceContents(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<WorkspaceItemsResolvedResponse> {
  return request<WorkspaceItemsResolvedResponse>(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/contents`,
    signal,
  )
}

/** 重排序：按新顺序传完整 itemRefs（≤500，BFF 校验）。 */
export async function reorderWorkspaceItems(
  workspaceId: string,
  itemRefs: string[],
): Promise<WorkspaceItemsResponse> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/items`,
    {
      method: 'PATCH',
      body: JSON.stringify({ itemRefs }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as WorkspaceItemsResponse
}

// ---- phase2 Gate 3：网页剪藏（library/clips） ----
// 抓取（SSRF 受限）→ 本地提取 → 存储三步由页面编排；ref 形如
// `library:<uuid>`，路径参数取 uuid 部分（本模块负责剥离，UI 只透传
// ref，与书签同一模式）。

/** `library:<uuid>` → `<uuid>`（容错裸 uuid，原样返回）。 */
function toClipId(clipRef: string): string {
  return clipRef.startsWith('library:') ? clipRef.slice('library:'.length) : clipRef
}

/** 服务端匿名抓取目标页 HTML（SSRF 守卫：只放行公网 http/https、
 * MIME 白名单、5MB / 20s 上限；400 clip_fetch_forbidden /
 * 502 clip_fetch_failed 由 UI 原样展示 message）。无副作用 mutation
 * 语义：不接 AbortSignal，发出后允许完成。 */
export async function fetchClipHtml(url: string): Promise<ClipFetchResult> {
  const response = await rawRequest(`${API_BASE}/library/clips/fetch`, {
    method: 'POST',
    body: JSON.stringify({ url }),
    contentType: 'application/json',
  })
  return (await response.json()) as ClipFetchResult
}

export interface ClipInput {
  url: string
  title: string
  byline?: string | null
  contentHtml: string
  contentText: string
  fetchedAt?: string
}

/** 保存剪藏（contentHtml 必须已过 DOMPurify——见 lib/clip-extract.ts；
 * 重复 url 幂等返回同一 ref）。不接 AbortSignal，与其它 mutation 一致。 */
export async function createClip(body: ClipInput): Promise<ClipDetail> {
  const response = await rawRequest(`${API_BASE}/library/clips`, {
    method: 'POST',
    body: JSON.stringify({
      url: body.url,
      title: body.title,
      byline: body.byline ?? null,
      contentHtml: body.contentHtml,
      contentText: body.contentText,
      fetchedAt: body.fetchedAt ?? new Date().toISOString(),
    }),
    contentType: 'application/json',
  })
  return (await response.json()) as ClipDetail
}

/** 剪藏列表（cursor opaque 透传）。 */
export async function listClips(
  cursor?: string | null,
  limit?: number,
  signal?: AbortSignal,
): Promise<ClipListResponse> {
  const query = new URLSearchParams()
  if (cursor != null) {
    query.set('cursor', cursor)
  }
  if (limit != null) {
    query.set('limit', String(limit))
  }
  const qs = query.toString()
  return request<ClipListResponse>(`${API_BASE}/library/clips?${qs}`, signal)
}

/** 读单条剪藏 Detail（含 contentHtml/contentText）。 */
export async function getClip(uuid: string, signal?: AbortSignal): Promise<ClipDetail> {
  return request<ClipDetail>(
    `${API_BASE}/library/clips/${encodeURIComponent(toClipId(uuid))}`,
    signal,
  )
}

/** 删除剪藏（破坏性；DELETE 204，无响应体）。 */
export async function deleteClip(uuid: string): Promise<void> {
  await rawRequest(
    `${API_BASE}/library/clips/${encodeURIComponent(toClipId(uuid))}`,
    { method: 'DELETE' },
  )
}

// ---- phase2 Gate 3：网页快照（library/snapshots，monolith） ----
// 服务端依赖外部 monolith 二进制；未配置时 503 monolith_unavailable，
// UI 原样透出 message。生成是长任务（10–90s）。

/** 生成离线快照（长任务；成功返回 SnapshotView，deduplicated 标记
 * 内容去重）。不接 AbortSignal，与其它 mutation 一致。 */
export async function createSnapshot(url: string): Promise<SnapshotView> {
  const response = await rawRequest(`${API_BASE}/library/snapshots`, {
    method: 'POST',
    body: JSON.stringify({ url }),
    contentType: 'application/json',
  })
  return (await response.json()) as SnapshotView
}

/** 快照列表 + 用量（count / bytes / quotaBytes）。 */
export async function listSnapshots(signal?: AbortSignal): Promise<SnapshotListResponse> {
  return request<SnapshotListResponse>(`${API_BASE}/library/snapshots`, signal)
}

/** 删除快照（DELETE 204，无响应体）。 */
export async function deleteSnapshot(uuid: string): Promise<void> {
  await rawRequest(
    `${API_BASE}/library/snapshots/${encodeURIComponent(uuid)}`,
    { method: 'DELETE' },
  )
}

// ---- phase2 G6：API 来源 / 邮件简报 / Obsidian 库 / 联合收藏 ----
// 契约别名：与 types.ts 同一策略（派生自 generated/schema）。本批别名
// 尚未收录进 types.ts，按任务约定在本模块内补齐（additive，不改既有导出）。

import type { components } from './generated/schema'

type G6Schemas = components['schemas']

export type ApiSource = G6Schemas['ApiSource']
export type ApiSourceListResponse = G6Schemas['ApiSourceListResponse']
export type ApiSourcePreviewResult = G6Schemas['ApiSourcePreviewResult']
export type MailBridgeList = G6Schemas['MailBridgeList']
export type MailBridgeListCreated = G6Schemas['MailBridgeListCreated']
export type MailBridgeListResponse = G6Schemas['MailBridgeListResponse']
export type MailIngestResult = G6Schemas['MailIngestResult']
export type DigestSettings = G6Schemas['DigestSettings']
export type DigestSettingsUpdate = G6Schemas['DigestSettingsUpdate']
export type ObsidianStatus = G6Schemas['ObsidianStatus']
export type ObsidianSettings = G6Schemas['ObsidianSettings']
export type ObsidianRescanResult = G6Schemas['ObsidianRescanResult']
export type NoteView = G6Schemas['NoteView']
export type NoteListResponse = G6Schemas['NoteListResponse']
export type FavoritesResponse = G6Schemas['FavoritesResponse']
export type LibrarySearchItem = G6Schemas['LibrarySearchItem']

/** 共享剪藏/书签/Obsidian 笔记的 ref 约定：`library:<uuid>` → `<uuid>`。 */
function toLibraryItemId(ref: string): string {
  return ref.startsWith('library:') ? ref.slice('library:'.length) : ref
}

// ---- phase2 G6：API 来源（api-sources） ----

/** fieldMap 五字段 → JMESPath 表达式（契约是 Record<string,string>，
 * 这里收窄为固定五键，UI 构造时保证键齐全；空串 = 未映射）。 */
export interface ApiSourceFieldMapInput {
  id: string
  title: string
  url: string
  published: string
  body: string
}

export interface ApiSourceCreateInput {
  name: string
  endpoint: string
  itemsExpr: string
  fieldMap: ApiSourceFieldMapInput
  subscribe?: boolean
}

export interface ApiSourcePreviewInput {
  endpoint: string
  itemsExpr: string
  fieldMap: ApiSourceFieldMapInput
}

export interface ApiSourceUpdateInput {
  name?: string | null
  endpoint?: string | null
  itemsExpr?: string | null
  fieldMap?: ApiSourceFieldMapInput | null
  enabled?: boolean | null
}

/** API 来源列表（GET 语义）。 */
export async function listApiSources(signal?: AbortSignal): Promise<ApiSourceListResponse> {
  return request<ApiSourceListResponse>(`${API_BASE}/api-sources`, signal)
}

/** 创建 API 来源。成功响应是唯一一次包含 secret / atomPath 的机会；
 * 失败（如自动订阅失败）仍返回 201 + subscribeError，由 UI 诚实展示。 */
export async function createApiSource(input: ApiSourceCreateInput): Promise<ApiSource> {
  const response = await rawRequest(`${API_BASE}/api-sources`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as ApiSource
}

/** 更新 API 来源（PATCH，部分字段；enabled 开关走这里）。 */
export async function updateApiSource(
  uuid: string,
  patch: ApiSourceUpdateInput,
): Promise<ApiSource> {
  const response = await rawRequest(
    `${API_BASE}/api-sources/${encodeURIComponent(uuid)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(patch),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as ApiSource
}

/** 删除 API 来源（破坏性；DELETE 204；服务端自动退订对应 FreshRSS 订阅）。 */
export async function deleteApiSource(uuid: string): Promise<void> {
  await rawRequest(`${API_BASE}/api-sources/${encodeURIComponent(uuid)}`, {
    method: 'DELETE',
  })
}

/** 无副作用预览：按 endpoint + itemsExpr + fieldMap 实抓 ≤5 条映射结果。
 * 400 invalid_expression / invalid_api_source、502 fetch_failed 的
 * error.message 由 UI 原样透出。 */
export async function previewApiSource(
  input: ApiSourcePreviewInput,
): Promise<ApiSourcePreviewResult> {
  const response = await rawRequest(`${API_BASE}/api-sources/preview`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as ApiSourcePreviewResult
}

// ---- phase2 G6：邮件（收信地址 + 每日摘要） ----

/** 收信地址列表（secret 绝不回显）。 */
export async function listMailBridgeLists(
  signal?: AbortSignal,
): Promise<MailBridgeListResponse> {
  return request<MailBridgeListResponse>(`${API_BASE}/mail/bridge-lists`, signal)
}

/** 创建收信地址。成功响应是唯一一次返回 bearer secret 的机会。 */
export async function createMailBridgeList(name: string): Promise<MailBridgeListCreated> {
  const response = await rawRequest(`${API_BASE}/mail/bridge-lists`, {
    method: 'POST',
    body: JSON.stringify({ name }),
    contentType: 'application/json',
  })
  return (await response.json()) as MailBridgeListCreated
}

/** 删除收信地址（破坏性；DELETE 204）。 */
export async function deleteMailBridgeList(uuid: string): Promise<void> {
  await rawRequest(`${API_BASE}/mail/bridge-lists/${encodeURIComponent(uuid)}`, {
    method: 'DELETE',
  })
}

/** 每日摘要设置（password 只报告 passwordConfigured 布尔，绝不回显）。 */
export async function getDigestSettings(signal?: AbortSignal): Promise<DigestSettings> {
  return request<DigestSettings>(`${API_BASE}/digest/settings`, signal)
}

/** 部分更新摘要设置；smtpPassword write-only（留空 = 不改动）。 */
export async function updateDigestSettings(
  patch: DigestSettingsUpdate,
): Promise<DigestSettings> {
  const response = await rawRequest(`${API_BASE}/digest/settings`, {
    method: 'PUT',
    body: JSON.stringify(patch),
    contentType: 'application/json',
  })
  return (await response.json()) as DigestSettings
}

export interface DigestEntryRefInput {
  title: string
  url: string
  source: string
}

/** 立即发送摘要（显式条目选择；503 smtp_not_configured /
 * 502 smtp_send_failed 的 error.message 由 UI 原样透出）。 */
export async function sendDigestNow(
  entryRefs: DigestEntryRefInput[],
): Promise<MailIngestResult> {
  const response = await rawRequest(`${API_BASE}/digest/send-now`, {
    method: 'POST',
    body: JSON.stringify({ entryRefs }),
    contentType: 'application/json',
  })
  return (await response.json()) as MailIngestResult
}

// ---- phase2 G6：Obsidian 库（只读投影） ----

/** Obsidian 扫描状态（错误时保留旧索引可见）。 */
export async function getObsidianStatus(signal?: AbortSignal): Promise<ObsidianStatus> {
  return request<ObsidianStatus>(`${API_BASE}/obsidian/status`, signal)
}

/** 连接 Vault（canonicalize 在服务端；503 vault_unreachable /
 * 403 vault_permission_denied 的 error.message 由 UI 原样透出）。 */
export async function updateObsidianSettings(vaultPath: string): Promise<ObsidianSettings> {
  const response = await rawRequest(`${API_BASE}/obsidian/settings`, {
    method: 'PUT',
    body: JSON.stringify({ vaultPath }),
    contentType: 'application/json',
  })
  return (await response.json()) as ObsidianSettings
}

/** 重新扫描（有界扫描 + 改名检测；长任务语义，不接 AbortSignal）。 */
export async function rescanObsidian(): Promise<ObsidianRescanResult> {
  const response = await rawRequest(`${API_BASE}/obsidian/rescan`, { method: 'POST' })
  return (await response.json()) as ObsidianRescanResult
}

/** 笔记列表（q 可选服务端过滤；limit 由页面界定）。 */
export async function listObsidianNotes(
  params: { q?: string | null; limit?: number } = {},
  signal?: AbortSignal,
): Promise<NoteListResponse> {
  const query = new URLSearchParams()
  if (params.q != null && params.q !== '') {
    query.set('q', params.q)
  }
  if (params.limit != null) {
    query.set('limit', String(params.limit))
  }
  const qs = query.toString()
  return request<NoteListResponse>(`${API_BASE}/obsidian/notes?${qs}`, signal)
}

/** 单条笔记 Detail（含原始 markdown 渲染的 contentHtml —— 不可信输入，
 * 渲染前必须过 lib/sanitize-article-html.ts；ref 为 `library:<uuid>`，
 * 路径参数取 uuid 部分，与书签/剪藏同一模式）。 */
export async function getObsidianNote(
  noteRef: string,
  signal?: AbortSignal,
): Promise<NoteView> {
  return request<NoteView>(
    `${API_BASE}/obsidian/notes/${encodeURIComponent(toLibraryItemId(noteRef))}`,
    signal,
  )
}

// ---- phase2 G6：联合收藏（RSS star + library favorite，仅展示层合并） ----

/** 联合收藏视图（两个域各自保有所有权，BFF 只做展示合并）。 */
export async function getFavorites(signal?: AbortSignal): Promise<FavoritesResponse> {
  return request<FavoritesResponse>(`${API_BASE}/favorites`, signal)
}

/** 添加库收藏（幂等；POST 204）。 */
export async function addLibraryFavorite(ref: string): Promise<void> {
  await rawRequest(`${API_BASE}/favorites/library`, {
    method: 'POST',
    body: JSON.stringify({ ref }),
    contentType: 'application/json',
  })
}

/** 移除库收藏（DELETE 204；契约带 JSON body）。 */
export async function removeLibraryFavorite(ref: string): Promise<void> {
  await rawRequest(`${API_BASE}/favorites/library`, {
    method: 'DELETE',
    body: JSON.stringify({ ref }),
    contentType: 'application/json',
  })
}

// ---- phase2 G7/G8：Agent 工作台 / 标签 / 关系图谱 / RAG ----
// 契约类型：generated schema 快照尚未收录本批端点（agent/tags/graph/rag
// 不在 components['schemas'] 内，openapi 未再生成），按任务约定在本模块
// 内以本地 interface 补齐（additive，不改既有导出）；字段与 BFF
// models.py / routers 逐一对照（AgentThread / AgentMessage / TagBinding /
// GraphResponse / Rag*）。

export interface AgentThread {
  id: string
  title: string
  createdAt: string
}

export interface AgentThreadListResponse {
  items: AgentThread[]
}

export type AgentMessageRole = 'user' | 'assistant' | 'tool' | 'system' | 'approval'

/** approval 消息 content：{approvalId, callId, tool, args, status, expiresInMinutes}。 */
export interface AgentApprovalContent {
  approvalId: string
  callId: string
  tool: string
  args: Record<string, unknown>
  status: string
  expiresInMinutes?: number
}

export interface AgentMessage {
  id: string
  threadId: string
  seq: number
  role: AgentMessageRole
  content: Record<string, unknown>
  citations: string[]
  createdAt: string
}

export interface AgentMessageListResponse {
  items: AgentMessage[]
}

export type AgentApprovalDecision = 'approve' | 'reject'

/** 会话列表（GET 语义）。 */
export async function listAgentThreads(signal?: AbortSignal): Promise<AgentThreadListResponse> {
  return request<AgentThreadListResponse>(`${API_BASE}/agent/threads`, signal)
}

/** 新建会话（POST 201，返回服务端确认的新线程）。 */
export async function createAgentThread(): Promise<AgentThread> {
  const response = await rawRequest(`${API_BASE}/agent/threads`, { method: 'POST' })
  return (await response.json()) as AgentThread
}

/** 删除会话（破坏性；DELETE 204）。 */
export async function deleteAgentThread(threadId: string): Promise<void> {
  await rawRequest(`${API_BASE}/agent/threads/${encodeURIComponent(threadId)}`, {
    method: 'DELETE',
  })
}

/** 读回消息（after=N 增量；本页取全量 after=0，由 TanStack 缓存持有）。 */
export async function listAgentMessages(
  threadId: string,
  after: number,
  signal?: AbortSignal,
): Promise<AgentMessageListResponse> {
  return request<AgentMessageListResponse>(
    `${API_BASE}/agent/threads/${encodeURIComponent(threadId)}/messages?after=${after}`,
    signal,
  )
}

/** 发送一轮用户输入（202 {status:'processing'}）；循环在服务端异步执行，
 * 结果经 /messages 轮询（或 SSE）读回。 */
export async function sendAgentMessage(threadId: string, text: string): Promise<{ status: string }> {
  const response = await rawRequest(
    `${API_BASE}/agent/threads/${encodeURIComponent(threadId)}/messages`,
    {
      method: 'POST',
      body: JSON.stringify({ text }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as { status: string }
}

/** 写操作批准/拒绝（服务端绑定 thread+call+args hash 后才执行真实写入）。 */
export async function decideAgentApproval(
  threadId: string,
  approvalId: string,
  decision: AgentApprovalDecision,
): Promise<{ status: string; message: AgentMessage | null }> {
  const response = await rawRequest(
    `${API_BASE}/agent/threads/${encodeURIComponent(threadId)}/approvals`,
    {
      method: 'POST',
      body: JSON.stringify({ approvalId, decision }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as { status: string; message: AgentMessage | null }
}

// ---- phase2 G8：标签（tags） ----

export interface TagSummary {
  id: number
  name: string
  count: number
}

export interface TagListResponse {
  items: TagSummary[]
}

export interface TagAssignInput {
  itemRef: string
  name: string
  origin?: string
}

/** 标签列表（q 可选服务端过滤；建议行不出现）。 */
export async function listTags(q: string | null, signal?: AbortSignal): Promise<TagListResponse> {
  const query = new URLSearchParams()
  if (q != null && q !== '') {
    query.set('q', q)
  }
  const qs = query.toString()
  return request<TagListResponse>(`${API_BASE}/tags?${qs}`, signal)
}

/** 重命名标签（PATCH 200，返回更新后的 binding 视图）。 */
export async function renameTag(tagId: number, name: string): Promise<unknown> {
  const response = await rawRequest(`${API_BASE}/tags/${encodeURIComponent(String(tagId))}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
    contentType: 'application/json',
  })
  return (await response.json()) as unknown
}

/** 删除标签（破坏性；DELETE 204）。 */
export async function deleteTag(tagId: number): Promise<void> {
  await rawRequest(`${API_BASE}/tags/${encodeURIComponent(String(tagId))}`, {
    method: 'DELETE',
  })
}

/** 绑定标签（POST 201 TagBinding）。 */
export async function assignTag(input: TagAssignInput): Promise<unknown> {
  const response = await rawRequest(`${API_BASE}/tags/assign`, {
    method: 'POST',
    body: JSON.stringify({ itemRef: input.itemRef, name: input.name, origin: input.origin ?? 'manual' }),
    contentType: 'application/json',
  })
  return (await response.json()) as unknown
}

/** 解绑标签（DELETE 204，契约带 JSON body）。 */
export async function unassignTag(input: TagAssignInput): Promise<void> {
  await rawRequest(`${API_BASE}/tags/assign`, {
    method: 'DELETE',
    body: JSON.stringify({ itemRef: input.itemRef, name: input.name, origin: input.origin ?? 'manual' }),
    contentType: 'application/json',
  })
}

// ---- phase2 G8：关系图谱（graph，只读派生视图） ----

export interface GraphNode {
  ref: string
  label: string
  kind: string
  degree: number
}

export interface GraphEdge {
  src: string
  dst: string
  kind: string
}

export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
  truncated: boolean
  totalNodes: number
}

/** 关系图谱（scope=all|workspace:<id>；max 上限由 BFF 钳制）。 */
export async function getGraph(
  scope: string,
  max: number,
  signal?: AbortSignal,
): Promise<GraphResponse> {
  const query = new URLSearchParams()
  query.set('scope', scope)
  query.set('max', String(max))
  return request<GraphResponse>(`${API_BASE}/graph?${query}`, signal)
}

// ---- phase2 G7：RAG（显式启用 / 重建 / 混合检索；状态仅展示） ----

export interface RagStatus {
  enabled: boolean
  chunks: number
  model: string
  vecTable: string | boolean
  lastRebuildAt: string | null
  lastError: string | null
  fastembedAvailable: boolean
}

export interface RagSearchItem {
  ref: string
  kind: string
  text: string
  score: number
}

export interface RagSearchResponse {
  items: RagSearchItem[]
  semanticUsed: boolean
  semanticError: string | null
}

/** RAG 状态（GET 语义，零成本；Agent 页状态 chip 用）。 */
export async function getRagStatus(signal?: AbortSignal): Promise<RagStatus> {
  return request<RagStatus>(`${API_BASE}/rag/status`, signal)
}

/** 显式启用语义索引（用户授权下载/加载嵌入模型）。 */
export async function enableRag(): Promise<{ enabled: boolean }> {
  const response = await rawRequest(`${API_BASE}/rag/enable`, { method: 'POST' })
  return (await response.json()) as { enabled: boolean }
}

/** 重建索引（长任务语义；报告 chunks / elapsedMs）。 */
export async function rebuildRag(): Promise<{ chunks: number; elapsedMs: number }> {
  const response = await rawRequest(`${API_BASE}/rag/rebuild`, { method: 'POST' })
  return (await response.json()) as { chunks: number; elapsedMs: number }
}

/** 混合检索（语义 + 关键词；honest degradation flags）。 */
export async function searchRag(
  q: string,
  k: number,
  signal?: AbortSignal,
): Promise<RagSearchResponse> {
  const query = new URLSearchParams()
  query.set('q', q)
  query.set('k', String(k))
  return request<RagSearchResponse>(`${API_BASE}/rag/search?${query}`, signal)
}
