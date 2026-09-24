/** LumiRSS API client — 只访问相对 /api/v1/*，所有 BFF HTTP 调用集中在此。
 * 读：getFeeds / getEntries / getEntry；写：setEntryState（set 语义）。 */

import { sessionExpired } from '../store/auth'
import type {
  AiProfile,
  AiProfileProvider,
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
  ClipFetchArticleResult,
  ClipListResponse,
  TranslationSegmentsView,
  TranslationVerificationView,
  Category,
  EntryConversation,
  EntryDetail,
  EntryListResponse,
  EntryRevisionsResponse,
  EntrySummary,
  EntryTranslation,
  Feed,
  FeedPreviewMetadata,
  FreshRssNativeUrl,
  FreshRssUiInfo,
  InboxItemList,
  InboxSource,
  InboxSourceCreated,
  OpmlImportPreview,
  OpmlImportResult,
  OperationsStatus,
  ReadLaterTimelineResponse,
  RemoteBackupsResponse,
  RestorePreview,
  RestoreResult,
  RssHubConfig,
  RssHubFavoriteItem,
  RssHubPreviewMetadata,
  RssHubRecentItem,
  RssHubRefreshResult,
  RssHubRouteRuns,
  RssHubRoutesResponse,
  SearchResponse,
  ServerSettings,
  SnapshotListResponse,
  SnapshotView,
  SourceDiscoveryResponse,
  SourceRegistryResponse,
  Subscription,
  SavedSearchView,
  SavedSearchViewList,
  TagMergePreview,
  TagMergeResult,
  WebDavSettings,
  WebDavTestResult,
  Workspace,
  WorkspaceItem,
  WorkspaceGroupsResponse,
  WorkspaceItemsResolvedResponse,
  WorkspaceItemsResponse,
  WorkspaceListResponse,
  WorkspaceResumeResponse,
  WorkspaceSnapshot,
  WorkspaceSnapshotList,
  WorkspaceSnapshotRestoreResult,
  QueueGenerateResponse,
  QueueItemView,
  QueueSnapshotDetail,
  QueueSnapshotList,
  QueueSnapshotView,
  QueueTodayResponse,
} from './types'

const API_BASE = '/api/v1'

/** 安全的错误对象：UI 只显示它的 message，永远不显示原始响应体。 */
export class ApiError extends Error {
  readonly status: number
  readonly type: string
  /** 429 rate_limited 的剩余等待秒数（Retry-After 头）；无该头为 null。 */
  readonly retryAfterSeconds: number | null
  /** 稳定错误族附带的额外标量（如 invite_not_active 的 serverTime /
   * notBefore）；服务端没给就是 null。UI 绝不从这里读秘密材料。 */
  readonly extra: Record<string, string> | null

  constructor(
    status: number,
    type: string,
    message: string,
    retryAfterSeconds: number | null = null,
    extra: Record<string, string> | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.type = type
    this.retryAfterSeconds = retryAfterSeconds
    this.extra = extra
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
  let extra: Record<string, string> | null = null
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
      // 稳定错误族的附加标量（如 invite_not_active 的 serverTime /
      // notBefore）——只收集字符串值，绝不携带任何秘密材料。
      const extras: Record<string, string> = {}
      for (const [key, value] of Object.entries(err as Record<string, unknown>)) {
        if (key !== 'type' && key !== 'message' && typeof value === 'string') {
          extras[key] = value
        }
      }
      if (Object.keys(extras).length > 0) {
        extra = extras
      }
    }
  } catch {
    // 非 JSON（如 HTML 错误页 / 422 detail 数组）→ 使用安全 fallback。
  }
  // 429 rate_limited：读 Retry-After 头（秒）供 UI 显示剩余等待。
  let retryAfterSeconds: number | null = null
  const retryAfterRaw = response.headers.get('Retry-After')
  if (retryAfterRaw !== null && /^\d+$/.test(retryAfterRaw.trim())) {
    retryAfterSeconds = Number.parseInt(retryAfterRaw.trim(), 10)
  }
  return new ApiError(response.status, type, message, retryAfterSeconds, extra)
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

/** N007 两步验证：密码正确但账号开启了 TOTP 时，登录响应是
 * {totpRequired, pendingToken}（短时效、非会话），随后以
 * verifyTotpLogin 换发真会话。 */
export interface LoginChallengeView {
  totpRequired: true
  pendingToken: string
}

export type LoginResponse = AuthStatusView | LoginChallengeView

export function isTotpChallenge(response: LoginResponse): response is LoginChallengeView {
  return (response as LoginChallengeView).totpRequired === true
}

// ---- N006 通行密钥 / N007 两步验证（账户安全 + 登录面） ----
// 契约类型在本模块声明（additive，与 0067 端点同一策略；BFF 是唯一
// 真源，generated/schema 由 pnpm api:generate 再生成兜底）。

/** 通行密钥列表项：id/label/时间戳 —— 服务端契约保证绝不含密钥材料。 */
export interface PasskeyCredential {
  id: string
  label: string
  /** epoch 秒（BFF 控制库行）。 */
  createdAt: number
  lastUsedAt: number | null
}

/** 注册/登录 ceremony options（WebAuthn publicKey JSON，base64url 字段）。 */
export interface PasskeyOptionsResponse {
  publicKey: Record<string, unknown>
  /** 单次挑战：finish 时原样回传给服务端核销。 */
  challenge: string
}

export interface PasskeyLoginOptionsResponse extends PasskeyOptionsResponse {
  /** 该用户名下有已注册的通行密钥（未知用户/无密钥 → false，同形）。 */
  passkeyAvailable: boolean
}

export interface TotpSetupView {
  secret: string
  otpauthUri: string
}

export interface TotpStatusView {
  enabled: boolean
  recoveryCodesRemaining: number
}

/** 通行密钥注册开始（session 会话内）。 */
export async function beginPasskeyRegistration(): Promise<PasskeyOptionsResponse> {
  const response = await rawRequest(`${API_BASE}/auth/passkeys/options`, {
    method: 'POST',
    body: JSON.stringify({}),
    contentType: 'application/json',
  })
  return (await response.json()) as PasskeyOptionsResponse
}

/** 通行密钥注册完成（challenge 回传核销 + RegistrationResponse）。 */
export async function finishPasskeyRegistration(body: {
  label: string
  challenge: string
  credential: Record<string, unknown>
}): Promise<PasskeyCredential> {
  const response = await rawRequest(`${API_BASE}/auth/passkeys`, {
    method: 'POST',
    body: JSON.stringify({
      label: body.label,
      challenge: body.challenge,
      ...body.credential,
    }),
    contentType: 'application/json',
  })
  return (await response.json()) as PasskeyCredential
}

/** 通行密钥列表（id/label/created/last-used，绝无密钥材料）。 */
export async function listPasskeys(signal?: AbortSignal): Promise<PasskeyCredential[]> {
  return request<PasskeyCredential[]>(`${API_BASE}/auth/passkeys`, signal)
}

/** 删除通行密钥：服务端强制当前密码（+TOTP 验证码，当两步验证开启）。 */
export async function deletePasskey(
  credentialId: string,
  currentPassword: string,
  totpCode?: string,
): Promise<void> {
  await rawRequest(`${API_BASE}/auth/passkeys/${encodeURIComponent(credentialId)}`, {
    method: 'DELETE',
    body: JSON.stringify({
      currentPassword,
      ...(totpCode ? { totpCode } : {}),
    }),
    contentType: 'application/json',
  })
}

/** 通行密钥登录 options（公开；未知用户名返回诚实通用响应）。 */
export async function beginPasskeyLogin(username: string): Promise<PasskeyLoginOptionsResponse> {
  const response = await rawRequest(`${API_BASE}/auth/passkeys/login/options`, {
    method: 'POST',
    body: JSON.stringify({ username }),
    contentType: 'application/json',
  })
  return (await response.json()) as PasskeyLoginOptionsResponse
}

/** 通行密钥登录完成：成功 = 与密码登录同一会话 Cookie 流程。 */
export async function finishPasskeyLogin(body: {
  username: string
  challenge: string
  credential: Record<string, unknown>
}): Promise<AuthStatusView> {
  const response = await rawRequest(`${API_BASE}/auth/passkeys/login`, {
    method: 'POST',
    body: JSON.stringify({
      username: body.username,
      challenge: body.challenge,
      ...body.credential,
    }),
    contentType: 'application/json',
  })
  return (await response.json()) as AuthStatusView
}

/** TOTP 状态（是否开启 + 剩余恢复码数量）。 */
export async function getTotpStatus(signal?: AbortSignal): Promise<TotpStatusView> {
  return request<TotpStatusView>(`${API_BASE}/auth/totp`, signal)
}

/** TOTP setup：秘密 + otpauth URI 只出现一次（手动录入，无 QR 依赖）。 */
export async function setupTotp(): Promise<TotpSetupView> {
  const response = await rawRequest(`${API_BASE}/auth/totp/setup`, {
    method: 'POST',
    body: JSON.stringify({}),
    contentType: 'application/json',
  })
  return (await response.json()) as TotpSetupView
}

/** TOTP enable：验证一个验证码后开启；恢复码明文只返回这一次。 */
export async function enableTotp(code: string): Promise<{ recoveryCodes: string[] }> {
  const response = await rawRequest(`${API_BASE}/auth/totp/enable`, {
    method: 'POST',
    body: JSON.stringify({ code }),
    contentType: 'application/json',
  })
  return (await response.json()) as { recoveryCodes: string[] }
}

/** TOTP disable：服务端强制「当前密码 + 验证码/恢复码」。 */
export async function disableTotp(code: string, currentPassword: string): Promise<void> {
  await rawRequest(`${API_BASE}/auth/totp/disable`, {
    method: 'POST',
    body: JSON.stringify({ code, currentPassword }),
    contentType: 'application/json',
  })
}

/** 两步登录完成：pendingToken + 验证码（或恢复码）→ 真会话。 */
export async function verifyTotpLogin(pendingToken: string, code: string): Promise<AuthStatusView> {
  const response = await rawRequest(`${API_BASE}/auth/totp/verify`, {
    method: 'POST',
    body: JSON.stringify({ pendingToken, code }),
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
  totpCode?: string,
): Promise<AuthStatusView> {
  const response = await rawRequest(`${API_BASE}/auth/password`, {
    method: 'POST',
    body: JSON.stringify({
      currentPassword,
      newPassword,
      ...(totpCode ? { totpCode } : {}),
    }),
    contentType: 'application/json',
  })
  return (await response.json()) as AuthStatusView
}

// ---- 0067 邀请制多账户（auth 多账户面 + 管理台） ----
// 契约类型在本模块补齐（additive，与 generated/schema 的策略一致——
// schema 尚未收录这批端点；BFF 是唯一真源）。admin 列表端点返回
// SQLite 行（snake_case、epoch 秒时间戳），在此归一为稳定的 Web DTO。

/** 邀请激活预览（公开端点；只回答是/否，不含任何标签/邮箱/池用户名）。
 * notBefore/serverTime 仅在预约生效（N002）场景由服务端给出——服务器
 * 时钟是唯一时钟，客户端墙钟只用于显示。 */
export interface ActivationPreview {
  valid: boolean
  kind: 'signup' | null
  /** 池中有 ready 的 FreshRSS 账号可立即绑定。 */
  freshrssReady: boolean
  /** 邀请的预约生效时间（ISO-8601）；未预约或不在等待态为 null。 */
  notBefore: string | null
  /** 服务器当前时间（ISO-8601），用于「等待生效」的诚实倒计时显示。 */
  serverTime: string | null
}

export interface AdminUser {
  id: string
  username: string
  role: 'owner' | 'admin' | 'member'
  status: 'active' | 'paused'
  displayName: string | null
  /** 激活该账号所用的邀请方案名（N001）；无方案或方案已删除为 null。 */
  schemeName: string | null
  /** ISO-8601；服务端 epoch 秒在此归一。 */
  createdAt: string | null
}

export interface AdminInvite {
  id: string
  kind: 'signup' | 'recovery'
  label: string | null
  targetUsername: string | null
  /** 生成该邀请的方案 id（N001）；普通邀请为 null。 */
  schemeId: string | null
  /** 预约生效时间（N002，ISO-8601）；未预约为 null。 */
  notBefore: string | null
  /** 创建时预约的池账号用户名（N003，admin 元数据）；未预约为 null。 */
  heldPoolAccount: string | null
  createdAt: string | null
  expiresAt: string | null
  usedAt: string | null
  revokedAt: string | null
}

export interface AdminInviteCreated {
  /** 原始 token（inv_...）只出现这一次；服务端只存哈希。 */
  token: string
  invite: AdminInvite
}

export interface FreshRssPoolMember {
  id: string
  username: string
  bound: boolean
  boundTo: string | null
}

export interface FreshRssPoolStatus {
  ready: number
  /** 被未使用邀请预约（held）的名额（N003）。 */
  held: number
  assigned: number
  members: FreshRssPoolMember[]
}

/** 容错归一：epoch 秒数字或 ISO 字符串 → ISO 字符串；其它 → null。 */
function toIso(value: unknown): string | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return new Date(value * 1000).toISOString()
  }
  if (typeof value === 'string' && value !== '') return value
  return null
}

function pickString(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null
}

function normalizeUser(row: Record<string, unknown>): AdminUser {
  const role = row.role
  const status = row.status
  return {
    id: String(row.id ?? ''),
    username: String(row.username ?? ''),
    role: role === 'owner' || role === 'admin' ? role : 'member',
    status: status === 'paused' ? 'paused' : 'active',
    displayName: pickString(row.displayName ?? row.display_name),
    schemeName: pickString(row.schemeName ?? row.scheme_name),
    createdAt: toIso(row.createdAt ?? row.created_at),
  }
}

function normalizeInvite(row: Record<string, unknown>): AdminInvite {
  const kind = row.kind
  return {
    id: String(row.id ?? ''),
    kind: kind === 'recovery' ? 'recovery' : 'signup',
    label: pickString(row.label),
    targetUsername: pickString(row.targetUsername ?? row.target_user),
    schemeId: pickString(row.schemeId ?? row.scheme_id),
    notBefore: toIso(row.notBefore ?? row.not_before),
    heldPoolAccount: pickString(row.heldPoolAccount ?? row.held_pool_account),
    createdAt: toIso(row.createdAt ?? row.created_at),
    expiresAt: toIso(row.expiresAt ?? row.expires_at),
    usedAt: toIso(row.usedAt ?? row.used_at),
    revokedAt: toIso(row.revokedAt ?? row.revoked_at),
  }
}

/** 登录（多账户：username + password）。成功 = 浏览器拿到会话 Cookie；
 * 响应体只含 authenticated/expiresAt，身份由随后的 GET /auth/session
 * 补齐（服务端核实，绝不取自响应体之外）。 */
export async function loginAccount(username: string, password: string): Promise<LoginResponse> {
  const response = await rawRequest(`${API_BASE}/auth/login`, {
    method: 'POST',
    body: JSON.stringify({ username, password }),
    contentType: 'application/json',
  })
  return (await response.json()) as LoginResponse
}

/** 邀请激活预览（公开；不消耗 token）。notBefore/serverTime 由服务端
 * 提供（N002 等待生效状态），缺失时归一为 null。 */
export async function getActivationPreview(token: string): Promise<ActivationPreview> {
  const body = await request<Record<string, unknown>>(
    `${API_BASE}/auth/activation-preview?token=${encodeURIComponent(token)}`,
  )
  return {
    valid: body.valid === true,
    kind: body.kind === 'signup' ? 'signup' : null,
    freshrssReady: body.freshrssReady === true,
    notBefore: pickString(body.notBefore),
    serverTime: pickString(body.serverTime),
  }
}

/** 兑换 signup 邀请并自动登录（会话 Cookie 由响应设置）。
 * 400: invite_invalid / invalid_username / weak_password。 */
export async function activateWithInvite(body: {
  token: string
  username: string
  password: string
  displayName?: string | null
}): Promise<AuthStatusView> {
  const response = await rawRequest(`${API_BASE}/auth/activate`, {
    method: 'POST',
    body: JSON.stringify({
      token: body.token,
      username: body.username,
      password: body.password,
      ...(body.displayName ? { displayName: body.displayName } : {}),
    }),
    contentType: 'application/json',
  })
  return (await response.json()) as AuthStatusView
}

// ---- 管理台（role=owner|admin；403 = 后端判定的越界，UI 不自行放行） ----

/** 成员目录（不含密码哈希；owner→member 全量）。 */
export async function listAdminUsers(signal?: AbortSignal): Promise<AdminUser[]> {
  const rows = await request<unknown[]>(`${API_BASE}/admin/users`, signal)
  return rows.map((row) => normalizeUser(row as Record<string, unknown>))
}

export interface AdminInviteInput {
  label?: string | null
  ttlHours?: number
  kind?: 'signup' | 'recovery'
  targetUsername?: string | null
}

/** 创建邀请。原始 token 只在本次响应出现一次，UI 必须立刻展示/复制。 */
export async function createAdminInvite(input: AdminInviteInput): Promise<AdminInviteCreated> {
  const response = await rawRequest(`${API_BASE}/admin/invites`, {
    method: 'POST',
    body: JSON.stringify({
      kind: input.kind ?? 'signup',
      ...(input.label ? { label: input.label } : {}),
      ...(input.ttlHours !== undefined ? { ttlHours: input.ttlHours } : {}),
      ...(input.targetUsername ? { targetUsername: input.targetUsername } : {}),
    }),
    contentType: 'application/json',
  })
  const body = (await response.json()) as { token?: unknown; invite?: unknown }
  return {
    token: String(body.token ?? ''),
    invite: normalizeInvite((body.invite ?? {}) as Record<string, unknown>),
  }
}

/** 邀请列表（新→旧；含已用/已撤销——列表即台账）。 */
export async function listAdminInvites(signal?: AbortSignal): Promise<AdminInvite[]> {
  const rows = await request<unknown[]>(`${API_BASE}/admin/invites`, signal)
  return rows.map((row) => normalizeInvite(row as Record<string, unknown>))
}

/** 撤销邀请（仅未使用可撤；DELETE 幂等到服务端 404 语义）。 */
export async function revokeAdminInvite(inviteId: string): Promise<void> {
  await rawRequest(`${API_BASE}/admin/invites/${encodeURIComponent(inviteId)}`, {
    method: 'DELETE',
  })
}

// ---- 邀请方案（N001）/ 漏斗（N004）——管理台新面 -------------------------

/** 邀请方案（模板：TTL + 可选初始源 + 可选池名额预约 + 配额备注）。 */
export interface InviteScheme {
  id: string
  name: string
  ttlHours: number
  initialSourceUrls: string[]
  freshrssPoolHold: boolean
  quotaNote: string | null
  /** ISO-8601；服务端 epoch 秒在此归一。 */
  createdAt: string | null
}

function normalizeScheme(row: Record<string, unknown>): InviteScheme {
  const urls = row.initialSourceUrls ?? row.initial_source_urls
  return {
    id: String(row.id ?? ''),
    name: String(row.name ?? ''),
    ttlHours: typeof row.ttlHours === 'number' ? row.ttlHours : Number(row.ttl_hours ?? 0),
    initialSourceUrls: Array.isArray(urls) ? urls.map((url) => String(url)) : [],
    freshrssPoolHold: (row.freshrssPoolHold ?? row.freshrss_pool_hold) === true,
    quotaNote: pickString(row.quotaNote ?? row.quota_note),
    createdAt: toIso(row.createdAt ?? row.created_at),
  }
}

export interface InviteSchemeInput {
  name: string
  ttlHours?: number
  initialSourceUrls?: string[]
  freshrssPoolHold?: boolean
  quotaNote?: string | null
}

/** 保存一个命名邀请方案（模板；生成多少邀请由后续批量调用决定）。 */
export async function createInviteScheme(input: InviteSchemeInput): Promise<InviteScheme> {
  const response = await rawRequest(`${API_BASE}/admin/invite-schemes`, {
    method: 'POST',
    body: JSON.stringify({
      name: input.name,
      ...(input.ttlHours !== undefined ? { ttlHours: input.ttlHours } : {}),
      ...(input.initialSourceUrls && input.initialSourceUrls.length > 0
        ? { initialSourceUrls: input.initialSourceUrls }
        : {}),
      ...(input.freshrssPoolHold ? { freshrssPoolHold: true } : {}),
      ...(input.quotaNote ? { quotaNote: input.quotaNote } : {}),
    }),
    contentType: 'application/json',
  })
  return normalizeScheme((await response.json()) as Record<string, unknown>)
}

/** 方案列表（新→旧）。 */
export async function listInviteSchemes(signal?: AbortSignal): Promise<InviteScheme[]> {
  const rows = await request<unknown[]>(`${API_BASE}/admin/invite-schemes`, signal)
  return rows.map((row) => normalizeScheme(row as Record<string, unknown>))
}

/** 删除方案模板（已生成的邀请/账号保留 scheme_id，展示上诚实降级）。 */
export async function deleteInviteScheme(schemeId: string): Promise<void> {
  await rawRequest(`${API_BASE}/admin/invite-schemes/${encodeURIComponent(schemeId)}`, {
    method: 'DELETE',
  })
}

export interface InviteSchemeBatchCreated {
  scheme: InviteScheme
  /** 每个元素都是一次性完整链接材料（token 只出现这一次）。 */
  invites: AdminInviteCreated[]
}

/** 从方案批量生成 N 个互相独立的一次性邀请（每个都记录 scheme_id）。 */
export async function generateInvitesFromScheme(
  schemeId: string,
  input: { count: number; notBefore?: string | null; force?: boolean },
): Promise<InviteSchemeBatchCreated> {
  const response = await rawRequest(
    `${API_BASE}/admin/invite-schemes/${encodeURIComponent(schemeId)}/generate-invites`,
    {
      method: 'POST',
      body: JSON.stringify({
        count: input.count,
        ...(input.notBefore ? { notBefore: input.notBefore } : {}),
        ...(input.force ? { force: true } : {}),
      }),
      contentType: 'application/json',
    },
  )
  const body = (await response.json()) as { scheme?: unknown; invites?: unknown }
  const items = Array.isArray(body.invites) ? body.invites : []
  return {
    scheme: normalizeScheme((body.scheme ?? {}) as Record<string, unknown>),
    invites: items.map((item) => {
      const row = (item ?? {}) as Record<string, unknown>
      return {
        token: String(row.token ?? ''),
        invite: normalizeInvite((row.invite ?? {}) as Record<string, unknown>),
      }
    }),
  }
}

/** 邀请漏斗（N004）：服务端真实行聚合，绝不含邀请码。 */
export interface InviteFunnelBucket {
  schemeId: string | null
  schemeName: string | null
  generated: number
  pending: number
  activated: number
  expired: number
  revoked: number
}

export interface InviteFunnel {
  totals: {
    generated: number
    pending: number
    activated: number
    expired: number
    revoked: number
    /** 激活失败审计事件计数（服务端有该审计才非 0）。 */
    failedActivation: number
  }
  byScheme: InviteFunnelBucket[]
}

function normalizeBucket(row: Record<string, unknown>): InviteFunnelBucket {
  const num = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0)
  return {
    schemeId: pickString(row.schemeId ?? row.scheme_id),
    schemeName: pickString(row.schemeName ?? row.scheme_name),
    generated: num(row.generated),
    pending: num(row.pending),
    activated: num(row.activated),
    expired: num(row.expired),
    revoked: num(row.revoked),
  }
}

/** 漏斗聚合（可选按方案过滤）。 */
export async function getInviteFunnel(signal?: AbortSignal, schemeId?: string | null): Promise<InviteFunnel> {
  const path =
    schemeId
      ? `${API_BASE}/admin/invite-funnel?scheme_id=${encodeURIComponent(schemeId)}`
      : `${API_BASE}/admin/invite-funnel`
  const body = await request<Record<string, unknown>>(path, signal)
  const totalsRaw = (body.totals ?? {}) as Record<string, unknown>
  const byScheme = Array.isArray(body.byScheme) ? body.byScheme : []
  const num = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0)
  return {
    totals: {
      generated: num(totalsRaw.generated),
      pending: num(totalsRaw.pending),
      activated: num(totalsRaw.activated),
      expired: num(totalsRaw.expired),
      revoked: num(totalsRaw.revoked),
      failedActivation: num(totalsRaw.failedActivation),
    },
    byScheme: byScheme.map((row) => normalizeBucket((row ?? {}) as Record<string, unknown>)),
  }
}

/** 暂停成员（owner 与最后一名活跃 admin 由服务端拒绝；暂停即撤销其全部会话）。 */
export async function pauseAdminUser(userId: string): Promise<void> {
  await rawRequest(`${API_BASE}/admin/users/${encodeURIComponent(userId)}/pause`, {
    method: 'POST',
  })
}

/** 恢复成员。 */
export async function resumeAdminUser(userId: string): Promise<void> {
  await rawRequest(`${API_BASE}/admin/users/${encodeURIComponent(userId)}/resume`, {
    method: 'POST',
  })
}

/** 撤销某成员的全部会话（强制下线；不动密码）。 */
export async function revokeAdminUserSessions(userId: string): Promise<void> {
  await rawRequest(`${API_BASE}/admin/users/${encodeURIComponent(userId)}/revoke-sessions`, {
    method: 'POST',
  })
}

export interface AdminPasswordReset {
  /** 一次性 recovery 邀请 token；拼 /activate?token= 给成员自助设新密码。 */
  recoveryToken: string
  invite: AdminInvite
}

/** 重置成员密码：服务端装上无人知晓的随机密码并撤销其全部会话，
 * 返回一次性 recovery 链接材料（O150：诚实——没有邮件，什么都不假装发送）。 */
export async function resetAdminUserPassword(userId: string): Promise<AdminPasswordReset> {
  const response = await rawRequest(
    `${API_BASE}/admin/users/${encodeURIComponent(userId)}/reset-password`,
    { method: 'POST' },
  )
  const body = (await response.json()) as { recoveryToken?: unknown; invite?: unknown }
  return {
    recoveryToken: String(body.recoveryToken ?? ''),
    invite: normalizeInvite((body.invite ?? {}) as Record<string, unknown>),
  }
}

/** FreshRSS 池状态（ready/assigned 计数 + 每个成员的绑定情况）。 */
export async function getFreshRssPool(signal?: AbortSignal): Promise<FreshRssPoolStatus> {
  const body = await request<Record<string, unknown>>(`${API_BASE}/admin/pool`, signal)
  const members = Array.isArray(body.members) ? body.members : []
  return {
    ready: typeof body.ready === 'number' ? body.ready : 0,
    held: typeof body.held === 'number' ? body.held : 0,
    assigned: typeof body.assigned === 'number' ? body.assigned : 0,
    members: members.map((raw) => {
      const row = (raw ?? {}) as Record<string, unknown>
      return {
        id: String(row.id ?? ''),
        username: String(row.username ?? ''),
        bound: row.bound === true,
        boundTo: pickString(row.boundTo ?? row.bound_to),
      }
    }),
  }
}

export interface FreshRssPoolInput {
  freshrssUsername: string
  freshrssBaseUrl: string
  /** 只写不回读：落入服务端 0600 secrets，绝不返回。 */
  apiPassword: string
  publicUrl?: string | null
}

/** 登记（非创建）一个部署侧已建好的 FreshRSS 账号入池。 */
export async function registerFreshRssPool(input: FreshRssPoolInput): Promise<void> {
  await rawRequest(`${API_BASE}/admin/pool`, {
    method: 'POST',
    body: JSON.stringify({
      freshrssUsername: input.freshrssUsername,
      freshrssBaseUrl: input.freshrssBaseUrl,
      apiPassword: input.apiPassword,
      ...(input.publicUrl ? { publicUrl: input.publicUrl } : {}),
    }),
    contentType: 'application/json',
  })
}

// ---- P11 管理台系统面板（/admin/system；admin-only，服务端派生、无秘密） ----

export interface AdminSystemService {
  name: string
  configured: boolean
  /** healthy/unconfigured/unauthenticated/unavailable/configured（服务端固定词表）。 */
  status: string
  latencyMs: number | null
}

export interface AdminSystemTask {
  name: string
  enabled: boolean
  /** running/completed/cancelled/failed/off（off = 生命周期未创建该任务）。 */
  state: string
  /** 目前没有任何调度器记录 last-run —— 服务端如实恒为 null。 */
  lastRunAt: string | null
}

export interface AdminSystemCounts {
  users: number
  activeUsers: number
  invites: number
  freshrssPoolReady: number
  freshrssPoolAssigned: number
  sessions: number
  /** 以下三个是「当前请求管理员自己库」的投影计数（无跨成员内容）。 */
  feeds: number
  entriesIndexed: number
  libraryItems: number
}

export interface AdminSystemInfo {
  version: string
  commit: string
  python: string
  /** 进程运行秒数；/proc 不可用（非 Linux）时如实为 null。 */
  uptimeS: number | null
  process: {
    rssBytes: number | null
    peakRssBytes: number | null
    cpuTimeS: number | null
  }
  counts: AdminSystemCounts
  services: AdminSystemService[]
  tasks: AdminSystemTask[]
}

/** 系统诊断（只含数字/布尔/固定状态串——绝不含秘密值或 env dump）。 */
export async function getAdminSystem(signal?: AbortSignal): Promise<AdminSystemInfo> {
  const body = await request<Record<string, unknown>>(`${API_BASE}/admin/system`, signal)
  const process = (body.process ?? {}) as Record<string, unknown>
  const counts = (body.counts ?? {}) as Record<string, unknown>
  const services = Array.isArray(body.services) ? body.services : []
  const tasks = Array.isArray(body.tasks) ? body.tasks : []
  const num = (value: unknown): number | null =>
    typeof value === 'number' && Number.isFinite(value) ? value : null
  return {
    version: String(body.version ?? ''),
    commit: typeof body.commit === 'string' ? body.commit : '',
    python: typeof body.python === 'string' ? body.python : '',
    uptimeS: num(body.uptimeS),
    process: {
      rssBytes: num(process.rssBytes),
      peakRssBytes: num(process.peakRssBytes),
      cpuTimeS: num(process.cpuTimeS),
    },
    counts: {
      users: num(counts.users) ?? 0,
      activeUsers: num(counts.activeUsers) ?? 0,
      invites: num(counts.invites) ?? 0,
      freshrssPoolReady: num(counts.freshrssPoolReady) ?? 0,
      freshrssPoolAssigned: num(counts.freshrssPoolAssigned) ?? 0,
      sessions: num(counts.sessions) ?? 0,
      feeds: num(counts.feeds) ?? 0,
      entriesIndexed: num(counts.entriesIndexed) ?? 0,
      libraryItems: num(counts.libraryItems) ?? 0,
    },
    services: services.map((raw) => {
      const row = (raw ?? {}) as Record<string, unknown>
      return {
        name: String(row.name ?? ''),
        configured: row.configured === true,
        status: String(row.status ?? 'unknown'),
        latencyMs: num(row.latencyMs),
      }
    }),
    tasks: tasks.map((raw) => {
      const row = (raw ?? {}) as Record<string, unknown>
      return {
        name: String(row.name ?? ''),
        enabled: row.enabled === true,
        state: String(row.state ?? 'unknown'),
        lastRunAt: toIso(row.lastRunAt),
      }
    }),
  }
}

export interface AdminAuditEntry {
  /** epoch 秒在此归一为 ISO。 */
  at: string | null
  /** 操作者只以用户 id 出现（审计不含用户名/凭据）。 */
  actor: string
  action: string
  objectType: string | null
  objectId: string | null
  outcome: string
  detail: string | null
}

/** 审计尾部（admin/audit 原始行归一；不含正文与凭据）。 */
export async function listAdminAudit(signal?: AbortSignal, limit = 20): Promise<AdminAuditEntry[]> {
  const rows = await request<unknown[]>(`${API_BASE}/admin/audit?limit=${limit}`, signal)
  return rows.map((raw) => {
    const row = (raw ?? {}) as Record<string, unknown>
    return {
      at: toIso(row.ts),
      actor: String(row.actor ?? ''),
      action: String(row.action ?? ''),
      objectType: pickString(row.object_type),
      objectId: pickString(row.object_id),
      outcome: String(row.outcome ?? 'ok'),
      detail: pickString(row.detail),
    }
  })
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
    view: 'all' | 'unread' | 'starred'
    feedUrl: string | null
    sourceType?: string | null
    categoryId?: string | null
    cursor?: string | null
    /** N034：按投影接收时间排序（服务端执行）。 */
    sort?: 'received' | null
  },
  signal?: AbortSignal,
): Promise<EntryListResponse> {  const query = new URLSearchParams()
  // view 始终显式携带，与 query key 的 scope 保持一致（与 cursor scope
  // 构造性一致，规避 invalid_cursor 400）。P0-01：read-later 不再是
  // entries 查询的客户端过滤视图——它走服务端时间线
  // getReadLaterTimeline（本模块下方），此处类型上已收窄排除。
  query.set('view', params.view)
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
  if (params.sort != null) {
    query.set('sort', params.sort)
  }
  return request<EntryListResponse>(`${API_BASE}/entries?${query}`, signal)
}

/** N031：单篇文章的有界修订历史（纯投影查询，不触上游）。 */
export async function getEntryRevisions(
  entryRef: string,
  signal?: AbortSignal,
): Promise<EntryRevisionsResponse> {
  return request<EntryRevisionsResponse>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/revisions`,
    signal,
  )
}

/** 0022 全局搜索：q 必填；cursor / libraryCursor opaque 原样透传
 * （库腿独立 keyset，pool #10）；过滤器由页面构造。 */
export async function searchEntries(
  params: {
    q: string
    cursor?: string | null
    libraryCursor?: string | null
    limit?: number
    feedUrl?: string | null
    categoryId?: string | null
    state?: 'unread' | null
    favorite?: boolean | null
    from?: string | null
    to?: string | null
    /** F078：同义词扩展（服务端默认开；显式 false 关闭）。 */
    expandSynonyms?: boolean
  },
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const query = new URLSearchParams()
  query.set('q', params.q)
  if (params.expandSynonyms === false) {
    query.set('expandSynonyms', 'false')
  }
  if (params.cursor != null) {
    // cursor 是 opaque string：原样传递，绝不 decode / parse / 修改。
    query.set('cursor', params.cursor)
  }
  if (params.libraryCursor != null) {
    query.set('libraryCursor', params.libraryCursor)
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

/** 0013 Gate 3 / N012：取消订阅（破坏性操作，确认流程由 UI 负责）。
 *  keepArtifacts：true=保留批注/工作区引用（204）；false=显式清理（200）；
 *  缺省=legacy 行为（仅备注级联）。 */
export async function unsubscribeFeed(
  subscriptionRef: string,
  keepArtifacts?: boolean,
): Promise<void> {
  // 契约扫描按「形状」提取路径：路径段单独成模板（单一占位符），
  // 查询串拼接在其后，保持 /subscriptions/{} 形状可校验。
  const path = `${API_BASE}/subscriptions/${encodeURIComponent(subscriptionRef)}`
  const url =
    keepArtifacts === undefined ? path : `${path}?keep_artifacts=${keepArtifacts}`
  await rawRequest(url, {
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
 * 浏览器不接触 FreshRSS 凭据）。成功即触发下载；失败抛 ApiError。
 * F003：selection 非空时按所选导出（BFF 重建 OPML，保留分类结构）。 */
export async function exportOpml(selection?: {
  subscriptionRefs?: string[]
  categoryIds?: string[]
}): Promise<void> {
  const params = new URLSearchParams()
  for (const ref of selection?.subscriptionRefs ?? []) params.append('subscription_refs', ref)
  for (const id of selection?.categoryIds ?? []) params.append('category_ids', id)
  const query = params.toString()
  const suffix = query !== '' ? `?${query}` : ''
  const response = await rawRequest(`${API_BASE}/opml/export` + suffix)
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
 * 并重新读取 FreshRSS，预览仅供参考）。成功后由调用方 invalidate。
 * F002：selectedIndexes 非空时仅导入勾选的逐项预览 index。 */
export async function importOpml(
  file: File,
  selectedIndexes?: number[],
): Promise<OpmlImportResult> {
  const qs =
    selectedIndexes !== undefined && selectedIndexes.length > 0
      ? `?selected_indexes=${selectedIndexes.join(',')}`
      : ''
  const response = await rawRequest(`${API_BASE}/opml/import` + qs, {
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

/** P09 委托入口：本账户 FreshRSS 原生界面坐标（恰好 {origin, username}，
 * 无凭据字段）。绑定待定 → 409 freshrss_native_url_unavailable（诚实
 * 待定态，UI 不渲染假链接）。 */
export async function getFreshRssNativeUrl(signal?: AbortSignal): Promise<FreshRssNativeUrl> {
  return request<FreshRssNativeUrl>(`${API_BASE}/freshrss/native-url`, signal)
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
 * 浏览器不直连 RSSHub）。在共享预览形状上附加服务端派生的 routeKey。 */
export async function previewRssHub(
  routeId: string,
  params: Record<string, string>,
): Promise<RssHubPreviewMetadata> {
  const response = await rawRequest(`${API_BASE}/rsshub/preview`, {
    method: 'POST',
    body: JSON.stringify({ routeId, params }),
    contentType: 'application/json',
  })
  return (await response.json()) as RssHubPreviewMetadata
}

// ---- N021 路由收藏与最近使用（服务端持久化，跨设备） ----

/** N021：收藏列表（敏感参数值只以 '***' 哨兵出现）。 */
export async function getRssHubFavorites(signal?: AbortSignal): Promise<RssHubFavoriteItem[]> {
  return request<RssHubFavoriteItem[]>(`${API_BASE}/rsshub/routes/favorites`, signal)
}

/** N021：收藏 / 改标签（服务端按 route_key upsert）。 */
export async function putRssHubFavorite(input: {
  routeId: string
  params?: Record<string, string>
  label?: string
}): Promise<RssHubFavoriteItem> {
  const response = await rawRequest(`${API_BASE}/rsshub/routes/favorites`, {
    method: 'PUT',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as RssHubFavoriteItem
}

/** N021：取消收藏（routeKey 来自收藏列表，客户端不自行拼装）。 */
export async function deleteRssHubFavorite(routeKey: string): Promise<void> {
  await rawRequest(
    `${API_BASE}/rsshub/routes/favorites/${encodeURIComponent(routeKey)}`,
    { method: 'DELETE' },
  )
}

/** N021：最近使用（仅成功过的 preview/subscribe 会出现在这里）。 */
export async function getRssHubRecent(signal?: AbortSignal): Promise<RssHubRecentItem[]> {
  return request<RssHubRecentItem[]>(`${API_BASE}/rsshub/routes/recent`, signal)
}

/** N025：路由健康时间线（单 route_key，最新在前，服务端有界）。 */
export async function getRssHubRouteHistory(
  routeKey: string,
  signal?: AbortSignal,
): Promise<RssHubRouteRuns> {
  const params = new URLSearchParams({ routeKey })
  return request<RssHubRouteRuns>(`${API_BASE}/rsshub/routes/history?${params}`, signal)
}

/** N027：强制重取该路由（绕过预览缓存；429 时抛带 retryAfterSeconds 的 ApiError）。 */
export async function refreshRssHubRoute(routeKey: string): Promise<RssHubRefreshResult> {
  const response = await rawRequest(`${API_BASE}/rsshub/refresh`, {
    method: 'POST',
    body: JSON.stringify({ routeKey }),
    contentType: 'application/json',
  })
  return (await response.json()) as RssHubRefreshResult
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
  /** gemini 时 BFF 强制使用官方接口地址（baseUrl 被忽略）。 */
  provider?: AiProfileProvider
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

// Q-P2-25：getAiPurposes 已删除（零消费者死代码）——用途 UI 从
// settings 快照读真值，写路径走 updateAiPurposes（GET/PUT 真值源
// 不对称曾留下双状态源隐患）。

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
  opts?: { overwriteRevisions?: boolean; signal?: AbortSignal },
): Promise<TranslationSegmentsView> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/segments/generate`,
    {
      method: 'POST',
      body: JSON.stringify({
        blocks,
        ...(opts?.overwriteRevisions ? { overwriteRevisions: true } : {}),
      }),
      signal: opts?.signal,
      contentType: 'application/json',
    },
  )
  return (await response.json()) as TranslationSegmentsView
}

/** F062：保存一段译文的手工修订（锚定当前源段 hash）。 */
export async function putTranslationSegmentRevision(
  entryRef: string,
  blockIndex: number,
  text: string,
): Promise<{ index: number; userRevision: string; revisedAt: string; revisionStale: boolean }> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/segments/${blockIndex}/revision`,
    { method: 'PUT', body: JSON.stringify({ text }), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { index: number; userRevision: string; revisedAt: string; revisionStale: boolean }
}

/** F062：撤销一段译文的手工修订。 */
export async function deleteTranslationSegmentRevision(
  entryRef: string,
  blockIndex: number,
): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/segments/${blockIndex}/revision`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

/** N086：把一块标记为「不翻译」（持久；该块不再参与生成）。 */
export async function markNoTranslateBlock(
  entryRef: string,
  blockIndex: number,
): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/segments/${blockIndex}/no-translate`,
    { method: 'PUT' },
  )
  if (!response.ok) throw await toApiError(response)
}

/** N086：撤销一块的「不翻译」标记（块恢复可翻译）。 */
export async function unmarkNoTranslateBlock(
  entryRef: string,
  blockIndex: number,
): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation/segments/${blockIndex}/no-translate`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

/** N082：当前译文的逐块数字校验（纯只读，零 provider 调用）。
 * 基于可见数字差异，非语义判断。 */
export async function getTranslationVerification(
  entryRef: string,
  language?: string,
): Promise<TranslationVerificationView> {
  const path = `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translation-verification`
  const url =
    language === undefined ? path : `${path}?language=${encodeURIComponent(language)}`
  const response = await rawRequest(url, { method: 'GET' })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as TranslationVerificationView
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

export async function removeWorkspaceItem(
  workspaceId: string,
  itemRef: string,
  options: { force?: boolean } = {},
): Promise<void> {
  // N102：固定条目需显式 ?force=1（BFF 409 workspace_item_pinned 保护）。
  const forceQuery = options.force === true ? '?force=1' : ''
  await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/items/${encodeURIComponent(itemRef)}` +
      forceQuery,
    { method: 'DELETE' },
  )
}

// ---- N101/N102/N105：工作区分组 / 固定 / 会话快照 ----

/** N101：分组视图（固定区 + 未分组隐式前置组 + 命名组序列）。 */
export async function getWorkspaceGroups(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<WorkspaceGroupsResponse> {
  return request<WorkspaceGroupsResponse>(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/groups`,
    signal,
  )
}

/** N101：设置命名组呈现顺序（只重排既有组；PUT 幂等）。 */
export async function putWorkspaceGroupOrder(
  workspaceId: string,
  order: string[],
): Promise<WorkspaceGroupsResponse> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/groups`,
    {
      method: 'PUT',
      body: JSON.stringify({ order }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as WorkspaceGroupsResponse
}

/** N101：移动条目到分组（groupName=null = 移回未分组）。 */
export async function moveWorkspaceItemGroup(
  workspaceId: string,
  itemRef: string,
  groupName: string | null,
): Promise<WorkspaceItem> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/items/${encodeURIComponent(itemRef)}/group`,
    {
      method: 'PATCH',
      body: JSON.stringify({ groupName }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as WorkspaceItem
}

/** N102：设置固定标记（set 语义非 toggle）。 */
export async function setWorkspaceItemPinned(
  workspaceId: string,
  itemRef: string,
  pinned: boolean,
): Promise<WorkspaceItem> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/items/${encodeURIComponent(itemRef)}/pin`,
    {
      method: 'PUT',
      body: JSON.stringify({ pinned }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as WorkspaceItem
}

/** N105：捕获当前标签页/分组状态为命名快照。 */
export async function captureWorkspaceSnapshot(
  workspaceId: string,
  name: string,
): Promise<WorkspaceSnapshot> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/snapshots`,
    {
      method: 'POST',
      body: JSON.stringify({ name }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as WorkspaceSnapshot
}

/** N105：快照列表（新→旧）。 */
export async function listWorkspaceSnapshots(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<WorkspaceSnapshotList> {
  return request<WorkspaceSnapshotList>(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/snapshots`,
    signal,
  )
}

/** N105：删除一个快照（Web 侧删除前二次确认）。 */
export async function deleteWorkspaceSnapshot(
  workspaceId: string,
  snapshotId: string,
): Promise<void> {
  await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/snapshots/${encodeURIComponent(snapshotId)}`,
    { method: 'DELETE' },
  )
}

/** N105：恢复快照（reorder=只重排既有成员 / replace=移除快照外成员；
 * replace 遇固定条目 409 workspace_item_pinned，需 force=true）。
 * 返回 diff 摘要 {restored, missing, kept, removed, revision}。 */
export async function restoreWorkspaceSnapshot(
  workspaceId: string,
  snapshotId: string,
  mode: 'reorder' | 'replace',
  force = false,
): Promise<WorkspaceSnapshotRestoreResult> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/snapshots/${encodeURIComponent(snapshotId)}/restore`,
    {
      method: 'POST',
      body: JSON.stringify({ mode, force }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as WorkspaceSnapshotRestoreResult
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

/** 重排序：按新顺序传完整 itemRefs（≤500，BFF 校验）。
 * P15：`expectedRevision` 可选（If-Match 式乐观并发）；工作区已在其它
 * 设备被改动时 BFF 返回 409 workspace_revision_conflict（ApiError.status
 * === 409），调用方应重取后重试，绝不静默覆盖。 */
export async function reorderWorkspaceItems(
  workspaceId: string,
  itemRefs: string[],
  expectedRevision?: number,
): Promise<WorkspaceItemsResponse> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/items`,
    {
      method: 'PATCH',
      body: JSON.stringify(
        expectedRevision === undefined ? { itemRefs } : { itemRefs, expectedRevision },
      ),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as WorkspaceItemsResponse
}

/** P15：读取「上次看到哪」续读指针（pointer=null = 无指针；含未知工作区）。 */
export async function getWorkspaceResume(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<WorkspaceResumeResponse> {
  return request<WorkspaceResumeResponse>(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/resume`,
    signal,
  )
}

/** P15：保存续读指针（条目打开时调用；PUT 幂等 upsert）。
 * 只指向工作区成员——非成员/未知工作区 → 404（诚实失败，不静默）。 */
export async function putWorkspaceResume(
  workspaceId: string,
  itemRef: string,
): Promise<WorkspaceResumeResponse> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/resume`,
    {
      method: 'PUT',
      body: JSON.stringify({ itemRef }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as WorkspaceResumeResponse
}

/** P0-10：重命名工作区（PATCH；保留工作区 read-later 由 BFF 拒绝）。 */
export async function renameWorkspace(
  workspaceId: string,
  name: string,
  description?: string,
): Promise<Workspace> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}`,
    {
      method: 'PATCH',
      // F25：description 缺省 = 不修改说明（旧调用方零改动兼容）
      body: JSON.stringify(description === undefined ? { name } : { name, description }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as Workspace
}

/** F27：导出工作区研究包（Markdown 文本；含条目/笔记/manifest）。 */
export async function exportResearchPackMd(workspaceId: string): Promise<string> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/research-pack`,
    { method: 'POST', body: JSON.stringify({}) },
  )
  return await response.text()
}

/** P0-10：删除工作区及其成员关系（DELETE 204；保留工作区由 BFF 拒绝，
 * 不存在返回 404）。成员内容本身不受影响（只解除归属）。 */
export async function deleteWorkspace(workspaceId: string): Promise<void> {
  await rawRequest(`${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}`, {
    method: 'DELETE',
  })
}

// ---- phase2 Gate 3：网页剪藏（library/clips） ----
// P0-03 后服务端可信管线：/clips/fetch 返回服务端提取 + 清洗的文章
// （ClipFetchArticleResult）；/clips 只接受 {url, finalUrl}——客户端
// 派生的 title/html 一律不再提交（服务端按 finalUrl 重取重导出）。
// ref 形如 `library:<uuid>`，路径参数取 uuid 部分（本模块负责剥离，
// UI 只透传 ref，与书签同一模式）。

/** `library:<uuid>` → `<uuid>`（容错裸 uuid，原样返回）。 */
function toClipId(clipRef: string): string {
  return clipRef.startsWith('library:') ? clipRef.slice('library:'.length) : clipRef
}

/** 服务端抓取并提取目标页文章（SSRF 钉住拨号 + 服务端 allow-list 清洗；
 * contentHtml 在渲染前仍必须过 DOMPurify——渲染终界不变）。
 * 400 clip_fetch_forbidden / 502 clip_fetch_failed 由 UI 原样展示
 * message。无副作用 mutation 语义：不接 AbortSignal，发出后允许完成。 */
export async function fetchClipArticle(url: string): Promise<ClipFetchArticleResult> {
  const response = await rawRequest(`${API_BASE}/library/clips/fetch`, {
    method: 'POST',
    body: JSON.stringify({ url }),
    contentType: 'application/json',
  })
  return (await response.json()) as ClipFetchArticleResult
}

/** 保存确认的剪藏：url 必填；finalUrl 来自 /fetch 预览（存在时服务端
 * 抓 finalUrl 重取重导出）。任何客户端 title/html 字段都不再提交。 */
export interface ClipInput {
  url: string
  finalUrl?: string | null
}

/** 保存剪藏（服务端重新提取+清洗后落库；重复 url 幂等返回同一 ref）。
 * 不接 AbortSignal，与其它 mutation 一致。 */
export async function createClip(body: ClipInput): Promise<ClipDetail> {
  const response = await rawRequest(`${API_BASE}/library/clips`, {
    method: 'POST',
    body: JSON.stringify({
      url: body.url,
      finalUrl: body.finalUrl ?? null,
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
/** P0-06i：创建响应含诚实的 FreshRSS 自动订阅状态（subscribeFailed/
 * atomPath 未设置时不出现在线路上）。 */
export type MailBridgeListCreated = G6Schemas['MailBridgeListCreatedV2']
export type MailBridgeListResponse = G6Schemas['MailBridgeListResponse']
export type MailIngestResult = G6Schemas['MailIngestResult']
export type DigestSettings = G6Schemas['DigestSettings']
export type DigestSettingsUpdate = G6Schemas['DigestSettingsUpdate']
export type GptDigestSettings = G6Schemas['GptDigestSettings']
export type GptDigestSettingsUpdate = G6Schemas['GptDigestSettingsUpdate']
export type GptDigestIssue = G6Schemas['GptDigestIssue']
export type GptDigestIssueList = G6Schemas['GptDigestIssueList']
export type GptDigestFeedInfo = G6Schemas['GptDigestFeedInfo']
export type GptDigestPreview = G6Schemas['GptDigestPreview']
export type GptDigestPreviewItem = G6Schemas['GptDigestPreviewItem']
export type GptDigestConfig = G6Schemas['GptDigestConfig']
export type GptDigestConfigList = G6Schemas['GptDigestConfigList']
export type GptDigestConfigUpdate = G6Schemas['GptDigestConfigUpdate']
export type GptDigestCreate = G6Schemas['GptDigestCreate']
export type GptDigestIssueRevise = G6Schemas['GptDigestIssueRevise']
export type GptDigestSentence = G6Schemas['GptDigestSentence']
export type GptDigestSentenceOp = G6Schemas['GptDigestSentenceOp']
export type GptDigestColumn = G6Schemas['GptDigestColumn']
export type GptDigestLeftoverItem = G6Schemas['GptDigestLeftoverItem']
export type GptDigestTrimPreview = G6Schemas['GptDigestTrimPreview']
export type StorageUsage = G6Schemas['StorageUsage']
export type SubscriptionVolumeResponse = G6Schemas['SubscriptionVolumeResponse']
export type SubscriptionVolumeItem = G6Schemas['SubscriptionVolumeItem']
export type SourceOverrideResult = G6Schemas['SourceOverrideResult']
export type TitleTranslationView = G6Schemas['TitleTranslationView']
export type SettingsHistoryList = G6Schemas['SettingsHistoryList']
export type SettingsHistoryEntry = G6Schemas['SettingsHistoryEntry']
export type SettingsRevertResult = G6Schemas['SettingsRevertResult']
export type GlossaryTerm = G6Schemas['GlossaryTerm']
export type GlossaryTermList = G6Schemas['GlossaryTermList']
export type ObsidianStatus = G6Schemas['ObsidianStatus']
export type ObsidianSettings = G6Schemas['ObsidianSettings']
export type ObsidianRescanResult = G6Schemas['ObsidianRescanResult']
export type NoteView = G6Schemas['NoteView']
export type NoteListResponse = G6Schemas['NoteListResponse']
export type ObsidianDeviceProfile = G6Schemas['ObsidianDeviceProfile']
export type ObsidianDeviceProfileList = G6Schemas['ObsidianDeviceProfileList']
export type ObsidianDeviceProfilePayload = G6Schemas['ObsidianDeviceProfilePayload']
export type ObsidianExportTemplateView = G6Schemas['ObsidianExportTemplateView']
export type ObsidianTemplatePreviewResult = G6Schemas['ObsidianTemplatePreviewResult']
export type ObsidianExportHandoffResult = G6Schemas['ObsidianExportHandoffResult']
export type ObsidianScanFileList = G6Schemas['ObsidianScanFileList']
export type ObsidianScanFiles = G6Schemas['ObsidianScanFiles']
export type ObsidianBlockRef = G6Schemas['ObsidianBlockRef']
export type ObsidianBlockRefsResponse = G6Schemas['ObsidianBlockRefsResponse']
export type ObsidianExportIssue = G6Schemas['ObsidianExportIssue']
export type ObsidianExportValidateResult = G6Schemas['ObsidianExportValidateResult']
export type ObsidianHandoffLogEntry = G6Schemas['ObsidianHandoffLogEntry']
export type ObsidianHandoffLogList = G6Schemas['ObsidianHandoffLogList']
export type ObsidianHandoffLogClearResult = G6Schemas['ObsidianHandoffLogClearResult']
export type AnnotationExportMarkResult = G6Schemas['AnnotationExportMarkResult']
export type AnnotationExportDelta = G6Schemas['AnnotationExportDelta']
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

/** F042：分页采样配置（none=单次抓取；page=?page=N；cursor=?cursor=）。 */
export interface ApiSourcePaginationInput {
  mode: 'none' | 'page' | 'cursor'
  page_param?: string
  first_page?: number
  cursor_path?: string
  max_pages?: number
  max_items?: number
}

export interface ApiSourceCreateInput {
  name: string
  endpoint: string
  itemsExpr: string
  fieldMap: ApiSourceFieldMapInput
  pagination?: ApiSourcePaginationInput
  subscribe?: boolean
  maxRunsPerHour?: number
}

export interface ApiSourcePreviewInput {
  endpoint: string
  itemsExpr: string
  fieldMap: ApiSourceFieldMapInput
  pagination?: ApiSourcePaginationInput
  dryRunPagination?: boolean
}

export interface ApiSourceUpdateInput {
  name?: string | null
  endpoint?: string | null
  itemsExpr?: string | null
  fieldMap?: ApiSourceFieldMapInput | null
  pagination?: ApiSourcePaginationInput | null
  enabled?: boolean | null
  maxRunsPerHour?: number | null
}

/** F043：重新确认结构基线（重新快照并解除漂移告警）。 */
export async function confirmApiSourceSchema(uuid: string): Promise<{ confirmed: boolean; sampledItems: number }> {
  const response = await rawRequest(
    `${API_BASE}/api-sources/${encodeURIComponent(uuid)}/confirm-schema`,
    { method: 'POST' },
  )
  return (await response.json()) as { confirmed: boolean; sampledItems: number }
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

// ---- N128 用样例预览 / N129 预算 / N130 轮换；N011/N016/N017 来源生命周期 ----

export interface ApiSourceSamplePreviewInput {
  samplePayload: unknown
  itemsExpr: string
  fieldMap: ApiSourceFieldMapInput
}

/** N128 离线样例预览：对粘贴样例跑同一条映射 + Atom 预览管线。
 * 零网络、零存储、无任何请求头；sampleMode=true 诚实标注。 */
export async function previewApiSourceSample(
  input: ApiSourceSamplePreviewInput,
): Promise<ApiSourcePreviewResult> {
  const response = await rawRequest(`${API_BASE}/api-sources/preview-sample`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as ApiSourcePreviewResult
}

export interface ApiSourceCredentialResult {
  ok: boolean
  statusClass: string
  latencyMs: number
  note?: string | null
}

/** N130 轮换预演（API 来源）：结构校验 + 只读端点探测（5s 上限）。
 * 响应脱敏：只有 {ok, statusClass, latencyMs}，凭据与请求头绝不回显。 */
export async function testApiSourceCredential(
  uuid: string,
  newCredential: string,
): Promise<ApiSourceCredentialResult> {
  const response = await rawRequest(
    `${API_BASE}/api-sources/${encodeURIComponent(uuid)}/credentials/test`,
    {
      method: 'POST',
      body: JSON.stringify({ newCredential }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as ApiSourceCredentialResult
}

/** N130 测试并轮换（API 来源）：预演失败 → 422 credential_test_failed
 * 且当前凭据原样；成功 → 原子换哈希 + 旧凭据进入 10 分钟宽限窗。 */
export async function rotateApiSourceCredential(
  uuid: string,
  newCredential: string,
): Promise<ApiSourceCredentialResult> {
  const response = await rawRequest(
    `${API_BASE}/api-sources/${encodeURIComponent(uuid)}/credentials/rotate`,
    {
      method: 'POST',
      body: JSON.stringify({ newCredential }),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as ApiSourceCredentialResult
}

export interface BundleSourceEntry {
  feed_url: string
  title?: string
  category?: string | null
  type?: string
  notes?: string | null
}

export interface BundleDocument {
  version: number
  generatedAt?: string | null
  sources: BundleSourceEntry[]
  missing?: string[]
}

export interface BundleImportItem {
  feedUrl: string
  title: string
  status: 'new' | 'exists' | 'needs_credentials' | 'invalid' | 'failed'
  type: string
  categoryAction: 'none' | 'reuse' | 'create'
  note?: string | null
}

export interface BundleImportResult {
  items: BundleImportItem[]
  counts: Record<string, number>
  applied: boolean
}

/** N011 组合包导出：凭据无关的 JSON（Lumi 生成源脱敏为 urn）。 */
export async function exportSourceBundle(feedUrls: string[]): Promise<BundleDocument> {
  const response = await rawRequest(`${API_BASE}/sources/bundle/export`, {
    method: 'POST',
    body: JSON.stringify({ feedUrls }),
    contentType: 'application/json',
  })
  return (await response.json()) as BundleDocument
}

/** N011 组合包导入：默认试运行预览；apply=true 才提交。 */
export async function importSourceBundle(
  bundle: BundleDocument,
  apply: boolean,
): Promise<BundleImportResult> {
  const response = await rawRequest(
    `${API_BASE}/sources/bundle/import?apply=${apply ? 'true' : 'false'}`,
    {
      method: 'POST',
      body: JSON.stringify(bundle),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as BundleImportResult
}

export interface StagedSourceSampleEntry {
  title: string
  link?: string | null
  published?: string | null
  summary?: string | null
}

export interface StagedSource {
  id: string
  url: string
  title: string
  addedAt: string
  note?: string | null
  sourceType: string
  origin: 'staging' | 'bundle_draft'
  enabled: boolean
  subscribed: boolean
  sample: StagedSourceSampleEntry[]
}

/** N016 暂存一个待评估来源（有界预览抓取 + 快照；不订阅、不计未读）。 */
export async function stageSource(url: string, note?: string): Promise<StagedSource> {
  const response = await rawRequest(`${API_BASE}/sources/staging`, {
    method: 'POST',
    body: JSON.stringify({ url, note: note || null }),
    contentType: 'application/json',
  })
  return (await response.json()) as StagedSource
}

export async function listStagedSources(signal?: AbortSignal): Promise<{ items: StagedSource[] }> {
  return request<{ items: StagedSource[] }>(`${API_BASE}/sources/staging`, signal)
}

/** N016 幂等订阅：已存在订阅 → exists；无论结果暂存行都会移除。 */
export async function subscribeStagedSource(
  id: string,
): Promise<{ status: 'subscribed' | 'exists'; feedUrl: string }> {
  const response = await rawRequest(
    `${API_BASE}/sources/staging/${encodeURIComponent(id)}/subscribe`,
    { method: 'POST' },
  )
  return (await response.json()) as { status: 'subscribed' | 'exists'; feedUrl: string }
}

export async function discardStagedSource(id: string): Promise<void> {
  await rawRequest(`${API_BASE}/sources/staging/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

export interface CleanupSuggestion {
  feedUrl: string
  title: string
  lastReadAt: string | null
  weeklyYield: number
  suggestion: 'demote' | 'mute'
  basis?: string | null
}

export interface CleanupSuggestionsResponse {
  items: CleanupSuggestion[]
  generatedAt: string
  basis: string
}

/** N017 清理建议（只读）：长期未读 × 仍高产的自有数据投影。 */
export async function getCleanupSuggestions(
  signal?: AbortSignal,
): Promise<CleanupSuggestionsResponse> {
  return request<CleanupSuggestionsResponse>(`${API_BASE}/sources/cleanup-suggestions`, signal)
}

export interface CleanupApplyItem {
  feedUrl: string
  ok: boolean
  error?: string | null
}

export interface CleanupApplyResult {
  items: CleanupApplyItem[]
  applied: number
}

/** N017 仅应用用户显式勾选的动作（mute / demote_category）；绝不自动退订。 */
export async function applyCleanupSuggestions(input: {
  feedUrls: string[]
  action: 'mute' | 'demote_category'
  targetCategoryLabel?: string
}): Promise<CleanupApplyResult> {
  const response = await rawRequest(`${API_BASE}/sources/cleanup-suggestions/apply`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as CleanupApplyResult
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

/** P0-06b：send-now 的条目引用 = bridge 条目的 messageId（服务端只按
 * messageId 解析已存条目，其它键被忽略——客户端文本永不被信任）。 */
export interface DigestEntryRefInput {
  messageId: string
}

/** 立即发送摘要（服务端取材：显式 messageId 解析或按设置来源取最新；
 * 422 no_digest_items / 503 smtp_not_configured / 502 smtp_send_failed
 * 的 error.message 由 UI 原样透出）。 */
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

// ---- M4/F01：GPT 日报（多配置；旧单配置端点等价配置 1） ----

/** 配置列表。 */
export async function listGptDigestConfigs(signal?: AbortSignal): Promise<GptDigestConfigList> {
  return request<GptDigestConfigList>(`${API_BASE}/gpt-digest/configs`, signal)
}

/** 新建配置（默认 paused；enabled 由编辑打开）。 */
export async function createGptDigestConfig(payload: GptDigestCreate): Promise<GptDigestConfig> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/configs`, {
    method: 'POST',
    body: JSON.stringify(payload),
    contentType: 'application/json',
  })
  return (await response.json()) as GptDigestConfig
}

/** 编辑/暂停配置（enabled=false = 暂停；非法值由服务端回退现值）。 */
export async function updateGptDigestConfig(
  configId: number,
  patch: GptDigestConfigUpdate,
): Promise<GptDigestConfig> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/configs/${configId}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
    contentType: 'application/json',
  })
  return (await response.json()) as GptDigestConfig
}

/** 删除配置（级联删除其期刊；默认配置服务端拒绝）。 */
export async function deleteGptDigestConfig(configId: number): Promise<void> {
  await rawRequest(`${API_BASE}/gpt-digest/configs/${configId}`, { method: 'DELETE' })
}

/** 指定配置的订阅路径（含 token）。 */
export async function getConfigFeed(configId: number): Promise<GptDigestFeedInfo> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/configs/${configId}/feed`, {
    method: 'GET',
  })
  return (await response.json()) as GptDigestFeedInfo
}

/** 指定配置的选材预览（F06）。 */
export async function previewConfigDigest(
  configId: number,
  putBack?: string[],
): Promise<GptDigestPreview> {
  // F101：putBack 为本次显式放回的材料身份（url:/title: 前缀键，可重复）。
  // `?` 内联进字面量：契约测试按路径形状比对，尾随 ${qs} 会被折叠成
  // 多余参数段（/preview{} → stale-BFF 404 类误报）。
  const query =
    putBack !== undefined && putBack.length > 0
      ? putBack.map((key) => `putBack=${encodeURIComponent(key)}`).join('&')
      : ''
  const path = query
    ? `${API_BASE}/gpt-digest/configs/${configId}/preview?${query}`
    : `${API_BASE}/gpt-digest/configs/${configId}/preview`
  const response = await rawRequest(path, {
    method: 'GET',
  })
  return (await response.json()) as GptDigestPreview
}

/** 指定配置的立即生成/修订（putBack 可选：本次显式放回的材料身份）。 */
export async function generateConfigDigest(
  configId: number,
  putBack?: string[],
): Promise<{ issue: GptDigestIssue; promptVersion: string }> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/configs/${configId}/generate`, {
    method: 'POST',
    body:
      putBack !== undefined && putBack.length > 0
        ? JSON.stringify({ putBack })
        : undefined,
    contentType: putBack !== undefined && putBack.length > 0 ? 'application/json' : undefined,
  })
  return (await response.json()) as { issue: GptDigestIssue; promptVersion: string }
}

/** 指定配置的最近期刊。 */
export async function listConfigIssues(
  configId: number,
  signal?: AbortSignal,
  limit = 14,
): Promise<GptDigestIssueList> {
  return request<GptDigestIssueList>(
    `${API_BASE}/gpt-digest/configs/${configId}/issues?limit=${limit}`,
    signal,
  )
}

/** F08：人工修订某期（title/sections；sourceIds 只能引用既有引用集）。 */
export async function reviseGptDigestIssue(
  configId: number,
  issueKey: string,
  payload: GptDigestIssueRevise,
): Promise<{ issue: GptDigestIssue }> {
  const response = await rawRequest(
    `${API_BASE}/gpt-digest/configs/${configId}/issues/${encodeURIComponent(issueKey)}`,
    { method: 'PUT', body: JSON.stringify(payload), contentType: 'application/json' },
  )
  return (await response.json()) as { issue: GptDigestIssue }
}

/** N172：仅重跑润色阶段（选材/总结成果保留）。 */
export async function retryPolishGptDigestIssue(
  configId: number,
  issueKey: string,
): Promise<{ issue: GptDigestIssue }> {
  const response = await rawRequest(
    `${API_BASE}/gpt-digest/configs/${configId}/issues/${encodeURIComponent(issueKey)}/retry-polish`,
    { method: 'POST' },
  )
  return (await response.json()) as { issue: GptDigestIssue }
}

/** N175：阅读时长裁剪预览（before/after + 将移入素材篮的条目；零写入）。 */
export async function getDigestTrimPreview(
  configId: number,
  issueKey: string,
  signal?: AbortSignal,
): Promise<GptDigestTrimPreview> {
  return request<GptDigestTrimPreview>(
    `${API_BASE}/gpt-digest/configs/${configId}/issues/${encodeURIComponent(issueKey)}/trim-preview`,
    signal,
  )
}

/** F29 反向入口：引用某一 RSS 条目的书签/笔记（新→旧；无效引用为空列表）。 */
export async function listNotesByEntry(
  entryRef: string,
  signal?: AbortSignal,
): Promise<BookmarkListResponse> {
  return request<BookmarkListResponse>(
    `${API_BASE}/library/notes-by-entry/${encodeURIComponent(entryRef)}`,
    signal,
  )
}

/** F39：导出 Lumi 自有数据（工作区/标签/书签/日报；版本化 JSON）。 */
export async function exportLumiData(): Promise<void> {
  const response = await rawRequest(`${API_BASE}/export/lumi-data`, { method: 'GET' })
  const blob = new Blob([await response.text()], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `lumirss-data-${new Date().toISOString().slice(0, 10)}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

/** F33：设置变更历史（新→旧）。 */
export async function getSettingsHistory(
  signal?: AbortSignal,
  limit = 10,
): Promise<SettingsHistoryList> {
  return request<SettingsHistoryList>(`${API_BASE}/settings/history?limit=${limit}`, signal)
}

/** F33：回退一次历史变更（跳过之后被改过的键）。 */
export async function revertSettingsHistory(historyId: number): Promise<SettingsRevertResult> {
  const response = await rawRequest(
    `${API_BASE}/settings/history/${historyId}/revert`,
    { method: 'POST' },
  )
  return (await response.json()) as SettingsRevertResult
}

/** F28：期内事实对照（按需，不落库）。 */
export async function compareFactsGptDigestIssue(
  configId: number,
  issueKey: string,
): Promise<{ title: string; bodyHtml: string; promptVersion: string }> {
  const response = await rawRequest(
    `${API_BASE}/gpt-digest/configs/${configId}/issues/${encodeURIComponent(issueKey)}/compare-facts`,
    { method: 'POST' },
  )
  return (await response.json()) as { title: string; bodyHtml: string; promptVersion: string }
}

/** F07：相邻日报变化对照（独立条目 key = {key}-d）。 */
export async function compareGptDigestIssue(
  configId: number,
  issueKey: string,
): Promise<{ issue: GptDigestIssue }> {
  const response = await rawRequest(
    `${API_BASE}/gpt-digest/configs/${configId}/issues/${encodeURIComponent(issueKey)}/compare`,
    { method: 'POST' },
  )
  return (await response.json()) as { issue: GptDigestIssue }
}

/** F03：生成周报（聚合该配置最近 7 天日刊）。 */
export async function generateWeeklyDigest(
  configId: number,
): Promise<{ issue: GptDigestIssue }> {
  const response = await rawRequest(
    `${API_BASE}/gpt-digest/configs/${configId}/weekly`,
    { method: 'POST' },
  )
  return (await response.json()) as { issue: GptDigestIssue }
}

/** F05：生成某期的初学者解释版（独立条目 key = {key}-x）。 */
export async function explainGptDigestIssue(
  configId: number,
  issueKey: string,
): Promise<{ issue: GptDigestIssue }> {
  const response = await rawRequest(
    `${API_BASE}/gpt-digest/configs/${configId}/issues/${encodeURIComponent(issueKey)}/explain`,
    { method: 'POST' },
  )
  return (await response.json()) as { issue: GptDigestIssue }
}

/** 来源覆盖列表（F046 静音列表 / F048/F055 来源设置消费）。 */
export async function listSourceOverrides(): Promise<{ items: SourceOverrideResult[] }> {
  return request<{ items: SourceOverrideResult[] }>(`${API_BASE}/sources/overrides`)
}

/** F11/F13/F001/N015：来源显示覆盖（sentinel：null=清除该维度，缺席=不改）。 */
export async function setSourceOverride(patch: {
  feedUrl: string
  hiddenUntil?: string | null
  showFrom?: string | null
  staleAlertHours?: number | null
  extractPolicy?: string | null
  readerStyle?: Record<string, number> | null
  /** F066：per-source AI 禁用（服务端执行点统一判定）。 */
  aiDisabled?: boolean
  /** N015：分时静音窗口（每周循环；null=清除，缺席=不改）。 */
  muteWindows?: { days: number[]; start: string; end: string }[] | null
}): Promise<SourceOverrideResult> {
  const response = await rawRequest(`${API_BASE}/sources/overrides`, {
    method: 'PUT',
    body: JSON.stringify(patch),
    contentType: 'application/json',
  })
  return (await response.json()) as SourceOverrideResult
}

/** N013：一个来源的显示别名（服务端真源；展示时优先于上游标题）。 */
export type SourceAliasView = {
  feedUrl: string
  customName: string
  updatedAt: string
}

/** N013：一条改名历史（oldCustomName 为 null = 首设别名）。 */
export type SourceAliasHistoryItem = {
  id: number
  feedUrl: string
  oldCustomName: string | null
  upstreamNameAtSave: string | null
  changedAt: string
}

/** N013：全部来源别名（时间线/订阅展示「服务端赢」的数据源）。 */
export async function listSourceAliases(): Promise<{ items: SourceAliasView[] }> {
  return request<{ items: SourceAliasView[] }>(`${API_BASE}/sources/aliases`)
}

/** N013：设置/更名来源别名（upsert + 变化时服务端写历史）。 */
export async function setSourceAlias(feedUrl: string, customName: string): Promise<SourceAliasView> {
  const response = await rawRequest(`${API_BASE}/sources/alias`, {
    method: 'PUT',
    body: JSON.stringify({ feedUrl, customName }),
    contentType: 'application/json',
  })
  return (await response.json()) as SourceAliasView
}

/** N013：某来源的改名历史（新→旧；≤20；删除别名不删历史）。 */
export async function listSourceAliasHistory(
  feedUrl: string,
  limit = 20,
): Promise<{ items: SourceAliasHistoryItem[] }> {
  return request<{ items: SourceAliasHistoryItem[] }>(
    `${API_BASE}/sources/alias/history?feedUrl=${encodeURIComponent(feedUrl)}&limit=${limit}`,
  )
}

/** N013：清除来源别名（历史保留；恢复 = 用历史旧名重新 setSourceAlias）。 */
export async function deleteSourceAlias(feedUrl: string): Promise<void> {
  await rawRequest(`${API_BASE}/sources/alias?feedUrl=${encodeURIComponent(feedUrl)}`, {
    method: 'DELETE',
  })
}

// ---- N012 退订影响预览 -------------------------------------------------------

/** N012：退订影响预览（只读快照；计数如实、样本 ≤ sampleLimit）。 */
export type UnsubscribePreview = {
  subscriptionRef: string
  feedUrl: string
  title: string
  projectionEntries: number
  unreadCount: number
  workspaceItems: {
    count: number
    items: { workspaceId: string; workspaceName: string; itemRef: string }[]
  }
  boardItems: { count: number; items: { workspaceId: string; itemRef: string; status: string }[] }
  libraryItems: { count: number; items: { itemRef: string; rssItemRef: string; title: string }[] }
  annotations: { count: number; items: { id: string; entryRef: string; excerpt: string }[] }
  inboxRules: {
    count: number
    items: { id: number; field: string; operator: string; value: string; matchedSample: string }[]
  }
  sampleLimit: number
  note: string
}

/** N012：退订影响预览（纯只读；先于任何确认/删除调用）。 */
export async function fetchUnsubscribePreview(subscriptionRef: string): Promise<UnsubscribePreview> {
  return request<UnsubscribePreview>(
    `${API_BASE}/subscriptions/${encodeURIComponent(subscriptionRef)}/unsubscribe-preview`,
  )
}

/** F001：按各自阈值超期的来源（basis 诚实标注判定依据）。 */
export type StaleSourceItem = {
  feedUrl: string
  subscriptionRef: string | null
  title: string
  staleAlertHours: number
  lastActivityAt: string | null
  ageHours: number | null
  basis: 'latest_entry' | 'fetch_time' | 'unknown'
}

export type StaleSourcesResponse = {
  checked: number
  items: StaleSourceItem[]
  generatedAt: string
}

export async function fetchStaleSources(
  signal?: AbortSignal,
): Promise<StaleSourcesResponse> {
  return request<StaleSourcesResponse>(`${API_BASE}/sources/stale`, signal)
}


/** F019：回收站条目。 */
export type TrashItem = {
  uuid: string
  kind: 'bookmark' | 'clip'
  title: string
  url: string | null
  deletedAt: string
}

/** F019：回收站列表（type 可选过滤）。 */
export async function listTrash(
  type?: 'bookmark' | 'clip',
  signal?: AbortSignal,
): Promise<{ items: TrashItem[] }> {
  const qs = type !== undefined ? `?type=${type}` : ''
  return request(`${API_BASE}/library/trash` + qs, signal)
}

/** F019：从回收站恢复。 */
export async function restoreTrashItem(uuid: string): Promise<void> {
  await rawRequest(`${API_BASE}/library/trash/${encodeURIComponent(uuid)}/restore`, {
    method: 'POST',
  })
}

/** F019：永久删除（UI 必须先二次确认；后端要求显式 permanent=true）。 */
export async function purgeTrashItem(uuid: string): Promise<void> {
  await rawRequest(`${API_BASE}/library/trash/${encodeURIComponent(uuid)}?permanent=true`, {
    method: 'DELETE',
  })
}


/** F020：Markdown 批量入库（BFF 逐文件校验 + content_hash 幂等）。 */
export type NoteImportResult = {
  items: { name: string; ok: boolean; uuid: string | null; reason: string | null }[]
  imported: number
  skipped: number
}

export async function importLumiNotes(payload: {
  files: { name: string; content: string }[]
  workspaceId?: string | null
}): Promise<NoteImportResult> {
  const body: Record<string, unknown> = { files: payload.files }
  if (payload.workspaceId != null) body.workspaceId = payload.workspaceId
  const response = await rawRequest(`${API_BASE}/library/notes/import`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  return (await response.json()) as NoteImportResult
}

/** F020：笔记列表（摘要首行）。 */
export async function listLumiNotes(
  workspaceId?: string | null,
  signal?: AbortSignal,
): Promise<{ items: { uuid: string; title: string; excerpt: string; updatedAt: string }[] }> {
  const qs = workspaceId != null ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ''
  return request(`${API_BASE}/library/notes` + qs, signal)
}

/** F004：重复订阅候选（只读，仅展示）。 */
export type DuplicateSuspectGroup = {
  key: string
  members: {
    subscriptionRef: string
    title: string
    feedUrl: string
    categoryLabel: string | null
  }[]
  differences: string[]
}

export async function fetchDuplicateSuspects(
  signal?: AbortSignal,
): Promise<{ groups: DuplicateSuspectGroup[]; checked: number }> {
  return request(`${API_BASE}/subscriptions/duplicate-suspects`, signal)
}

/** F005：来源备注视图。 */
export type SourceNotesView = {
  subscriptionRef: string
  note: string | null
  reason: string | null
  maintenanceLog: string | null
  updatedAt: string | null
}

export async function getSourceNotes(
  subscriptionRef: string,
  signal?: AbortSignal,
): Promise<SourceNotesView> {
  return request(
    `${API_BASE}/subscriptions/${encodeURIComponent(subscriptionRef)}/notes`,
    signal,
  )
}

/** F005：备注列表（可选 note_search 后端过滤）。 */
export async function listSourceNotes(
  noteSearch?: string,
  signal?: AbortSignal,
): Promise<{ items: SourceNotesView[] }> {
  const qs = noteSearch ? `?note_search=${encodeURIComponent(noteSearch)}` : ''
  return request(`${API_BASE}/subscriptions/notes` + qs, signal)
}

/** F005：更新备注（sentinel：undefined=不改，null=清空）。 */
export async function updateSourceNotes(patch: {
  subscriptionRef: string
  note?: string | null
  reason?: string | null
  maintenanceLog?: string | null
}): Promise<SourceNotesView> {
  const { subscriptionRef, ...body } = patch
  const response = await rawRequest(
    `${API_BASE}/subscriptions/${encodeURIComponent(subscriptionRef)}/notes`,
    { method: 'PATCH', body: JSON.stringify(body), contentType: 'application/json' },
  )
  return (await response.json()) as SourceNotesView
}

/** F006：批量分类迁移（逐项执行、逐项汇报）。 */
export type BatchMoveResult = {
  items: { ref: string; ok: boolean; error: string | null }[]
  moved: number
}

export async function batchMoveSubscriptions(payload: {
  refs: string[]
  targetCategoryId: string
}): Promise<BatchMoveResult> {
  const response = await rawRequest(`${API_BASE}/subscriptions/batch-move`, {
    method: 'POST',
    body: JSON.stringify(payload),
    contentType: 'application/json',
  })
  return (await response.json()) as BatchMoveResult
}

/** F23：单条标题按需翻译（缓存优先；原题保留）。 */
export async function translateEntryTitle(
  entryRef: string,
  language = 'zh-CN',
): Promise<TitleTranslationView> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/translate-title`,
    { method: 'POST', body: JSON.stringify({ language }), contentType: 'application/json' },
  )
  return (await response.json()) as TitleTranslationView
}

/** F21：术语本列表（搜索 q 可选）。 */
export async function listGlossary(
  signal?: AbortSignal,
  q?: string,
): Promise<GlossaryTermList> {
  const suffix = q ? `&q=${encodeURIComponent(q)}` : ''
  return request<GlossaryTermList>(`${API_BASE}/glossary?limit=100${suffix}`, signal)
}

/** F21：新建术语（N083：protect = 专有名词保留）。 */
export async function createGlossaryTerm(payload: {
  term: string
  definition: string
  protect?: boolean
}): Promise<GlossaryTerm> {
  const response = await rawRequest(`${API_BASE}/glossary`, {
    method: 'POST',
    body: JSON.stringify(payload),
    contentType: 'application/json',
  })
  return (await response.json()) as GlossaryTerm
}

/** F21：修改术语（PATCH 全量替换；N083：protect 可翻转）。 */
export async function updateGlossaryTerm(
  id: string,
  payload: { term: string; definition: string; protect?: boolean },
): Promise<GlossaryTerm> {
  const response = await rawRequest(`${API_BASE}/glossary/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
    contentType: 'application/json',
  })
  return (await response.json()) as GlossaryTerm
}

/** F21：删除术语。 */
export async function deleteGlossaryTerm(id: string): Promise<void> {
  await rawRequest(`${API_BASE}/glossary/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

/** F36：存储用量（只读统计；无预算时 warning 为 null）。 */
export async function getStorageUsage(signal?: AbortSignal): Promise<StorageUsage> {
  return request<StorageUsage>(`${API_BASE}/storage/usage`, signal)
}

/** F12：订阅收件量概览（口径 = 发布时间窗口；投影未覆盖 → null）。 */
export async function getSubscriptionVolume(
  signal?: AbortSignal,
  days = 7,
): Promise<SubscriptionVolumeResponse> {
  return request<SubscriptionVolumeResponse>(
    `${API_BASE}/sources/volume?days=${days}`,
    signal,
  )
}

/** F19：延后一个稍后读项目（until=ISO 未来时刻；到期自动回时间线）。 */
export async function snoozeReadLaterItem(itemRef: string, until: string): Promise<void> {
  await rawRequest(
    `${API_BASE}/workspaces/read-later/items/${encodeURIComponent(itemRef)}/snooze`,
    { method: 'POST', body: JSON.stringify({ until }), contentType: 'application/json' },
  )
}

/** GPT 日报设置（token 不在此响应中，见 getGptDigestFeed）。 */
export async function getGptDigestSettings(signal?: AbortSignal): Promise<GptDigestSettings> {
  return request<GptDigestSettings>(`${API_BASE}/gpt-digest/settings`, signal)
}

/** 部分更新 GPT 日报设置；非法值由服务端回退现值。 */
export async function updateGptDigestSettings(
  patch: GptDigestSettingsUpdate,
): Promise<GptDigestSettings> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/settings`, {
    method: 'PUT',
    body: JSON.stringify(patch),
    contentType: 'application/json',
  })
  return (await response.json()) as GptDigestSettings
}

/** 订阅路径（含 token；token 即凭据，只在会话认证下返回）。 */
export async function getGptDigestFeed(): Promise<GptDigestFeedInfo> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/feed`, { method: 'GET' })
  return (await response.json()) as GptDigestFeedInfo
}

/** 轮换订阅 token：旧 URL 立即失效。 */
export async function rotateGptDigestFeed(): Promise<GptDigestFeedInfo> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/feed/rotate`, { method: 'POST' })
  return (await response.json()) as GptDigestFeedInfo
}

/** 选材预览（F06）：无副作用，sourceId 与实际生成一致。 */
export async function previewGptDigest(): Promise<GptDigestPreview> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/preview`, { method: 'GET' })
  return (await response.json()) as GptDigestPreview
}

/** 显式生成/修订当天期号（用户动作，忽略 enabled）。失败时 error.type:
 * no_material / generation_failed / ai_not_configured / ai_upstream。 */
export async function generateGptDigest(): Promise<{ issue: GptDigestIssue; promptVersion: string }> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/generate`, { method: 'POST' })
  return (await response.json()) as { issue: GptDigestIssue; promptVersion: string }
}

/** 最近期刊（不含正文 HTML）。 */
export async function listGptDigestIssues(
  signal?: AbortSignal,
  limit = 14,
): Promise<GptDigestIssueList> {
  return request<GptDigestIssueList>(`${API_BASE}/gpt-digest/issues?limit=${limit}`, signal)
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

// ---- P16：多设备交接（设备档案 / 导出模板 / 交接；全部用户级） ----

/** 设备档案列表（描述用户各设备上的 Obsidian vault，仅用于 URI 生成）。 */
export async function listObsidianDevices(signal?: AbortSignal): Promise<ObsidianDeviceProfileList> {
  return request<ObsidianDeviceProfileList>(`${API_BASE}/obsidian/devices`, signal)
}

/** 新建设备档案（201 返回服务端创建的完整行）。 */
export async function createObsidianDevice(
  payload: ObsidianDeviceProfilePayload,
): Promise<ObsidianDeviceProfile> {
  const response = await rawRequest(`${API_BASE}/obsidian/devices`, {
    method: 'POST',
    body: JSON.stringify(payload),
    contentType: 'application/json',
  })
  return (await response.json()) as ObsidianDeviceProfile
}

/** 更新设备档案（全量载荷；他人/不存在的 id = 404，路由即隔离）。 */
export async function updateObsidianDevice(
  deviceId: string,
  payload: ObsidianDeviceProfilePayload,
): Promise<ObsidianDeviceProfile> {
  const response = await rawRequest(
    `${API_BASE}/obsidian/devices/${encodeURIComponent(deviceId)}`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as ObsidianDeviceProfile
}

/** 删除设备档案（204；不存在 = 404）。 */
export async function deleteObsidianDevice(deviceId: string): Promise<void> {
  await rawRequest(`${API_BASE}/obsidian/devices/${encodeURIComponent(deviceId)}`, {
    method: 'DELETE',
  })
}

/** 导出模板视图：template 为空串 = 跟随 defaultTemplate。 */
export async function getObsidianExportTemplate(
  signal?: AbortSignal,
): Promise<ObsidianExportTemplateView> {
  return request<ObsidianExportTemplateView>(`${API_BASE}/obsidian/export-template`, signal)
}

/** 保存导出模板（template='' = 回到默认模板；exportNamePolicy 为 N135
 * 命名策略，null = 不改模板只改策略）。 */
export async function updateObsidianExportTemplate(
  template: string | null,
  exportNamePolicy?: ObsidianExportTemplateView['exportNamePolicy'],
): Promise<ObsidianExportTemplateView> {
  const body: Record<string, unknown> = { template }
  if (exportNamePolicy !== undefined) {
    body.exportNamePolicy = exportNamePolicy
  }
  const response = await rawRequest(`${API_BASE}/obsidian/export-template`, {
    method: 'PUT',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  return (await response.json()) as ObsidianExportTemplateView
}

/** 模板实时预览：entryRef 缺省 = 夹具文本；unknownVars 诚实上报。 */
export async function previewObsidianExportTemplate(
  template: string,
  entryRef?: string | null,
): Promise<ObsidianTemplatePreviewResult> {
  const response = await rawRequest(`${API_BASE}/obsidian/export-template/preview`, {
    method: 'POST',
    body: JSON.stringify({ template, entryRef: entryRef ?? null }),
    contentType: 'application/json',
  })
  return (await response.json()) as ObsidianTemplatePreviewResult
}

/** 导出到 Obsidian 交接：mode='uri' → 打开 uri（用户在 Obsidian 确认
 * 保存）；mode='file'（tooLong）→ 前端下载 .md + 剪贴板回退。
 * onlySinceLastExport（N137）：只携带上次导出水位之后的批注。 */
export async function requestObsidianExportHandoff(
  entryRef: string,
  deviceId: string,
  options: { onlySinceLastExport?: boolean } = {},
): Promise<ObsidianExportHandoffResult> {
  const response = await rawRequest(`${API_BASE}/obsidian/export-handoff`, {
    method: 'POST',
    body: JSON.stringify({
      entryRef,
      deviceId,
      onlySinceLastExport: options.onlySinceLastExport === true,
    }),
    contentType: 'application/json',
  })
  return (await response.json()) as ObsidianExportHandoffResult
}

// ---- N134/N135/N137/N139/N140：交接闭环扩展 ----

/** N134 块级回跳反查：哪些投影笔记内嵌了 ^lumi-<paraId> 块 id。 */
export async function listObsidianBlockRefs(
  paraId: string,
  signal?: AbortSignal,
): Promise<ObsidianBlockRefsResponse> {
  const query = new URLSearchParams({ paraId })
  return request<ObsidianBlockRefsResponse>(
    `${API_BASE}/obsidian/block-refs?${query.toString()}`,
    signal,
  )
}

/** N139 导出侧链接校验（只读报告；不交接、不落日志、不推水位）。 */
export async function validateObsidianExport(
  entryRef: string,
  deviceId: string,
  options: { onlySinceLastExport?: boolean } = {},
): Promise<ObsidianExportValidateResult> {
  const response = await rawRequest(`${API_BASE}/obsidian/export-handoff/validate`, {
    method: 'POST',
    body: JSON.stringify({
      entryRef,
      deviceId,
      onlySinceLastExport: options.onlySinceLastExport === true,
    }),
    contentType: 'application/json',
  })
  return (await response.json()) as ObsidianExportValidateResult
}

/** N140 交接记录列表（新→旧）。 */
export async function listObsidianHandoffLog(
  signal?: AbortSignal,
): Promise<ObsidianHandoffLogList> {
  return request<ObsidianHandoffLogList>(`${API_BASE}/obsidian/handoff-log`, signal)
}

/** N140 显式确认（唯一 confirmed 路径；页面可见性等被动事件绝不调用）。 */
export async function confirmObsidianHandoff(
  handoffId: string,
): Promise<ObsidianHandoffLogEntry> {
  const response = await rawRequest(
    `${API_BASE}/obsidian/handoff/${encodeURIComponent(handoffId)}/confirm`,
    { method: 'POST' },
  )
  return (await response.json()) as ObsidianHandoffLogEntry
}

/** N140 清空交接历史（返回如实删除条数）。 */
export async function clearObsidianHandoffLog(): Promise<ObsidianHandoffLogClearResult> {
  const response = await rawRequest(`${API_BASE}/obsidian/handoff-log`, {
    method: 'DELETE',
  })
  return (await response.json()) as ObsidianHandoffLogClearResult
}

/** N137 增量预览：上次导出水位之后的新增/修改计数（可按文章收窄）。 */
export async function getAnnotationsExportDelta(
  entryRef?: string | null,
  signal?: AbortSignal,
): Promise<AnnotationExportDelta> {
  const query = new URLSearchParams()
  if (entryRef) {
    query.set('entryRef', entryRef)
  }
  const qs = query.toString()
  // ? 号内联在字面量里：契约测试按 `?` 截断路径，变量携带的查询串
  // 会被折叠成形状错误的多余参数段（同 listKnowledgeCards 口径）。
  const path =
    qs === ''
      ? `${API_BASE}/annotations/export-delta`
      : `${API_BASE}/annotations/export-delta?${qs}`
  return request<AnnotationExportDelta>(path, signal)
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
// 契约类型：凡 OpenAPI 已收录的信封一律用 generated 别名（下方
// `Schemas['…']`），绝不手写复制。E04 已给 Agent/RAG 全部端点补上
// response_model（AgentMessageListResponse / RagStatus 等已入
// generated schema）；本地 AgentMessage 仍保留 Record 形态的
// content——消费方按索引防御式读取（AgentWorkbenchPage），换生成
// 别名需改为窄化访问，属后续重构，非契约缺口。

type Schemas = components['schemas']

export type AgentThread = Schemas['AgentThread']

export type AgentThreadListResponse = Schemas['AgentThreadListResponse']

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

/** 批准/拒绝取值（BFF 请求体 AgentApprovalDecision.decision 的有效值；
 * BFF 侧是裸 str，OpenAPI 抓不到枚举，故在此手写联合）。 */
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

/** 列表行复用 BFF 的 TagBinding 模型（id/name/count + 可选绑定字段）。 */
export type TagSummary = Schemas['TagBinding']

export type TagListResponse = Schemas['TagListResponse']

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
export async function renameTag(tagId: number, name: string): Promise<TagSummary> {
  const response = await rawRequest(`${API_BASE}/tags/${encodeURIComponent(String(tagId))}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
    contentType: 'application/json',
  })
  return (await response.json()) as TagSummary
}

/** 删除标签（破坏性；DELETE 204）。 */
export async function deleteTag(tagId: number): Promise<void> {
  await rawRequest(`${API_BASE}/tags/${encodeURIComponent(String(tagId))}`, {
    method: 'DELETE',
  })
}

/** pool #16：合并预览（受影响计数，只读）。 */
export async function getTagMergePreview(
  sourceId: number,
  targetId: number,
  signal?: AbortSignal,
): Promise<TagMergePreview> {
  const query = new URLSearchParams({ sourceId: String(sourceId), targetId: String(targetId) })
  return request<TagMergePreview>(`${API_BASE}/tags/merge/preview?${query}`, signal)
}

/** pool #16：执行合并（源并入目标；一个事务）。 */
export async function mergeTags(sourceId: number, targetId: number): Promise<TagMergeResult> {
  const response = await rawRequest(`${API_BASE}/tags/merge`, {
    method: 'POST',
    body: JSON.stringify({ sourceId, targetId }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as TagMergeResult
}

/** 绑定标签（POST 201 TagBinding）。 */
export async function assignTag(input: TagAssignInput): Promise<TagSummary> {
  const response = await rawRequest(`${API_BASE}/tags/assign`, {
    method: 'POST',
    body: JSON.stringify({ itemRef: input.itemRef, name: input.name, origin: input.origin ?? 'manual' }),
    contentType: 'application/json',
  })
  return (await response.json()) as TagSummary
}

/** 解绑标签（DELETE 204，契约带 JSON body）。 */
export async function unassignTag(input: TagAssignInput): Promise<void> {
  await rawRequest(`${API_BASE}/tags/assign`, {
    method: 'DELETE',
    body: JSON.stringify({ itemRef: input.itemRef, name: input.name, origin: input.origin ?? 'manual' }),
    contentType: 'application/json',
  })
}

/** P0-10：单条内容的既有标签（GET /tags/item/{item_ref}；含 suggested
 * 行——UI 以 status='attached' 为已勾选依据）。 */
export interface ItemTag {
  tagId: number
  name: string
  origin: string
  status: string
}

export async function listTagsForItem(
  itemRef: string,
  signal?: AbortSignal,
): Promise<{ items: ItemTag[] }> {
  return request<{ items: ItemTag[] }>(
    `${API_BASE}/tags/item/${encodeURIComponent(itemRef)}`,
    signal,
  )
}

// ---- phase2 G8：关系图谱（graph，只读派生视图） ----

export type GraphNode = Schemas['GraphNode']

export type GraphEdge = Schemas['GraphEdge']

export type GraphResponse = Schemas['GraphResponse']

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
  // E04 对齐服务端契约（RagStatus.vecTable: boolean；历史上误写宽类型）。
  vecTable: boolean
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

// Q-P2-25：RagSearchResponse 已随 searchRag 一并删除（零消费者）；
// RagSearchItem 保留（语义命中行类型，Agent 引用面板语义对齐用）。

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

// Q-P2-25：searchRag 已删除（零消费者死代码）。语义检索当前只有
// Agent 工具消费（agent_tools.py）；SearchPage 的「语义」开关属于
// 新功能，届时重新引入（RAG 语义直接检索面，见 recovery 账本）。

// ---- phase2 recovery wave 2：统一 resolve + 稍后读时间线 ----

/** P0-02：批量解析 ItemRef → ResolvedItem（含 per-kind 打开 payload）。
 * stale/unknown 目标降级为 stale=true 的视图，绝不抛错——调用方按
 * stale 渲染「已失效」态。openTarget 语义见 lib/open-item.ts。 */
export async function resolveItems(
  refs: string[],
  signal?: AbortSignal,
): Promise<WorkspaceItemsResolvedResponse> {
  const response = await rawRequest(`${API_BASE}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ refs }),
    contentType: 'application/json',
    signal,
  })
  return (await response.json()) as WorkspaceItemsResolvedResponse
}

/** pool #09：保存搜索视图（存查询+筛选意图，不是结果集）。 */
export async function getSavedSearchViews(
  signal?: AbortSignal,
): Promise<SavedSearchViewList> {
  return request<SavedSearchViewList>(`${API_BASE}/search/views`, signal)
}

export async function createSavedSearchView(
  body: { name: string; query: string; view: string; categoryKey: string },
): Promise<SavedSearchView> {
  const response = await rawRequest(`${API_BASE}/search/views`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as SavedSearchView
}

export async function renameSavedSearchView(
  id: string,
  name: string,
): Promise<SavedSearchView> {
  const response = await rawRequest(
    `${API_BASE}/search/views/${encodeURIComponent(id)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ name }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as SavedSearchView
}

export async function deleteSavedSearchView(id: string): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/search/views/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

/** F061：私有 Atom 订阅 token 结果（atomPath 带 secret，仅此一次返回）。 */
export interface ViewFeedTokenResult {
  atomPath: string
  hasFeedToken: boolean
}

/** F061：首次启用视图私有 Atom 订阅（已启用 → 409 token_already_active）。 */
export async function enableViewFeedToken(id: string): Promise<ViewFeedTokenResult> {
  const response = await rawRequest(
    `${API_BASE}/search/views/${encodeURIComponent(id)}/token/enable`,
    { method: 'POST' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as ViewFeedTokenResult
}

/** F061：轮换订阅 token（旧地址立即失效；新地址仅本次返回）。 */
export async function rotateViewFeedToken(id: string): Promise<ViewFeedTokenResult> {
  const response = await rawRequest(
    `${API_BASE}/search/views/${encodeURIComponent(id)}/token/rotate`,
    { method: 'POST' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as ViewFeedTokenResult
}

/** P0-01：服务端稍后读时间线（order: newest（默认）| oldest（pool #14）；
 * cursor opaque 原样透传，绑定排序方向；悬挂成员以 stale=true 行可见
 * 而非消失）。 */
export async function getReadLaterTimeline(
  params: {
    limit?: number
    cursor?: string | null
    order?: 'newest' | 'oldest'
  } = {},
  signal?: AbortSignal,
): Promise<ReadLaterTimelineResponse> {
  const query = new URLSearchParams()
  if (params.limit != null) {
    query.set('limit', String(params.limit))
  }
  if (params.cursor != null) {
    query.set('cursor', params.cursor)
  }
  if (params.order != null && params.order !== 'newest') {
    query.set('order', params.order)
  }
  return request<ReadLaterTimelineResponse>(
    `${API_BASE}/workspaces/read-later/timeline?${query}`,
    signal,
  )
}

// ---- 0021：Inbox 推送来源（连接器管理 + 条目 refs；卡片经 /resolve）----

/** GET /api/v1/inbox/sources —— 连接器列表（永不回显 secret）。 */
export async function listInboxSources(signal?: AbortSignal): Promise<InboxSource[]> {
  return request<InboxSource[]>(`${API_BASE}/inbox/sources`, signal)
}

/** POST /api/v1/inbox/sources —— 创建连接器；bearer secret 仅此一次返回。 */
export async function createInboxSource(name: string): Promise<InboxSourceCreated> {
  const response = await rawRequest(`${API_BASE}/inbox/sources`, {
    method: 'POST',
    body: JSON.stringify({ name }),
    contentType: 'application/json',
  })
  return (await response.json()) as InboxSourceCreated
}

/** DELETE /api/v1/inbox/sources/{uuid} —— 删除连接器及其全部推送条目；
 * 404（另一设备/标签页已删除）按幂等成功处理。 */
export async function deleteInboxSource(sourceUuid: string): Promise<void> {
  try {
    await rawRequest(
      `${API_BASE}/inbox/sources/${encodeURIComponent(sourceUuid)}`,
      { method: 'DELETE' },
    )
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) throw error
  }
}

/** GET /api/v1/inbox/items —— 最新在前 refs 分页；卡片渲染走 /resolve。 */
export async function listInboxItems(
  params: { limit?: number; cursor?: string | null } = {},
  signal?: AbortSignal,
): Promise<InboxItemList> {
  const query = new URLSearchParams()
  if (params.limit != null) {
    query.set('limit', String(params.limit))
  }
  if (params.cursor != null) {
    query.set('cursor', params.cursor)
  }
  return request<InboxItemList>(`${API_BASE}/inbox/items?${query}`, signal)
}

/** DELETE /api/v1/inbox/items/{uuid} —— 删除单条推送内容；
 * 404（另一设备/标签页已删除）按幂等成功处理。 */
export async function deleteInboxItem(itemRef: string): Promise<void> {
  const uuid = itemRef.startsWith('library:')
    ? itemRef.slice('library:'.length)
    : itemRef
  try {
    await rawRequest(
      `${API_BASE}/inbox/items/${encodeURIComponent(uuid)}`,
      { method: 'DELETE' },
    )
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) throw error
  }
}

/** GET /api/v1/sources —— 统一来源注册表（只读综合，不含任何 secret）。 */
export async function listSources(signal?: AbortSignal): Promise<SourceRegistryResponse> {
  return request<SourceRegistryResponse>(`${API_BASE}/sources`, signal)
}

// ---- Q-P1-07：IMAP 收信通路（后端 4 端点早已存在，此前无任何 UI） ----
// 类型来自生成契约（generated/schema），不手写复制。

export type MailImapSettings = G6Schemas['MailImapSettings']
export interface MailImapSettingsUpdate {
  host?: string
  port?: number
  user?: string
  folder?: string
  ssl?: boolean
  listUuid?: string
  intervalSeconds?: number
  /** F007：False = 轮询与手动拉取直接跳过。 */
  enabled?: boolean
  /** write-only：GET 永不回显。 */
  password?: string
}
export type MailImapTestResult = G6Schemas['MailImapTestResult']
export type MailImapPollResult = G6Schemas['MailImapPollResult']

/** GET /api/v1/mail/imap/settings —— password 永不回显（write-only）。 */
export async function getMailImapSettings(
  signal?: AbortSignal,
): Promise<MailImapSettings> {
  return request<MailImapSettings>(`${API_BASE}/mail/imap/settings`, signal)
}

/** PUT /api/v1/mail/imap/settings —— partial 更新 + write-only 密码。 */
export async function updateMailImapSettings(
  patch: MailImapSettingsUpdate,
): Promise<MailImapSettings> {
  const response = await rawRequest(`${API_BASE}/mail/imap/settings`, {
    method: 'PUT',
    body: JSON.stringify(patch),
    contentType: 'application/json',
  })
  return (await response.json()) as MailImapSettings
}

/** POST /api/v1/mail/imap/test —— 连通性+认证探测（不下载任何邮件）。 */
export async function testMailImap(): Promise<MailImapTestResult> {
  const response = await rawRequest(`${API_BASE}/mail/imap/test`, { method: 'POST' })
  return (await response.json()) as MailImapTestResult
}

/** POST /api/v1/mail/imap/poll —— 手动单次拉取到绑定的 bridge 列表。 */
export async function pollMailImap(): Promise<MailImapPollResult> {
  const response = await rawRequest(`${API_BASE}/mail/imap/poll`, { method: 'POST' })
  return (await response.json()) as MailImapPollResult
}

// ==== W2（F021–F040）净新增功能 API =========================================

// ---- F021 手工关联内容 ----

export interface RelationEndView {
  ref: string
  domain: string
  kind: string
  title: string
  source: string
  datetime?: string | null
  excerpt?: string | null
  url?: string | null
  stale: boolean
  staleReason?: string | null
}

export interface ItemRelationView {
  id: number
  srcRef: string
  dstRef: string
  note: string
  createdAt: string
  src: RelationEndView
  dst: RelationEndView
  stale: boolean
}

/** F021：双向列出某条目的手工关联（失效端 stale=true，绝不抛错吞掉）。 */
export async function listRelationsForItem(
  itemRef: string,
  signal?: AbortSignal,
): Promise<{ items: ItemRelationView[] }> {
  const query = new URLSearchParams({ itemRef })
  return request<{ items: ItemRelationView[] }>(
    `${API_BASE}/relations?${query}`,
    signal,
  )
}

/** F021：创建手工关联（自关联/无效引用 → 422；同向不同备注 → 409）。 */
export async function createRelation(body: {
  srcRef: string
  dstRef: string
  note?: string
}): Promise<ItemRelationView> {
  const response = await rawRequest(`${API_BASE}/relations`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as ItemRelationView
}

/** F021：解除关联（幂等语义由 404 表达）。 */
export async function deleteRelation(id: number): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/relations/${encodeURIComponent(String(id))}`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

// ---- F022 收件箱归类规则 ----

export interface InboxRuleView {
  id: number
  priority: number
  field: 'source' | 'title'
  operator: 'contains' | 'equals'
  value: string
  targetWorkspaceId: string
  enabled: boolean
  createdAt: string
}

export interface InboxRuleDryRunResultView {
  matchedRule: InboxRuleView | null
  explanation: string
}

export async function getInboxRules(signal?: AbortSignal): Promise<{ items: InboxRuleView[] }> {
  return request<{ items: InboxRuleView[] }>(`${API_BASE}/inbox/rules`, signal)
}

export async function createInboxRule(body: {
  field: string
  operator: string
  value: string
  targetWorkspaceId: string
  enabled?: boolean
}): Promise<InboxRuleView> {
  const response = await rawRequest(`${API_BASE}/inbox/rules`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as InboxRuleView
}

export async function patchInboxRule(
  id: number,
  body: Partial<{ field: string; operator: string; value: string; targetWorkspaceId: string; enabled: boolean }>,
): Promise<InboxRuleView> {
  const response = await rawRequest(
    `${API_BASE}/inbox/rules/${encodeURIComponent(String(id))}`,
    { method: 'PATCH', body: JSON.stringify(body), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as InboxRuleView
}

export async function moveInboxRule(id: number, direction: 'up' | 'down'): Promise<InboxRuleView> {
  const response = await rawRequest(
    `${API_BASE}/inbox/rules/${encodeURIComponent(String(id))}/move?direction=${direction}`,
    { method: 'POST' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as InboxRuleView
}

export async function deleteInboxRule(id: number): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/inbox/rules/${encodeURIComponent(String(id))}`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

export async function dryRunInboxRule(body: {
  field: string
  value: string
  source?: string
}): Promise<InboxRuleDryRunResultView> {
  const response = await rawRequest(`${API_BASE}/inbox/rules/dry-run`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as InboxRuleDryRunResultView
}

// ---- F023 跨来源作者聚合 ----

export interface AuthorSummaryView {
  author: string
  count: number
}

export interface AuthorAliasView {
  alias: string
  canonical: string
  createdAt: string
}

export interface AuthorItemsView {
  author: string
  items: Array<{
    entryRef: string
    title: string
    feedTitle: string
    author?: string | null
    url?: string | null
    publishedAt: string
    read: boolean
    starred: boolean
  }>
  hasMore: boolean
}

export async function getAuthors(
  signal?: AbortSignal,
  limit = 50,
): Promise<{ items: AuthorSummaryView[] }> {
  return request<{ items: AuthorSummaryView[] }>(
    `${API_BASE}/authors?limit=${limit}`,
    signal,
  )
}

export async function getAuthorItems(
  author: string,
  offset = 0,
  limit = 20,
  signal?: AbortSignal,
): Promise<AuthorItemsView> {
  const query = new URLSearchParams({
    author,
    limit: String(limit),
    offset: String(offset),
  })
  return request<AuthorItemsView>(`${API_BASE}/authors/items?${query}`, signal)
}

export async function getAuthorAliases(
  signal?: AbortSignal,
): Promise<{ items: AuthorAliasView[] }> {
  return request<{ items: AuthorAliasView[] }>(`${API_BASE}/authors/aliases`, signal)
}

export async function createAuthorAlias(body: {
  alias: string
  canonical: string
}): Promise<AuthorAliasView> {
  const response = await rawRequest(`${API_BASE}/authors/aliases`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as AuthorAliasView
}

export async function deleteAuthorAlias(alias: string): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/authors/aliases/${encodeURIComponent(alias)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

// ---- F024 积压整理助手 ----

export interface BacklogSampleItemView {
  ref: string
  title: string
  publishedAt?: string | null
}

export interface BacklogPreviewView {
  count: number
  sample: BacklogSampleItemView[]
  effectiveExclusions: string[]
  confirmPreviewToken: string
}

export interface BacklogApplyView {
  applied: number
  failed: BacklogSampleItemView[]
  effectiveExclusions: string[]
}

export interface BacklogCondition {
  olderThanDays: number
  feedUrl?: string | null
  categoryId?: string | null
}

/** F024：预览（真实 count + 前 20 样本 + 一次性 token；零写入）。 */
export async function previewBacklog(
  condition: BacklogCondition,
  signal?: AbortSignal,
): Promise<BacklogPreviewView> {
  const response = await rawRequest(`${API_BASE}/entries/backlog-preview`, {
    method: 'POST',
    body: JSON.stringify({
      ...condition,
      excludeStarred: true,
      excludeReadLater: true,
    }),
    contentType: 'application/json',
    signal,
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as BacklogPreviewView
}

/** F024：确认执行（必须带 preview 的 token，防条件漂移）。 */
export async function applyBacklog(
  condition: BacklogCondition,
  confirmPreviewToken: string,
): Promise<BacklogApplyView> {
  const response = await rawRequest(`${API_BASE}/entries/backlog-apply`, {
    method: 'POST',
    body: JSON.stringify({
      ...condition,
      excludeStarred: true,
      excludeReadLater: true,
      confirmPreviewToken,
    }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as BacklogApplyView
}

// ---- F025/F026/F027：AI 输入范围 + 摘要证据 + 版本 ----

/** F025：生成摘要（可选 maxChars 限定发送范围；响应含 inputChars/truncated）。 */
export async function generateEntrySummaryScoped(
  entryRef: string,
  maxChars?: number,
): Promise<EntrySummary> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/summary`,
    {
      method: 'POST',
      ...(maxChars !== undefined
        ? { body: JSON.stringify({ maxChars }), contentType: 'application/json' }
        : {}),
    },
  )
  return (await response.json()) as EntrySummary
}

/** F027：切换展示的摘要版本。 */
export async function activateSummaryVersion(
  entryRef: string,
  versionId: string,
): Promise<EntrySummary> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/summary/versions/${encodeURIComponent(versionId)}/activate`,
    { method: 'POST' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as EntrySummary
}

/** F030：发送对话消息（可选 maxChars）。 */
export async function sendConversationMessageScoped(
  entryRef: string,
  question: string,
  maxChars?: number,
): Promise<EntryConversation> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/conversation/messages`,
    {
      method: 'POST',
      body: JSON.stringify(
        maxChars !== undefined ? { question, maxChars } : { question },
      ),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as EntryConversation
}

/** F027：摘要版本视图（summary 响应的 versions 字段）。 */
export interface SummaryVersionItem {
  versionId: string
  summary: string
  provider: string
  model: string
  createdAt: string
}

// ---- F030 问答模板 ----

export interface QaTemplateView {
  id: string
  name: string
  text: string
  createdAt: string
  updatedAt: string
}

export async function getQaTemplates(signal?: AbortSignal): Promise<{ items: QaTemplateView[] }> {
  return request<{ items: QaTemplateView[] }>(`${API_BASE}/qa-templates`, signal)
}

export async function createQaTemplate(body: { name: string; text: string }): Promise<QaTemplateView> {
  const response = await rawRequest(`${API_BASE}/qa-templates`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as QaTemplateView
}

export async function patchQaTemplate(
  id: string,
  body: { name: string; text?: string },
): Promise<QaTemplateView> {
  const response = await rawRequest(
    `${API_BASE}/qa-templates/${encodeURIComponent(id)}`,
    { method: 'PATCH', body: JSON.stringify(body), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as QaTemplateView
}

export async function deleteQaTemplate(id: string): Promise<void> {
  const response = await rawRequest(`${API_BASE}/qa-templates/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw await toApiError(response)
}

// ---- F028 术语表批量导入导出 ----

export interface GlossaryImportOutcome {
  imported: number
  skipped: number
  overwritten: number
  errors: Array<{ index: number; reason: string }>
}

/** F028：批量导入（skip / overwrite；非法条目逐条 errors）。 */
export async function importGlossaryTerms(
  terms: Array<{ term: string; translation: string }>,
  mode: 'skip' | 'overwrite',
): Promise<GlossaryImportOutcome> {
  const response = await rawRequest(`${API_BASE}/glossary/import`, {
    method: 'POST',
    body: JSON.stringify({ terms, mode }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as GlossaryImportOutcome
}

/** F028：解析导入内容（纯前端预览：条数 + 冲突计数）。 */
export function parseGlossaryImportText(text: string): {
  terms: Array<{ term: string; translation: string }>
  parseError: string | null
} {
  try {
    const data = JSON.parse(text) as { terms?: unknown }
    if (data === null || typeof data !== 'object' || !Array.isArray(data.terms)) {
      return { terms: [], parseError: 'JSON 结构应为 { "terms": [...] }。' }
    }
    const terms: Array<{ term: string; translation: string }> = []
    let invalid = 0
    for (const raw of data.terms) {
      if (
        raw !== null &&
        typeof raw === 'object' &&
        typeof (raw as { term?: unknown }).term === 'string' &&
        typeof (raw as { translation?: unknown }).translation === 'string'
      ) {
        terms.push({
          term: (raw as { term: string }).term,
          translation: (raw as { translation: string }).translation,
        })
      } else {
        invalid += 1
      }
    }
    return {
      terms,
      parseError: invalid > 0 ? `${invalid} 条结构非法（将在导入时逐条报错）。` : null,
    }
  } catch {
    return { terms: [], parseError: '不是合法的 JSON。' }
  }
}

/** F028：导出为 JSON 下载。 */
export async function exportGlossaryJson(): Promise<void> {
  const response = await fetch(`${API_BASE}/glossary/export`)
  if (!response.ok) throw await toApiError(response)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'lumirss-glossary.json'
  anchor.click()
  URL.revokeObjectURL(url)
}

// ---- F029 术语命中预览 ----

export interface GlossaryHitItem {
  term: string
  translation: string
  count: number
  /** N083：blocks 输入提供时附带的命中位置（客户端块索引）。 */
  blockIndexes?: number[]
}

/** F029：现役 glossary 在本文正文的命中（服务端预览；与生成 prompt 同源）。
 * N083：提供 blocks 时逐块定位，命中附带 blockIndexes。 */
export async function getGlossaryHits(
  entryRef: string,
  opts?: { blocks?: TranslationSegmentBlockInput[]; signal?: AbortSignal },
): Promise<{ hits: GlossaryHitItem[]; promptBlock: string }> {
  const body = opts?.blocks && opts.blocks.length > 0 ? { blocks: opts.blocks } : undefined
  const response = await fetch(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/glossary-hits`,
    {
      method: 'POST',
      ...(body !== undefined
        ? {
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(body),
          }
        : {}),
      signal: opts?.signal,
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { hits: GlossaryHitItem[]; promptBlock: string }
}

// ---- F031/F032 日报草稿审阅 + 缺失日期补刊 ----

/** F031：审阅后显式发布（幂等；校验失败 422 保留草稿）。 */
export async function publishGptDigestIssue(
  configId: number,
  issueKey: string,
): Promise<GptDigestIssue> {
  const response = await rawRequest(
    `${API_BASE}/gpt-digest/configs/${configId}/issues/${encodeURIComponent(issueKey)}/publish`,
    { method: 'POST' },
  )
  if (!response.ok) throw await toApiError(response)
  const body = (await response.json()) as { issue: GptDigestIssue }
  return body.issue
}

export interface MissingDigestDates {
  missing: string[]
  existing: string[]
}

/** F032：最近 N 天缺失期号的日期（含草稿排除）。 */
export async function getMissingDigestDates(
  configId: number,
  signal?: AbortSignal,
): Promise<MissingDigestDates> {
  return request<MissingDigestDates>(
    `${API_BASE}/gpt-digest/configs/${configId}/missing-dates?days=30`,
    signal,
  )
}

/** F032：补刊指定缺失日期（已有期号 409 protected；无材料 422）。 */
export async function generateDigestForDate(
  configId: number,
  targetDate: string,
): Promise<GptDigestIssue> {
  const response = await rawRequest(
    `${API_BASE}/gpt-digest/configs/${configId}/generate`,
    {
      method: 'POST',
      body: JSON.stringify({ targetDate }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  const body = (await response.json()) as { issue: GptDigestIssue }
  return body.issue
}

// ---- F033/F034 快照资源诊断 + 版本 ----

export interface SnapshotResource {
  url: string
  status: 'ok' | 'failed' | 'skipped'
  error?: string | null
}

export interface SnapshotDetail extends SnapshotView {
  resources: SnapshotResource[]
  resourcesTruncated: boolean
}

export interface SnapshotVersionMeta {
  versionId: number
  snapshotUuid: string
  sha256: string
  sha8: string
  text: string | null
  createdAt: string
}

/** F033：快照详情（含资源状态诊断）。 */
export async function getSnapshotDetail(
  uuid: string,
  signal?: AbortSignal,
): Promise<SnapshotDetail> {
  return request<SnapshotDetail>(
    `${API_BASE}/library/snapshots/${encodeURIComponent(uuid)}`,
    signal,
  )
}

/** F033：仅重试 failed 资源（无失败 → retried 0）。 */
export async function retryFailedSnapshotResources(uuid: string): Promise<{
  retried: number
  resources: SnapshotResource[]
}> {
  const response = await rawRequest(
    `${API_BASE}/library/snapshots/${encodeURIComponent(uuid)}/retry-failed`,
    { method: 'POST' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { retried: number; resources: SnapshotResource[] }
}

/** F034：重新采集为新版本（相同内容 → deduplicated）。 */
export async function createSnapshotVersion(uuid: string): Promise<{
  deduplicated: boolean
  versions: SnapshotVersionMeta[]
}> {
  const response = await rawRequest(
    `${API_BASE}/library/snapshots/${encodeURIComponent(uuid)}/versions`,
    { method: 'POST' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { deduplicated: boolean; versions: SnapshotVersionMeta[] }
}

/** F034：版本列表（时间 + hash 前 8）。 */
export async function listSnapshotVersions(
  uuid: string,
  signal?: AbortSignal,
): Promise<{ versions: SnapshotVersionMeta[] }> {
  return request<{ versions: SnapshotVersionMeta[] }>(
    `${API_BASE}/library/snapshots/${encodeURIComponent(uuid)}/versions`,
    signal,
  )
}

/** F034：两版本 unified 文本差异。 */
export async function diffSnapshotVersions(
  uuid: string,
  versionId: number,
  against: number,
): Promise<{ diff: string }> {
  return request<{ diff: string }>(
    `${API_BASE}/library/snapshots/${encodeURIComponent(uuid)}/versions/${versionId}/diff?against=${against}`,
  )
}

// ---- F038 会话管理 ----

export interface AuthSessionView {
  id: string
  createdAt: number
  lastSeenAt: number
  expiresAt: number
  userAgent?: string | null
  current: boolean
}

/** F038：活跃会话（绝不含 token/hash 字段）。 */
export async function listAuthSessions(signal?: AbortSignal): Promise<AuthSessionView[]> {
  return request<AuthSessionView[]>(`${API_BASE}/auth/sessions`, signal)
}

/** F038：撤销会话（撤销当前会话 = 登出）。 */
export async function revokeAuthSession(id: string): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/auth/sessions/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

// ---- F039 脱敏诊断包 ----

export interface DiagnosticsPayload {
  version: string
  schemaVersion: number
  authMode: string
  uptimeS: number
  deps: Array<{ name: string; status: string }>
  errorCountsByType: Record<string, number>
  configPresence: Record<string, boolean>
  counts: { feeds: number; entriesIndexed: number; libraryItems: number }
}

/** F039：获取脱敏诊断（仅布尔/计数；绝不含秘密值）。 */
export async function getDiagnostics(signal?: AbortSignal): Promise<DiagnosticsPayload> {
  return request<DiagnosticsPayload>(`${API_BASE}/operations/diagnostics`, signal)
}

// ---- F035 固定保存视图 ----

export async function getPinnedViews(
  signal?: AbortSignal,
): Promise<{ items: SavedSearchView[] }> {
  return request<{ items: SavedSearchView[] }>(`${API_BASE}/search/views/pinned`, signal)
}

/** F035：固定视图服务端真实计数（失效视图 error 态显示 '—'）。 */
export async function getPinnedViewCount(
  id: string,
  signal?: AbortSignal,
): Promise<{ count: number; capped: boolean; error?: string | null }> {
  return request<{ count: number; capped: boolean; error?: string | null }>(
    `${API_BASE}/search/views/${encodeURIComponent(id)}/count`,
    signal,
  )
}

export async function pinSavedView(id: string): Promise<SavedSearchView> {
  const response = await rawRequest(`${API_BASE}/search/views/${encodeURIComponent(id)}/pin`, {
    method: 'POST',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as SavedSearchView
}

export async function unpinSavedView(id: string): Promise<SavedSearchView> {
  const response = await rawRequest(`${API_BASE}/search/views/${encodeURIComponent(id)}/unpin`, {
    method: 'POST',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as SavedSearchView
}

// ---- W3（F044-F052/F056/F058）新增端点 ---------------------------------

/** F044：RSS 地址迁移（FreshRSS 无原位改 URL；新建订阅+元数据随迁）。 */
export interface SubscriptionMigrateResult {
  oldSubscriptionRef: string
  oldFeedUrl: string
  newSubscriptionRef: string | null
  newFeedUrl: string
  newTitle: string | null
  copiedNotes: boolean
  copiedOverrides: boolean
  note: string
}

export async function migrateSubscription(
  subscriptionRef: string,
  newUrl: string,
): Promise<SubscriptionMigrateResult> {
  const response = await rawRequest(
    `${API_BASE}/subscriptions/${encodeURIComponent(subscriptionRef)}/migrate`,
    { method: 'POST', body: JSON.stringify({ newUrl }), contentType: 'application/json' },
  )
  return (await response.json()) as SubscriptionMigrateResult
}

/** F045：服务端屏蔽规则。 */
export interface FeedFilterRule {
  id: string
  feedUrl: string
  field: 'title' | 'author'
  op: 'contains' | 'equals'
  value: string
  enabled: boolean
  createdAt: string
}

export async function listFeedFilterRules(feedUrl?: string): Promise<{ items: FeedFilterRule[] }> {
  const path = feedUrl !== undefined ? `/feed-filter-rules?feedUrl=${encodeURIComponent(feedUrl)}` : '/feed-filter-rules'
  return request<{ items: FeedFilterRule[] }>(`${API_BASE}${path}`)
}

export async function createFeedFilterRule(input: {
  feedUrl: string
  field: 'title' | 'author'
  op: 'contains' | 'equals'
  value: string
  enabled?: boolean
}): Promise<FeedFilterRule> {
  const response = await rawRequest(`${API_BASE}/feed-filter-rules`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as FeedFilterRule
}

export async function deleteFeedFilterRule(id: string): Promise<void> {
  await rawRequest(`${API_BASE}/feed-filter-rules/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export async function trialFeedFilterRule(input: {
  feedUrl?: string
  sampleTitle: string
  sampleAuthor?: string | null
}): Promise<{ matched: boolean; ruleId: string | null; reason: string | null }> {
  const response = await rawRequest(`${API_BASE}/feed-filter-rules/trial`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as { matched: boolean; ruleId: string | null; reason: string | null }
}

/** F050：批量检查台（纯诊断，不改配置）。 */
export interface HealthCheckItem {
  ref: string
  status: 'ok' | 'auth_error' | 'not_found' | 'rate_limited' | 'timeout' | 'bad_content' | 'network_error'
  httpStatus?: number
  checkedAt: string
}

export async function runHealthCheck(refs: string[], timeoutS = 5): Promise<{ items: HealthCheckItem[] }> {
  const response = await rawRequest(`${API_BASE}/subscriptions/health-check`, {
    method: 'POST',
    body: JSON.stringify({ refs, timeoutS }),
    contentType: 'application/json',
  })
  return (await response.json()) as { items: HealthCheckItem[] }
}

/** F049：导入批次。 */
export interface ImportBatch {
  id: string
  kind: 'opml' | 'bookmarks' | 'md_notes'
  createdAt: string
  counts: { imported?: number; skipped?: number; failed?: number }
  errors: { items: { url?: string; reason?: string }[]; truncated: boolean }
  retryPayload: { url?: string; title?: string | null }[]
}

export async function listImportBatches(limit = 20): Promise<{ items: ImportBatch[] }> {
  return request<{ items: ImportBatch[] }>(`${API_BASE}/library/import-batches?limit=${limit}`)
}

export async function retryImportBatch(
  batchId: string,
): Promise<{ batchId: string; imported: number; skipped: number; failed: number; errors: { url?: string; reason?: string }[] }> {
  const response = await rawRequest(
    `${API_BASE}/library/import-batches/${encodeURIComponent(batchId)}/retry`,
    { method: 'POST' },
  )
  return (await response.json()) as {
    batchId: string
    imported: number
    skipped: number
    failed: number
    errors: { url?: string; reason?: string }[]
  }
}

/** F051：批注（服务端真源；localStorage 降级为离线缓存）。 */
export interface Annotation {
  id: string
  entryRef: string
  anchor: Record<string, unknown>
  anchorHash: string
  excerpt: string
  note: string
  color: string
  createdAt: string
  updatedAt: string
}

export async function listAnnotations(params: {
  entryRef?: string
  q?: string
  color?: string
  cursor?: string
}): Promise<{ items: Annotation[]; nextCursor: string | null }> {
  const search = new URLSearchParams()
  if (params.entryRef) search.set('entryRef', params.entryRef)
  if (params.q) search.set('q', params.q)
  if (params.color) search.set('color', params.color)
  if (params.cursor) search.set('cursor', params.cursor)
  return request<{ items: Annotation[]; nextCursor: string | null }>(
    `${API_BASE}/annotations?${search.toString()}`,
  )
}

export async function createAnnotation(input: {
  entryRef: string
  anchor: Record<string, unknown>
  excerpt?: string | null
  note?: string | null
  color?: string
}): Promise<Annotation> {
  const response = await rawRequest(`${API_BASE}/annotations`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as Annotation
}

export async function updateAnnotation(
  id: string,
  patch: { note?: string; excerpt?: string; color?: string },
): Promise<Annotation> {
  const response = await rawRequest(`${API_BASE}/annotations/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
    contentType: 'application/json',
  })
  return (await response.json()) as Annotation
}

export async function deleteAnnotation(id: string): Promise<void> {
  await rawRequest(`${API_BASE}/annotations/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

/** F048：单篇「用提取正文试读」（extractOnce 临时预览，不改来源策略）。 */
export async function getEntryExtractPreview(entryRef: string): Promise<{
  contentHtml: string | null
  extractionFailed: boolean | null
}> {
  return request<{ contentHtml: string | null; extractionFailed: boolean | null }>(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}?extractOnce=true`,
  )
}

/** F052：批注汇编导出（Markdown 下载）。N075：citeBibliography=true
 *  时每篇文章追加「引用格式」行（缺失项「不详」）。 */
export async function exportAnnotations(input: {
  entryRefs?: string[]
  q?: string
  citeBibliography?: boolean
}): Promise<Blob> {
  const response = await rawRequest(`${API_BASE}/annotations/export`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return await response.blob()
}

/** F056：跨设备继续阅读。 */
export interface ReadingProgressItem {
  entryRef: string
  paraId: string
  pct: number
  deviceLabel: string
  updatedAt: string
}

export async function putReadingProgress(input: {
  entryRef: string
  paraId: string
  pct: number
  deviceLabel: string
}): Promise<void> {
  await rawRequest(`${API_BASE}/reading-progress`, {
    method: 'PUT',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
}

export async function listReadingProgress(limit = 5): Promise<{ items: ReadingProgressItem[] }> {
  return request<{ items: ReadingProgressItem[] }>(`${API_BASE}/reading-progress?limit=${limit}`)
}

/** F058：批注复习队列。 */
/** F058/N076/N077：复习队列项（泛化：批注 | 知识卡片 + 来源追踪）。 */
export interface ReviewQueueItem {
  id: string
  itemKind: 'annotation' | 'knowledge_card'
  annotationId: string | null
  knowledgeCardId: string | null
  entryRef: string | null
  /** 批注锚点段落（N077 查看原文段落 deep link 用；无 → null）。 */
  paraId: string | null
  dueAt: string
  completedAt: string | null
  due: boolean | null
  /** N077：揭示时刻（来源追踪）；从未揭示 → null。 */
  lastViewedAt: string | null
  /** N077：来源条目仍可达（投影存在性）；无来源 → null。 */
  sourceAvailable: boolean | null
  /** 批注项字段（卡片项 → null）。 */
  excerpt: string | null
  note: string | null
  /** 卡片项字段（批注项 → null）。 */
  concept: string | null
  explanation: string | null
}

export async function addReviewQueueItem(input: {
  kind?: 'annotation' | 'knowledge_card'
  annotationId?: string
  knowledgeCardId?: string
  dueAt: string
}): Promise<{ id: string; rescheduled: boolean }> {
  const response = await rawRequest(`${API_BASE}/review-queue`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  return (await response.json()) as { id: string; rescheduled: boolean }
}

export async function listReviewQueue(status: 'due' | 'done'): Promise<{ items: ReviewQueueItem[] }> {
  return request<{ items: ReviewQueueItem[] }>(`${API_BASE}/review-queue?status=${status}`)
}

export async function completeReviewQueueItem(id: string): Promise<void> {
  await rawRequest(`${API_BASE}/review-queue/${encodeURIComponent(id)}/complete`, { method: 'POST' })
}

export async function postponeReviewQueueItem(id: string, dueAt: string): Promise<void> {
  await rawRequest(`${API_BASE}/review-queue/${encodeURIComponent(id)}/postpone`, {
    method: 'POST',
    body: JSON.stringify({ dueAt }),
    contentType: 'application/json',
  })
}

/** N077：揭示答案 → 记录 last_viewed_at（来源追踪）。 */
export async function viewReviewQueueItem(id: string): Promise<{ id: string; lastViewedAt: string }> {
  const response = await rawRequest(`${API_BASE}/review-queue/${encodeURIComponent(id)}/view`, {
    method: 'POST',
  })
  return (await response.json()) as { id: string; lastViewedAt: string }
}

/** N071：批注原文漂移修复。 */
export interface AnnotationRepairCandidate {
  blockIndex: number
  score: number
  excerpt: string
}

export async function getAnnotationRepairCandidates(
  id: string,
): Promise<{ annotationId: string; entryRef: string; quote: string; candidates: AnnotationRepairCandidate[] }> {
  return request(
    `${API_BASE}/annotations/${encodeURIComponent(id)}/repair-candidates`,
  )
}

export async function repairAnnotation(
  id: string,
  blockIndex: number,
  quoteText: string,
): Promise<{ annotation: Annotation; blockIndex: number; score: number }> {
  const response = await rawRequest(`${API_BASE}/annotations/${encodeURIComponent(id)}/repair`, {
    method: 'POST',
    body: JSON.stringify({ blockIndex, quoteText }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { annotation: Annotation; blockIndex: number; score: number }
}

/** N073：批注颜色语义标签（label 空 = 未命名 → 诚实显示原始色名）。 */
export interface AnnotationColorLabel {
  color: string
  label: string
}

export async function getColorLabels(): Promise<{ items: AnnotationColorLabel[] }> {
  return request<{ items: AnnotationColorLabel[] }>(`${API_BASE}/annotations/color-labels`)
}

export async function putColorLabel(color: string, label: string): Promise<{ items: AnnotationColorLabel[] }> {
  const response = await rawRequest(`${API_BASE}/annotations/color-labels`, {
    method: 'PUT',
    body: JSON.stringify({ color, label }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { items: AnnotationColorLabel[] }
}

/** N074：阅读问题清单。 */
export interface ReadingQuestion {
  id: string
  question: string
  status: 'open' | 'done'
  entryRef: string | null
  annotationId: string | null
  workspaceId: string | null
  createdAt: string
  updatedAt: string
}

export async function createReadingQuestion(input: {
  question: string
  entryRef?: string | null
  annotationId?: string | null
  workspaceId?: string | null
}): Promise<ReadingQuestion> {
  const response = await rawRequest(`${API_BASE}/reading-questions`, {
    method: 'POST',
    body: JSON.stringify(input),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as ReadingQuestion
}

export async function listReadingQuestions(params: {
  status?: 'open' | 'done'
  entryRef?: string
  annotationId?: string
}): Promise<{ items: ReadingQuestion[] }> {
  const search = new URLSearchParams()
  if (params.status) search.set('status', params.status)
  if (params.entryRef) search.set('entryRef', params.entryRef)
  if (params.annotationId) search.set('annotationId', params.annotationId)
  const qs = search.toString()
  return request<{ items: ReadingQuestion[] }>(
    qs === '' ? `${API_BASE}/reading-questions` : `${API_BASE}/reading-questions?${qs}`,
  )
}

export async function patchReadingQuestion(
  id: string,
  patch: { question?: string; status?: 'open' | 'done' },
): Promise<ReadingQuestion> {
  const response = await rawRequest(
    `${API_BASE}/reading-questions/${encodeURIComponent(id)}`,
    { method: 'PATCH', body: JSON.stringify(patch), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as ReadingQuestion
}

export async function deleteReadingQuestion(id: string): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/reading-questions/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

/** F063：AI 任务中心 — 最近任务列表（默认/上限 50）。 */
export interface AiTaskRecord {
  id: string
  kind: string
  entryRef: string | null
  status: 'done' | 'failed'
  model: string
  durationMs: number
  inputChars: number | null
  errorType: string | null
  createdAt: string
}

export async function listAiTasks(limit = 50): Promise<{ items: AiTaskRecord[] }> {
  return request<{ items: AiTaskRecord[] }>(`${API_BASE}/ai/tasks?limit=${limit}`)
}

/** F063：重试任务（仅服务端可重建输入的类型；原记录不变，返回新任务）。 */
export async function retryAiTask(id: string): Promise<{ task: AiTaskRecord | null; originalId: string }> {
  const response = await rawRequest(`${API_BASE}/ai/tasks/${encodeURIComponent(id)}/retry`, {
    method: 'POST',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { task: AiTaskRecord | null; originalId: string }
}

/** F064：AI 用量限制（当前窗口已用/剩余/重置时间；本地时区口径）。 */
export interface AiQuotaUsage {
  window: '' | 'day' | 'month'
  maxCalls: number
  used: number
  remaining: number
  windowStart: string
  windowReset: string
  retryAfter: number
}

export async function getAiQuota(): Promise<AiQuotaUsage> {
  return request<AiQuotaUsage>(`${API_BASE}/settings/ai/quota`)
}

/** F065：多篇共同问答（上下文仅所选条目；citations 为 refs 子集）。 */
export interface AskBatchResult {
  answer: string
  citations: { index: number; entryRef: string }[]
  skipped: { entryRef: string; reason: string }[]
}

export async function askBatchEntries(body: {
  entryRefs: string[]
  question: string
  maxCharsPerEntry?: number
}): Promise<AskBatchResult> {
  const response = await rawRequest(`${API_BASE}/entries/ask-batch`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as AskBatchResult
}

/** F067：多文观点对照（模型 JSON 结构服务端校验；quote 核验标注）。 */
export interface CompareResult {
  commonPoints: string[]
  differences: { topic: string; positions: { entry: number; claim: string }[] }[]
  evidence: { entry: number; quote: string; verified: boolean }[]
  uncertainties: string[]
  materials: { index: number; entryRef: string; title: string }[]
  skipped: { entryRef: string; reason: string }[]
}

export async function compareEntries(body: { entryRefs: string[] }): Promise<CompareResult> {
  const response = await rawRequest(`${API_BASE}/entries/compare`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as CompareResult
}

/** F069：文章自测（生成响应只含题目，绝不含答案）。 */
export interface QuizSession {
  quizId: string
  entryRef: string
  questions: { index: number; question: string; options: string[] }[]
}

export async function generateQuiz(entryRef: string, count: number): Promise<QuizSession> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/quiz`,
    { method: 'POST', body: JSON.stringify({ count }), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as QuizSession
}

/** F069：评分（服务端只读答案表）。 */
export interface QuizGradeResult {
  quizId: string
  items: {
    index: number
    chosen: number | null
    correct: boolean
    answerIndex: number
    explanation: string
    evidenceQuote: string
  }[]
}

export async function gradeQuiz(quizId: string, answers: (number | null)[]): Promise<QuizGradeResult> {
  const response = await rawRequest(`${API_BASE}/quiz/${encodeURIComponent(quizId)}/grade`, {
    method: 'POST',
    body: JSON.stringify({ answers }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as QuizGradeResult
}

/** F070：知识卡片（预览候选 / 幂等保存 / 检索 / 删除）。 */
export interface KnowledgeCard {
  id: string
  entryRef: string
  concept: string
  explanation: string
  sourceQuote: string
  quoteVerified: boolean
  createdAt: string
  entryTitle: string | null
  stale: boolean
}

export async function previewKnowledgeCards(
  entryRef: string,
  max: number,
): Promise<{ entryRef: string; cards: { concept: string; explanation: string; sourceQuote: string; verified: boolean }[] }> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/knowledge-cards/preview`,
    { method: 'POST', body: JSON.stringify({ max }), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { entryRef: string; cards: { concept: string; explanation: string; sourceQuote: string; verified: boolean }[] }
}

export async function saveKnowledgeCards(
  entryRef: string,
  cards: { concept: string; explanation: string; sourceQuote: string }[],
): Promise<{ results: { concept: string; status: 'created' | 'skipped' | 'error'; reason?: string | null; cardId?: string | null }[] }> {
  const response = await rawRequest(
    `${API_BASE}/entries/${encodeURIComponent(entryRef)}/knowledge-cards/save`,
    { method: 'POST', body: JSON.stringify({ cards }), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { results: { concept: string; status: 'created' | 'skipped' | 'error'; reason?: string | null; cardId?: string | null }[] }
}

export async function listKnowledgeCards(q?: string): Promise<{ items: KnowledgeCard[] }> {
  // ? 号内联在字面量里：契约测试按 `?` 截断路径，变量携带的查询串
  // 会被折叠成形状错误的多余参数段。
  const path =
    q && q.trim() !== ''
      ? `${API_BASE}/knowledge-cards?q=${encodeURIComponent(q.trim())}`
      : `${API_BASE}/knowledge-cards`
  return request<{ items: KnowledgeCard[] }>(path)
}

export async function deleteKnowledgeCard(id: string): Promise<void> {
  const response = await rawRequest(`${API_BASE}/knowledge-cards/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw await toApiError(response)
}

/** F071：疑似重复审核（扫描/队列/确认/忽略/白名单）。 */
export interface DuplicatePair {
  id: string
  aRef: string
  bRef: string
  reason: string
  status: 'pending' | 'confirmed' | 'ignored' | 'whitelisted'
  createdAt: string
  aTitle: string | null
  bTitle: string | null
  aUrl: string | null
  bUrl: string | null
}

export async function scanDuplicates(): Promise<{ scanned: number; created: number; pending: number }> {
  const response = await rawRequest(`${API_BASE}/library/duplicates/scan`, { method: 'POST' })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { scanned: number; created: number; pending: number }
}

export async function listDuplicates(status = 'pending'): Promise<{ items: DuplicatePair[] }> {
  return request<{ items: DuplicatePair[] }>(`${API_BASE}/library/duplicates?status=${status}`)
}

export async function duplicateAction(id: string, action: 'confirm' | 'ignore' | 'whitelist'): Promise<DuplicatePair> {
  // action 必须内联为字面量后缀：api 契约测试按路径形状比对
  // （/duplicates/{}/confirm 形状），变量拼接会被视作多余参数段。
  const path =
    action === 'confirm'
      ? `${API_BASE}/library/duplicates/${encodeURIComponent(id)}/confirm`
      : action === 'ignore'
        ? `${API_BASE}/library/duplicates/${encodeURIComponent(id)}/ignore`
        : `${API_BASE}/library/duplicates/${encodeURIComponent(id)}/whitelist`
  const response = await rawRequest(path, { method: 'POST' })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as DuplicatePair
}

/** F073：引用清单导出（返回文件内容与诚实标注头）。 */
export interface SearchExportResult {
  content: string
  total: number
  truncated: boolean
  contentType: string
}

export async function exportSearchList(body: {
  q: string
  format: 'csv' | 'markdown'
  includeExcerpt?: boolean
  cap?: number
}): Promise<SearchExportResult> {
  const response = await rawRequest(`${API_BASE}/search/export`, {
    method: 'POST',
    body: JSON.stringify({
      q: body.q,
      format: body.format,
      fields: body.includeExcerpt
        ? ['title', 'source', 'date', 'url', 'excerpt']
        : ['title', 'source', 'date', 'url'],
    }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return {
    content: await response.text(),
    total: Number(response.headers.get('x-lumi-total') ?? '0'),
    truncated: response.headers.get('x-lumi-truncated') === '1',
    contentType: response.headers.get('content-type') ?? 'text/plain',
  }
}

/** F075：两视图对照（纯读取；common/onlyA/onlyB refs ≤200 + 完整计数）。 */
export interface ViewCompareResult {
  common: string[]
  onlyA: string[]
  onlyB: string[]
  counts: { a: number; b: number; common: number; onlyA: number; onlyB: number }
  complete: boolean
}

export async function compareSavedViews(aId: string, bId: string): Promise<ViewCompareResult> {
  const response = await rawRequest(`${API_BASE}/search/views/compare`, {
    method: 'POST',
    body: JSON.stringify({ aId, bId }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as ViewCompareResult
}

/** F076：图谱命名视图（layout ≤200 节点位置；同名覆盖需 overwrite）。 */
export interface GraphViewPayload {
  id: string
  name: string
  layout: Record<string, { x: number; y: number }>
  filters: Record<string, unknown>
  focusNode: string | null
  createdAt: string
  updatedAt: string
}

export async function listGraphViews(): Promise<{ items: GraphViewPayload[] }> {
  return request<{ items: GraphViewPayload[] }>(`${API_BASE}/graph/views`)
}

export async function saveGraphView(body: {
  name: string
  layout?: Record<string, { x: number; y: number }>
  filters?: Record<string, unknown>
  focusNode?: string | null
  overwrite?: boolean
}): Promise<GraphViewPayload> {
  const response = await rawRequest(`${API_BASE}/graph/views`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as GraphViewPayload
}

export async function deleteGraphView(id: string): Promise<void> {
  const response = await rawRequest(`${API_BASE}/graph/views/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw await toApiError(response)
}

/** F077：关系路径查找（BFS 于派生图；paths ≤5）。 */
export interface GraphPathResult {
  paths: { nodes: { ref: string; label: string; kind: string }[]; edgeKinds: string[] }[]
  reachable: boolean
}

export async function findGraphPath(body: {
  srcRef: string
  dstRef: string
  maxDepth?: number
}): Promise<GraphPathResult> {
  const response = await rawRequest(`${API_BASE}/graph/path`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as GraphPathResult
}

/** F078：检索同义词（单层扩展；expansions ≤8×50）。 */
export interface SearchSynonym {
  id: string
  term: string
  expansions: string[]
  enabled: boolean
}

export async function listSynonyms(): Promise<{ items: SearchSynonym[] }> {
  return request<{ items: SearchSynonym[] }>(`${API_BASE}/search/synonyms`)
}

export async function createSynonym(term: string, expansions: string[]): Promise<SearchSynonym> {
  const response = await rawRequest(`${API_BASE}/search/synonyms`, {
    method: 'POST',
    body: JSON.stringify({ term, expansions }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as SearchSynonym
}

export async function deleteSynonym(id: string): Promise<void> {
  const response = await rawRequest(`${API_BASE}/search/synonyms/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw await toApiError(response)
}

export async function previewSynonyms(q: string): Promise<{ matched: { term: string; expansions: string[] }[]; effectiveTerms: string[] }> {
  const response = await rawRequest(`${API_BASE}/search/synonyms/preview`, {
    method: 'POST',
    body: JSON.stringify({ q }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { matched: { term: string; expansions: string[] }[]; effectiveTerms: string[] }
}

/** F080：Obsidian 反链/断链。 */
export async function listNoteBacklinks(uuid: string): Promise<{ items: { fromUuid: string; title: string; alias: string | null }[] }> {
  return request<{ items: { fromUuid: string; title: string; alias: string | null }[] }>(
    `${API_BASE}/obsidian/notes/${encodeURIComponent(uuid)}/backlinks`,
  )
}

export async function listNoteBrokenLinks(uuid: string): Promise<{ items: { raw: string; reason: string }[] }> {
  return request<{ items: { raw: string; reason: string }[] }>(
    `${API_BASE}/obsidian/notes/${encodeURIComponent(uuid)}/broken-links`,
  )
}

// ===========================================================================
// W5：F081–F100（批量编辑 / 合并 / 模板 / 归档 / 看板 / 目标 / 失效检查 /
// 资料包 ZIP / 剪藏修订 / 笔记生命周期 / RAG 排除·作业·一致性 /
// Agent 范围·权限·搜索·导出·预演·分支）。E04 起 Agent W5 与 RAG 端点
// 的响应均已入 generated schema（AgentThreadSettings /
// AgentThreadSearchHit / AgentBranchResult / AgentApprovalPreview /
// RagRebuildPauseResult 等）；本地 interface 为收窄视图，逐步替换中。
// ===========================================================================

// ---- F081 批量元数据编辑 ---------------------------------------------------

/** patch 字段缺省（undefined）= 未勾选，保持原值。 */
export interface BatchEditPatch {
  titleSuffix?: string
  tagsAdd?: string[]
  tagsRemove?: string[]
  workspaceId?: string
}

export interface BatchEditItemState {
  title: string
  tags: string[]
  workspaceIds: string[]
}

export interface BatchEditPreviewItem {
  ref: string
  before: BatchEditItemState
  after: BatchEditItemState
}

export interface BatchEditApplyItem {
  ref: string
  ok: boolean
  error?: string | null
}

export async function previewBatchEdit(
  refs: string[],
  patch: BatchEditPatch,
): Promise<{ items: BatchEditPreviewItem[] }> {
  const response = await rawRequest(`${API_BASE}/library/batch-edit/preview`, {
    method: 'POST',
    body: JSON.stringify({ refs, patch }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { items: BatchEditPreviewItem[] }
}

export async function applyBatchEdit(
  refs: string[],
  patch: BatchEditPatch,
): Promise<{ items: BatchEditApplyItem[]; applied: number; failed: number }> {
  const response = await rawRequest(`${API_BASE}/library/batch-edit`, {
    method: 'POST',
    body: JSON.stringify({ refs, patch }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as {
    items: BatchEditApplyItem[]
    applied: number
    failed: number
  }
}

// ---- F082 重复资料合并 -----------------------------------------------------

export interface MergeFieldCompare {
  field: string
  primary: unknown
  duplicate: unknown
}

export interface MergePreview {
  primaryRef: string
  duplicateRef: string
  fields: MergeFieldCompare[]
  annotationCount: number
  assetUuids: string[]
}

export interface MergeResult {
  mergedRef: string
  removedRef: string
  tagsUnion: string[]
  movedAnnotations: number
  trashed: boolean
}

export async function previewMerge(
  primaryRef: string,
  duplicateRef: string,
): Promise<MergePreview> {
  const response = await rawRequest(`${API_BASE}/library/merge/preview`, {
    method: 'POST',
    body: JSON.stringify({ primaryRef, duplicateRef }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as MergePreview
}

export async function applyMerge(
  primaryRef: string,
  duplicateRef: string,
  policy: { title: 'primary' | 'duplicate'; note: 'primary' | 'append' },
): Promise<MergeResult> {
  const response = await rawRequest(`${API_BASE}/library/merge`, {
    method: 'POST',
    body: JSON.stringify({ primaryRef, duplicateRef, policy }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as MergeResult
}

// ---- F083 工作区模板 -------------------------------------------------------

export interface WorkspaceTemplateView {
  id: string
  name: string
  config: Record<string, unknown>
  createdAt: string
}

export async function saveWorkspaceAsTemplate(
  workspaceId: string,
  name: string,
): Promise<WorkspaceTemplateView> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/save-as-template`,
    { method: 'POST', body: JSON.stringify({ name }), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as WorkspaceTemplateView
}

export async function createWorkspaceFromTemplate(body: {
  templateId: string
  name: string
  includeExampleItems: boolean
  exampleRefs?: string[]
}): Promise<{ workspace: Workspace; addedExampleRefs: string[]; skippedExampleRefs: string[] }> {
  const response = await rawRequest(`${API_BASE}/workspaces/from-template`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as {
    workspace: Workspace
    addedExampleRefs: string[]
    skippedExampleRefs: string[]
  }
}

export async function listWorkspaceTemplates(): Promise<{ items: WorkspaceTemplateView[] }> {
  return request<{ items: WorkspaceTemplateView[] }>(`${API_BASE}/workspace-templates`)
}

export async function deleteWorkspaceTemplate(templateId: string): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/workspace-templates/${encodeURIComponent(templateId)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

// ---- F084 工作区归档 -------------------------------------------------------

export async function patchWorkspaceArchive(
  workspaceId: string,
  archived: boolean,
): Promise<Workspace> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/archive`,
    { method: 'PATCH', body: JSON.stringify({ archived }), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as Workspace
}

export async function listArchivedWorkspaces(): Promise<Workspace[]> {
  return request<Workspace[]>(`${API_BASE}/workspace-archive`)
}

// ---- F085 看板 / F086 目标 --------------------------------------------------

/** N112：三状态扩展为五状态（待处理/阅读中/待摘录/待验证/已完成）。 */
export type BoardStatus = 'todo' | 'reading' | 'excerpted' | 'needs_verification' | 'done'

export interface BoardCard {
  itemRef: string
  status: BoardStatus
  updatedAt: string
}

export interface BoardColumnView {
  status: BoardStatus
  items: BoardCard[]
  total: number
}

export async function getWorkspaceBoard(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<{ workspaceId: string; columns: BoardColumnView[] }> {
  return request(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/board`,
    signal,
  )
}

export async function setBoardStatus(
  workspaceId: string,
  itemRef: string,
  status: BoardStatus,
): Promise<{ itemRef: string; status: BoardStatus; updatedAt: string }> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/board`,
    {
      method: 'PUT',
      body: JSON.stringify({ itemRef, status }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { itemRef: string; status: BoardStatus; updatedAt: string }
}

export interface WorkspaceGoalView {
  exists?: boolean
  workspaceId?: string
  targetCount?: number
  deadline?: string | null
  doneCount?: number
  createdAt?: string
  goalText?: string | null
  conditions?: string[]
}

export async function getWorkspaceGoal(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<WorkspaceGoalView> {
  return request(`${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/goal`, signal)
}

export async function putWorkspaceGoal(
  workspaceId: string,
  targetCount: number,
  deadline?: string | null,
  extra?: { goalText?: string | null; conditions?: string[] | null },
): Promise<WorkspaceGoalView> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/goal`,
    {
      method: 'PUT',
      body: JSON.stringify({
        targetCount,
        deadline: deadline ?? null,
        ...(extra?.goalText !== undefined ? { goalText: extra.goalText } : {}),
        ...(extra?.conditions !== undefined ? { conditions: extra.conditions } : {}),
      }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as WorkspaceGoalView
}

export async function deleteWorkspaceGoal(workspaceId: string): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/goal`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

// ---- N113 分节大纲 -----------------------------------------------------------

/** 分节成员（unresolved = 引用的条目已不在工作区，诚实标记）。 */
export interface WorkspaceSectionItem {
  itemRef: string
  position: number
  addedAt: string
  unresolved: boolean
}

export interface WorkspaceSectionView {
  id: string
  workspaceId: string
  title: string
  sortIndex: number
  createdAt: string
  items: WorkspaceSectionItem[]
}

export async function listWorkspaceSections(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<{ items: WorkspaceSectionView[] }> {
  return request(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/sections`,
    signal,
  )
}

export async function createWorkspaceSection(
  workspaceId: string,
  title: string,
): Promise<WorkspaceSectionView> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/sections`,
    { method: 'POST', body: JSON.stringify({ title }), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as WorkspaceSectionView
}

export async function renameWorkspaceSection(
  workspaceId: string,
  sectionId: string,
  title: string,
): Promise<WorkspaceSectionView> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/sections/${encodeURIComponent(sectionId)}`,
    { method: 'PATCH', body: JSON.stringify({ title }), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as WorkspaceSectionView
}

export async function deleteWorkspaceSection(
  workspaceId: string,
  sectionId: string,
): Promise<void> {
  await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/sections/${encodeURIComponent(sectionId)}`,
    { method: 'DELETE' },
  )
}

/** 分节顺序持久化（PUT 全量；真实变化 bump revision）。 */
export async function reorderWorkspaceSections(
  workspaceId: string,
  sectionIds: string[],
): Promise<{ items: WorkspaceSectionView[] }> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/sections/order`,
    {
      method: 'PUT',
      body: JSON.stringify({ sectionIds }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { items: WorkspaceSectionView[] }
}

/** 条目引用进分节（幂等；同一 ref 可进多节；非成员 404）。 */
export async function addWorkspaceSectionItem(
  workspaceId: string,
  sectionId: string,
  itemRef: string,
): Promise<WorkspaceSectionItem> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/sections/${encodeURIComponent(sectionId)}/items`,
    { method: 'POST', body: JSON.stringify({ itemRef }), contentType: 'application/json' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as WorkspaceSectionItem
}

/** 从分节移除引用（只拆引用，不动工作区成员本身）。 */
export async function removeWorkspaceSectionItem(
  workspaceId: string,
  sectionId: string,
  itemRef: string,
): Promise<void> {
  await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/sections/${encodeURIComponent(sectionId)}/items/${encodeURIComponent(itemRef)}`,
    { method: 'DELETE' },
  )
}

/** 节内条目顺序持久化（PUT 全量 1..N）。 */
export async function reorderWorkspaceSectionItems(
  workspaceId: string,
  sectionId: string,
  itemRefs: string[],
): Promise<{ items: WorkspaceSectionView[] }> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/sections/${encodeURIComponent(sectionId)}/items/order`,
    {
      method: 'PUT',
      body: JSON.stringify({ itemRefs }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { items: WorkspaceSectionView[] }
}

// ---- N114 汇编预览 -----------------------------------------------------------

export interface CompileItem {
  itemRef: string
  title: string
  excerpt: string
  citation: string
  note?: string | null
}

export interface CompileSection {
  sectionId: string | null
  title: string
  items: CompileItem[]
}

export interface CompileDraft {
  workspaceId: string
  workspaceName: string
  generatedAt: string
  sections: CompileSection[]
  includedCount: number
  excludedMissing: number
  excluded: { itemRef: string; reason: string }[]
}

/** 汇编草稿（纯预览不落库；sectionIds 缺省 = 全部大纲分节）。 */
export async function compileWorkspace(
  workspaceId: string,
  sectionIds?: string[],
): Promise<CompileDraft> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/compile`,
    {
      method: 'POST',
      body: JSON.stringify({ sectionIds: sectionIds ?? null }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as CompileDraft
}

/** 汇编草稿 Markdown 文本版（同样纯预览；供下载）。 */
export async function compileWorkspaceMarkdown(
  workspaceId: string,
  sectionIds?: string[],
): Promise<string> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/compile/markdown`,
    {
      method: 'POST',
      body: JSON.stringify({ sectionIds: sectionIds ?? null }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return await response.text()
}

// ---- N120 清理预演 -----------------------------------------------------------

export interface WorkspaceCleanupCategory {
  category: string
  items: Record<string, unknown>[]
}

export interface WorkspaceCleanupPreview {
  workspaceId: string
  categories: WorkspaceCleanupCategory[]
  actionable: string[]
  reportOnly: string[]
}

export const CLEANUP_CATEGORY_LABELS: Record<string, string> = {
  unresolved_refs: '已消失的来源条目',
  protected_library_refs: '受保护的库引用（不参与清理）',
  unverifiable_refs: '无法核实（不参与清理）',
  empty_groups: '空分组',
  orphan_section_refs: '悬空的分节引用',
  pinned_group_conflicts: '固定 + 分组冲突（仅提示）',
}

export async function getWorkspaceCleanupPreview(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<WorkspaceCleanupPreview> {
  return request(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/cleanup-preview`,
    signal,
  )
}

export interface CleanupApplyResult {
  logId: string
  removed: Record<string, number>
}

/** 应用选中的可执行类目（快照先行；只删 Lumi 元数据行）。 */
export async function applyWorkspaceCleanup(
  workspaceId: string,
  categories: string[],
): Promise<CleanupApplyResult> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/cleanup`,
    {
      method: 'POST',
      body: JSON.stringify({ categories }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as CleanupApplyResult
}

export interface CleanupUndoResult {
  logId: string
  restoredRefs: number
  restoredSectionRefs: number
}

/** 撤销最近一次（或指定日志的）清理（重复 undo 幂等）。 */
export async function undoWorkspaceCleanup(
  workspaceId: string,
  logId?: string | null,
): Promise<CleanupUndoResult> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/cleanup/undo`,
    {
      method: 'POST',
      body: JSON.stringify({ logId: logId ?? null }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as CleanupUndoResult
}

// ---- F087 书签失效检查 -------------------------------------------------------

export type BookmarkLinkStatus =
  | 'ok'
  | 'redirect'
  | 'not_found'
  | 'auth_required'
  | 'rate_limited'
  | 'timeout'
  | 'network_error'
  | 'blocked_ssrf'

export interface BookmarkCheckItem {
  ref: string
  status: BookmarkLinkStatus
  httpStatus?: number | null
  finalUrl?: string | null
  checkedAt: string
  error?: string | null
}

export async function checkBookmarkLinks(
  refs: string[],
): Promise<{ items: BookmarkCheckItem[] }> {
  const response = await rawRequest(`${API_BASE}/library/bookmarks/check-links`, {
    method: 'POST',
    body: JSON.stringify({ refs }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { items: BookmarkCheckItem[] }
}

// ---- F088 资料包导出增强（ZIP） ----------------------------------------------

export interface ResearchPackPreviewW5 {
  entryCount: number
  missingCount: number
  estBytes: number
  snapshots: { uuid: string; title: string; bytes: number }[]
}

export async function previewResearchPackW5(
  workspaceId: string,
  includeSnapshots: string[],
): Promise<ResearchPackPreviewW5> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/research-pack/preview`,
    {
      method: 'POST',
      body: JSON.stringify({ includeSnapshots }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as ResearchPackPreviewW5
}

/** ZIP 导出：POST 返回二进制附件（由调用方触发下载；错误时仍可能是 JSON）。 */
export async function exportResearchPackZip(
  workspaceId: string,
  includeSnapshots: string[],
): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/research-pack`,
    {
      method: 'POST',
      body: JSON.stringify({ format: 'zip', includeSnapshots }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `research-pack-${workspaceId}.zip`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}

// ---- F089 剪藏手工修订 -------------------------------------------------------

export interface ClipRevisionPayload {
  revisedAt: string
  note: string | null
  baseContentHash: string | null
}

export interface ClipDetailW5 {
  ref: string
  url: string
  title: string
  byline: string | null
  fetchedAt: string
  createdAt: string
  original: Record<string, unknown>
  revised: ClipRevisionPayload | null
  content: Record<string, unknown>
}

export async function saveClipRevision(
  uuid: string,
  body: { blocks: string[]; note?: string | null; force?: boolean; baseContentHash?: string | null },
): Promise<ClipDetailW5> {
  const response = await rawRequest(
    `${API_BASE}/library/clips/${encodeURIComponent(uuid)}/revision`,
    {
      method: 'PATCH',
      body: JSON.stringify(body),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as ClipDetailW5
}

export async function discardClipRevision(uuid: string): Promise<void> {
  const response = await rawRequest(
    `${API_BASE}/library/clips/${encodeURIComponent(uuid)}/revision`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw await toApiError(response)
}

/** F089 块清单（修订 UI 的勾选来源；id 形如 b1/b2…）。 */
export async function getClipBlocks(
  uuid: string,
  signal?: AbortSignal,
): Promise<{ blocks: { id: string; text: string }[] }> {
  return request(`${API_BASE}/library/clips/${encodeURIComponent(uuid)}/revision`, signal)
}

// ---- F090 Lumi 笔记全生命周期 ------------------------------------------------
// 列表沿用 F020 的 listLumiNotes（workspaceId 过滤版）；这里补全
// 详情 / 创建 / 编辑（乐观锁）/ 软删四个生命周期端点。

export interface LumiNoteDetail {
  uuid: string
  title: string
  contentMd: string
  workspaceId: string | null
  createdAt: string
  updatedAt: string
}

export async function getLumiNote(uuid: string, signal?: AbortSignal): Promise<LumiNoteDetail> {
  return request(`${API_BASE}/library/notes/${encodeURIComponent(uuid)}`, signal)
}

export async function createLumiNote(body: {
  title: string
  contentMd: string
  workspaceId?: string | null
}): Promise<LumiNoteDetail> {
  const response = await rawRequest(`${API_BASE}/library/notes`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as LumiNoteDetail
}

export async function updateLumiNote(
  uuid: string,
  body: { title?: string; contentMd?: string; baseUpdatedAt?: string },
): Promise<LumiNoteDetail> {
  const response = await rawRequest(
    `${API_BASE}/library/notes/${encodeURIComponent(uuid)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(body),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as LumiNoteDetail
}

export async function deleteLumiNote(uuid: string): Promise<void> {
  const response = await rawRequest(`${API_BASE}/library/notes/${encodeURIComponent(uuid)}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw await toApiError(response)
}

// ---- F091 RAG 索引排除 / F093 作业 / F100 一致性 ------------------------------

export interface RagExclusionItem {
  feedUrl: string
  ragExcluded: boolean
  aiDisabled: boolean
  affectedChunks: number
}

export async function listRagExclusions(signal?: AbortSignal): Promise<{ items: RagExclusionItem[] }> {
  return request(`${API_BASE}/rag/exclusions`, signal)
}

export async function setRagExclusion(
  feedRef: string,
  excluded: boolean,
): Promise<{ items: RagExclusionItem[] }> {
  const response = await rawRequest(`${API_BASE}/rag/exclusions`, {
    method: 'PUT',
    body: JSON.stringify({ feedRef, excluded }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { items: RagExclusionItem[] }
}

export async function pauseRagRebuild(): Promise<{ paused: boolean; jobId: string | null; status?: string }> {
  const response = await rawRequest(`${API_BASE}/rag/rebuild/pause`, { method: 'POST' })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { paused: boolean; jobId: string | null; status?: string }
}

export async function resumeRagRebuild(): Promise<{
  chunks: number
  elapsedMs: number
  jobId?: string | null
  status?: string | null
}> {
  const response = await rawRequest(`${API_BASE}/rag/rebuild/resume`, { method: 'POST' })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as {
    chunks: number
    elapsedMs: number
    jobId?: string | null
    status?: string | null
  }
}

export interface RagInconsistencyItem {
  ref: string
  storedHash: string | null
  currentHash: string | null
  basis: 'content_hash' | 'embedding_model'
}

export async function listRagInconsistencies(): Promise<{
  modelId: string
  items: RagInconsistencyItem[]
}> {
  return request(`${API_BASE}/rag/inconsistencies`)
}

/** F092 试检索：GET /rag/search（q + k；score 缺失时 UI 显示「—」绝不编造）。 */
export async function ragTrySearch(
  q: string,
  k = 6,
  signal?: AbortSignal,
): Promise<{ items: { ref: string; kind: string; text: string; score?: number | null; title?: string | null; modelId?: string | null }[]; semanticUsed: boolean; semanticError: string | null }> {
  const query = new URLSearchParams({ q, k: String(k) })
  return request(`${API_BASE}/rag/search?${query.toString()}`, signal)
}

export async function repairRagRefs(
  refs: string[],
): Promise<{ repaired: string[]; failed: { ref: string; error: string }[] }> {
  const response = await rawRequest(`${API_BASE}/rag/repair`, {
    method: 'POST',
    body: JSON.stringify({ refs }),
    contentType: 'application/json',
  })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as { repaired: string[]; failed: { ref: string; error: string }[] }
}

// ---- F094/F095/F096/F097/F098/F099 Agent 会话 --------------------------------

/** F094/F098 会话设置（下轮生效；scope=null + clearScope 显式清除）。 */
export interface AgentThreadSettingsPatch {
  title?: string
  scope?: { workspaceId?: string; entryRefs?: string[] } | null
  clearScope?: boolean
  toolPolicy?: {
    mode: 'all' | 'readonly'
    allowedTools?: string[]
    maxOpsPerTurn?: number
  } | null
  clearToolPolicy?: boolean
}

export async function updateAgentThreadSettings(
  threadId: string,
  patch: AgentThreadSettingsPatch,
): Promise<{ id: string; title: string; scope: unknown; toolPolicy: unknown; branchOf: string | null }> {
  const response = await rawRequest(
    `${API_BASE}/agent/threads/${encodeURIComponent(threadId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(patch),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as {
    id: string
    title: string
    scope: unknown
    toolPolicy: unknown
    branchOf: string | null
  }
}

export interface AgentThreadSearchHit {
  threadId: string
  threadTitle: string
  messageIndex: number
  role: string
  snippet: string
}

export async function searchAgentThreads(
  q: string,
  signal?: AbortSignal,
): Promise<{ items: AgentThreadSearchHit[]; truncated: boolean }> {
  const query = new URLSearchParams({ q })
  return request(`${API_BASE}/agent/threads/search?${query.toString()}`, signal)
}

/** F096 导出：返回 markdown 文本（调用方触发下载）。 */
export async function exportAgentThreadMarkdown(
  threadId: string,
  rounds: number,
): Promise<string> {
  const response = await rawRequest(
    `${API_BASE}/agent/threads/${encodeURIComponent(threadId)}/export?rounds=${rounds}&format=md`,
    { method: 'GET' },
  )
  if (!response.ok) throw await toApiError(response)
  return await response.text()
}

export interface ApprovalPreviewChange {
  field: string
  from: unknown
  to: unknown
}

export interface ApprovalPreview {
  approvalId: string
  tool: string
  target: unknown
  changes: ApprovalPreviewChange[]
  uncertain: unknown[]
}

export async function previewAgentApproval(
  threadId: string,
  approvalId: string,
): Promise<ApprovalPreview> {
  const response = await rawRequest(
    `${API_BASE}/agent/threads/${encodeURIComponent(threadId)}/approvals/${encodeURIComponent(approvalId)}/preview`,
    { method: 'POST' },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as ApprovalPreview
}

export async function branchAgentThread(
  threadId: string,
  messageIndex: number,
): Promise<{ thread: AgentThread; branchOf: string; copiedMessages: number; truncated: boolean }> {
  const response = await rawRequest(
    `${API_BASE}/agent/threads/${encodeURIComponent(threadId)}/branch`,
    {
      method: 'POST',
      body: JSON.stringify({ messageIndex }),
      contentType: 'application/json',
    },
  )
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as {
    thread: AgentThread
    branchOf: string
    copiedMessages: number
    truncated: boolean
  }
}

// ---- W6：F101–F115（素材池 / 轮换 / 邮件工具 / 收件箱事件 / 保留 / 比较） ----

/** F102：素材池条目（usedIssueKey 非空 = 已被某期刊消费）。 */
export interface DigestPoolEntry {
  id: number
  entryRef: string
  addedAt: string
  position: number
  usedIssueKey: string | null
}

/** GET …/pool：items = 待用（按 position 升序），used = 已消费。 */
export interface DigestPoolList {
  items: DigestPoolEntry[]
  used?: DigestPoolEntry[]
}

/** F102：素材池列表（待用 + 已消费分列）。 */
export async function listDigestPool(
  configId: number,
  signal?: AbortSignal,
): Promise<DigestPoolList> {
  return request<DigestPoolList>(
    `${API_BASE}/gpt-digest/configs/${configId}/pool`,
    signal,
  )
}

/** F102：加入素材池。409 duplicate / 422 ai_disabled_source 由调用方处理。 */
export async function addDigestPoolEntry(
  configId: number,
  entryRef: string,
): Promise<DigestPoolEntry> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/configs/${configId}/pool`, {
    method: 'POST',
    body: JSON.stringify({ entryRef }),
    contentType: 'application/json',
  })
  return (await response.json()) as DigestPoolEntry
}

/** F102：移出素材池（不存在 → 404 ApiError）。 */
export async function removeDigestPoolEntry(
  configId: number,
  entryId: number,
): Promise<void> {
  await rawRequest(`${API_BASE}/gpt-digest/configs/${configId}/pool/${entryId}`, {
    method: 'DELETE',
  })
}

/** F102：全量提交排序后的 id 顺序。 */
export async function reorderDigestPool(
  configId: number,
  orderedIds: number[],
): Promise<DigestPoolList> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/configs/${configId}/pool`, {
    method: 'PATCH',
    body: JSON.stringify({ orderedIds }),
    contentType: 'application/json',
  })
  return (await response.json()) as DigestPoolList
}

/** F103：轮换 dry-run 影响报告（零变更；无记录 → null 诚实未知）。 */
export interface FeedRotateImpact {
  tokenExists: boolean
  tokenRotatedAt: string | null
  ageDays: number | null
  note: string
}

/** F103：订阅 token 轮换影响预览（dryRun=true，服务端零写入）。 */
export async function rotateGptDigestFeedDryRun(): Promise<{
  dryRun: boolean
  impact: FeedRotateImpact
}> {
  const response = await rawRequest(`${API_BASE}/gpt-digest/feed/rotate?dryRun=true`, {
    method: 'POST',
  })
  return (await response.json()) as { dryRun: boolean; impact: FeedRotateImpact }
}

/** F104：单封邮件解析对照（structure 快照 + 统计；零写入）。 */
export interface MailParseDebug {
  messageId: string
  structure: Record<string, unknown> | null
  attachmentMeta: { filename: string; bytes: number }[]
  subjectPresent: boolean
  fromDisplay: string
  textLen: number
  htmlPartPresent: boolean
  itemTitle: string
  itemDiffSummary: {
    titleMatches: boolean
    bodyChars: number
    trackingPixelsBlocked: number
  }
}

export async function getMailParseDebug(
  listUuid: string,
  messageId: string,
  signal?: AbortSignal,
): Promise<MailParseDebug> {
  return request<MailParseDebug>(
    `${API_BASE}/mail/lists/${encodeURIComponent(listUuid)}/messages/${encodeURIComponent(messageId)}/parse-debug`,
    signal,
  )
}

/** F110：会话链（祖先 → 本封 → 子孙；current 标当前查看的邮件）。 */
export interface MailThread {
  chain: { id: string; subject: string; date: string; current: boolean }[]
  reason: string | null
  cycleBroken: boolean
}

export async function getMailThread(
  listUuid: string,
  messageId: string,
  signal?: AbortSignal,
): Promise<MailThread> {
  return request<MailThread>(
    `${API_BASE}/mail/lists/${encodeURIComponent(listUuid)}/messages/${encodeURIComponent(messageId)}/thread`,
    signal,
  )
}

/** F105：邮件接收规则（scope=list）。 */
export interface MailRule {
  id: number
  listUuid: string
  priority: number
  field: string
  op: string
  value: string
  action: string
  enabled: boolean
}

export interface MailRuleList {
  items: MailRule[]
}

export async function listMailRules(
  listUuid: string,
  signal?: AbortSignal,
): Promise<MailRuleList> {
  return request<MailRuleList>(
    `${API_BASE}/mail/lists/${encodeURIComponent(listUuid)}/rules`,
    signal,
  )
}

export interface MailRuleCreateInput {
  field: 'from' | 'subject'
  op: 'contains' | 'equals'
  value: string
  action: 'allow' | 'deny'
  enabled?: boolean
}

export async function createMailRule(
  listUuid: string,
  input: MailRuleCreateInput,
): Promise<MailRule> {
  const response = await rawRequest(
    `${API_BASE}/mail/lists/${encodeURIComponent(listUuid)}/rules`,
    {
      method: 'POST',
      body: JSON.stringify(input),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as MailRule
}

export async function patchMailRule(
  ruleId: number,
  patch: { enabled?: boolean; value?: string; action?: string },
): Promise<MailRule> {
  const response = await rawRequest(`${API_BASE}/mail/rules/${ruleId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
    contentType: 'application/json',
  })
  return (await response.json()) as MailRule
}

export async function moveMailRule(ruleId: number, direction: 'up' | 'down'): Promise<MailRule> {
  const response = await rawRequest(
    `${API_BASE}/mail/rules/${ruleId}/move?direction=${direction}`,
    { method: 'POST' },
  )
  return (await response.json()) as MailRule
}

export async function deleteMailRule(ruleId: number): Promise<void> {
  await rawRequest(`${API_BASE}/mail/rules/${ruleId}`, { method: 'DELETE' })
}

/** F105：样本试跑（纯读）：field/value → 首条命中规则或「无规则 = 允许」。 */
export interface MailRuleDryRunResult {
  matchedRule: MailRule | null
  explanation: string
}

export async function dryRunMailRule(
  listUuid: string,
  sample: { field: 'from' | 'subject'; value: string },
): Promise<MailRuleDryRunResult> {
  const response = await rawRequest(
    `${API_BASE}/mail/lists/${encodeURIComponent(listUuid)}/rules/dry-run`,
    {
      method: 'POST',
      body: JSON.stringify(sample),
      contentType: 'application/json',
    },
  )
  return (await response.json()) as MailRuleDryRunResult
}

/** F106：历史回填结果（dryRun → sample/matched；执行 → processed/created/…）。 */
export interface MailBackfillResult {
  dryRun?: boolean
  sample?: { uid: number; subject: string; date: string }[]
  matched?: number
  uidvalidity?: string | null
  note?: string
  aborted?: boolean
  reason?: string
  processed?: number
  created?: number
  skippedDup?: number
  failed?: { uid: string; reason: string }[]
}

export async function backfillMailImap(body: {
  since?: string
  uids?: number[]
  dryRun: boolean
}): Promise<MailBackfillResult> {
  const response = await rawRequest(`${API_BASE}/mail/imap/backfill`, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
  return (await response.json()) as MailBackfillResult
}

/** F107：收件投递事件（失败可重放）。 */
export interface InboxEvent {
  id: number
  sourceUuid: string
  guid: string
  status: string
  errorSummary: string | null
  payloadHashPrefix: string
  createdAt: string
}

export async function listInboxEvents(
  sourceUuid: string,
  signal?: AbortSignal,
  limit = 50,
): Promise<{ items: InboxEvent[] }> {
  return request<{ items: InboxEvent[] }>(
    `${API_BASE}/inbox/sources/${encodeURIComponent(sourceUuid)}/events?limit=${limit}`,
    signal,
  )
}

export async function replayInboxEvent(
  eventId: number,
): Promise<{ status: string; ref: string; replayedFrom: number }> {
  const response = await rawRequest(`${API_BASE}/inbox/events/${eventId}/replay`, {
    method: 'POST',
  })
  return (await response.json()) as { status: string; ref: string; replayedFrom: number }
}

/** F108：接入检查（零写入契约试跑）。 */
export interface IngestDryRunResult {
  valid: boolean
  errors: { field: string; reason: string }[]
  wouldCreate: { title: string; kind: string } | null
  notes: string[]
  wouldDuplicate?: boolean
}

export async function dryRunInboxIngest(
  sourceUuid: string,
  payloadJson: string,
): Promise<IngestDryRunResult> {
  const response = await rawRequest(
    `${API_BASE}/inbox/sources/${encodeURIComponent(sourceUuid)}/ingest/dry-run`,
    {
      method: 'POST',
      body: payloadJson,
      contentType: 'application/json',
    },
  )
  return (await response.json()) as IngestDryRunResult
}

/** F114：派生数据保留策略（默认关；preview 只读，apply 有界删除）。 */
export interface StorageRetention {
  enabled: boolean
  aiVersionsDays: number | null
  taskLogDays: number | null
}

export interface RetentionPreview {
  enabled: boolean
  aiVersions: { count: number; bytes: number }
  taskLog: { count: number }
  excluded: Record<string, unknown>
  quizNote: string
}

export interface RetentionApplyResult {
  enabled: boolean
  deleted: { aiVersions: number; taskLog: number }
  note?: string
}

export async function getStorageRetention(signal?: AbortSignal): Promise<StorageRetention> {
  return request<StorageRetention>(`${API_BASE}/storage/retention`, signal)
}

export async function putStorageRetention(values: {
  enabled?: boolean
  aiVersionsDays?: number | null
  taskLogDays?: number | null
}): Promise<StorageRetention> {
  const response = await rawRequest(`${API_BASE}/storage/retention`, {
    method: 'PUT',
    body: JSON.stringify(values),
    contentType: 'application/json',
  })
  return (await response.json()) as StorageRetention
}

export async function previewStorageRetention(): Promise<RetentionPreview> {
  const response = await rawRequest(`${API_BASE}/storage/retention/preview`, { method: 'POST' })
  return (await response.json()) as RetentionPreview
}

export async function applyStorageRetention(): Promise<RetentionApplyResult> {
  const response = await rawRequest(`${API_BASE}/storage/retention/apply`, { method: 'POST' })
  return (await response.json()) as RetentionApplyResult
}

/** F115：两份本地备份 manifest 比较（incomparable 诚实呈现）。 */
export interface BackupCompareResult {
  identical: boolean
  categories: {
    name: string
    aCount: number | null
    bCount: number | null
    delta: number
  }[]
  schemaVersions: { a: unknown; b: unknown } | null
  incomparable: string[]
}

export async function compareBackups(aId: string, bId: string): Promise<BackupCompareResult> {
  const response = await rawRequest(`${API_BASE}/backups/compare`, {
    method: 'POST',
    body: JSON.stringify({ aId, bId }),
    contentType: 'application/json',
  })
  return (await response.json()) as BackupCompareResult
}

/** F109：轮换收件连接器 bearer secret。新 secret 只在本响应出现一次；
 * 旧令牌自下一请求起立即失效；已推送条目不受影响。 */
export async function rotateInboxSource(sourceUuid: string): Promise<InboxSourceCreated> {
  const response = await rawRequest(
    `${API_BASE}/inbox/sources/${encodeURIComponent(sourceUuid)}/rotate`,
    { method: 'POST' },
  )
  return (await response.json()) as InboxSourceCreated
}

// ---- N041/N042/N043/N044 今日必读队列（服务端持久化；跨设备一致） ----

/** 今日队列视图（pending + done；removed 行不出库门）。 */
export async function getTodayQueue(signal?: AbortSignal): Promise<QueueTodayResponse> {
  return request<QueueTodayResponse>(`${API_BASE}/queue/today`, signal)
}

/** 生成（或幂等返回）今天的队列：已存在时返回 200 + generated=false
 * （绝不重排已确认队列），?force=1 重建（done 保留）。 */
export async function generateTodayQueue(input: {
  timeBudgetMinutes?: number
  levels?: string[]
  workspaceId?: string
  force?: boolean
}): Promise<QueueGenerateResponse> {
  const body = {
    ...(input.timeBudgetMinutes !== undefined
      ? { timeBudgetMinutes: input.timeBudgetMinutes }
      : {}),
    ...(input.levels !== undefined ? { levels: input.levels } : {}),
    ...(input.workspaceId !== undefined ? { workspaceId: input.workspaceId } : {}),
  }
  // force 走独立路径字面量（避免把查询串拼进路径模板）。
  if (input.force === true) {
    return postJson<QueueGenerateResponse>(`${API_BASE}/queue/today/generate?force=1`, body)
  }
  return postJson<QueueGenerateResponse>(`${API_BASE}/queue/today/generate`, body)
}

/** 手动加入（新 201 / 重复或复活 200 / 今天已完成 409 queue_item_done）。 */
export async function addQueueItem(input: {
  itemRef: string
  segment?: string | null
}): Promise<QueueItemView> {
  return postJson<QueueItemView>(`${API_BASE}/queue/today/items`, {
    itemRef: input.itemRef,
    ...(input.segment !== undefined ? { segment: input.segment } : {}),
  })
}

/** 移除（status=removed，行保留；再移除 → 404）。 */
export async function removeQueueItem(itemId: string): Promise<void> {
  await rawRequest(`${API_BASE}/queue/today/items/${encodeURIComponent(itemId)}`, {
    method: 'DELETE',
  })
}

/** 完成状态（set 语义，不是 toggle；绝不隐式改写上游已读）。 */
export async function setQueueItemDone(itemId: string, done: boolean): Promise<QueueItemView> {
  return postJson<QueueItemView>(
    `${API_BASE}/queue/today/items/${encodeURIComponent(itemId)}/done`,
    { done },
  )
}

/** 持久化重排（给定的 id 按序列排前；未提及行垫后）。 */
export async function reorderTodayQueue(order: string[]): Promise<QueueTodayResponse> {
  return putJson<QueueTodayResponse>(`${API_BASE}/queue/today/order`, { order })
}

/** 行菜单移动分段（segment=null = 移回未分组）。 */
export async function moveQueueItemSegment(
  itemId: string,
  segment: string | null,
): Promise<QueueItemView> {
  return rawRequestJson<QueueItemView>(
    `${API_BASE}/queue/today/items/${encodeURIComponent(itemId)}/segment`,
    { method: 'PATCH', body: JSON.stringify({ segment }), contentType: 'application/json' },
  )
}

/** 段顺序（呈现提示；服务端存储 → 跨设备一致）。 */
export async function setQueueSegmentOrder(order: string[]): Promise<QueueTodayResponse> {
  return putJson<QueueTodayResponse>(`${API_BASE}/queue/today/segments`, { order })
}

/** 冻结当前 pending 成员为不可变快照。 */
export async function freezeTodayQueue(label: string): Promise<QueueSnapshotView> {
  return postJson<QueueSnapshotView>(`${API_BASE}/queue/today/freeze`, { label })
}

/** 快照列表（新→旧）。 */
export async function getQueueSnapshots(signal?: AbortSignal): Promise<QueueSnapshotList> {
  return request<QueueSnapshotList>(`${API_BASE}/queue/snapshots`, signal)
}

/** 打开冻结视图（原始成员顺序；消失 ref 由调用方呈现占位）。 */
export async function getQueueSnapshot(
  snapshotId: string,
  signal?: AbortSignal,
): Promise<QueueSnapshotDetail> {
  return request<QueueSnapshotDetail>(
    `${API_BASE}/queue/snapshots/${encodeURIComponent(snapshotId)}`,
    signal,
  )
}

/** 删除一个快照（housekeeping）。 */
export async function deleteQueueSnapshot(snapshotId: string): Promise<void> {
  await rawRequest(`${API_BASE}/queue/snapshots/${encodeURIComponent(snapshotId)}`, {
    method: 'DELETE',
  })
}

/** POST JSON → 解析响应体的小工具（错误处理沿用 rawRequest 信封）。 */
async function postJson<T>(path: string, body: unknown): Promise<T> {
  return rawRequestJson<T>(path, {
    method: 'POST',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
}

/** PUT JSON → 解析响应体。 */
async function putJson<T>(path: string, body: unknown): Promise<T> {
  return rawRequestJson<T>(path, {
    method: 'PUT',
    body: JSON.stringify(body),
    contentType: 'application/json',
  })
}

async function rawRequestJson<T>(
  path: string,
  init: { method: string; body: string; contentType: string },
): Promise<T> {
  const response = await rawRequest(path, init)
  return (await response.json()) as T
}

// ---- N121 粘贴多链接收件箱 / N122 剪藏锁定与候选 / N123 清理预览 -------------
// N121：逐条 created | duplicate | failed（单条失败绝不回滚整批）。

export interface BulkLinkResultItem {
  url: string
  status: 'created' | 'duplicate' | 'failed'
  ref?: string | null
  reason?: string | null
}

export interface BulkLinksResponse {
  target: 'bookmark' | 'clip'
  created: number
  duplicate: number
  failed: number
  items: BulkLinkResultItem[]
}

export function bulkLinks(urls: string[], target: 'bookmark' | 'clip'): Promise<BulkLinksResponse> {
  return postJson<BulkLinksResponse>(`${API_BASE}/library/bulk-links`, { urls, target })
}

/** N122：显式锁定/解锁（覆盖式写入的唯一开关）。 */
export function setClipLock(uuid: string, locked: boolean): Promise<{ ref: string; locked: boolean }> {
  return putJson(`${API_BASE}/library/clips/${encodeURIComponent(uuid)}/lock`, { locked })
}

export interface ClipRefreshResult {
  ref: string
  status: 'applied' | 'candidate' | 'unchanged'
  locked: boolean
  title?: string
  fetchedAt?: string
  revised?: boolean
  revisedAt?: string
  note?: string
}

/** N122：重新抓取（未锁定 → 应用进修订槽；锁定 → 只存候选）。 */
export function refreshClip(uuid: string): Promise<ClipRefreshResult> {
  return postJson<ClipRefreshResult>(
    `${API_BASE}/library/clips/${encodeURIComponent(uuid)}/refresh`,
    {},
  )
}

export interface ClipCandidate {
  ref: string
  title: string
  fetchedAt: string
  contentHtml: string
  contentText: string
}

/** N122：查看候选版本（渲染前仍须过 DOMPurify）。 */
export function getClipCandidate(uuid: string, signal?: AbortSignal): Promise<ClipCandidate> {
  return request<ClipCandidate>(
    `${API_BASE}/library/clips/${encodeURIComponent(uuid)}/candidate`,
    signal,
  )
}

/** N122：应用候选（锁定 → 409 clip_locked；可带 keepIds 走同一净化）。 */
export function applyClipCandidate(uuid: string, keepIds?: string[]): Promise<ClipRefreshResult> {
  return postJson<ClipRefreshResult>(
    `${API_BASE}/library/clips/${encodeURIComponent(uuid)}/candidate/apply`,
    keepIds ? { keepIds } : {},
  )
}

/** N122：丢弃候选版本（204；无候选 → 404）。 */
export async function discardClipCandidate(uuid: string): Promise<void> {
  await rawRequest(
    `${API_BASE}/library/clips/${encodeURIComponent(uuid)}/candidate`,
    { method: 'DELETE' },
  )
}

/** N123：清理预览（零写入）：每块 {keep, reason} 建议供用户逐块改。 */
export interface ClipCleanupBlock {
  id: string
  text: string
  keep: boolean
  reason: 'paragraph' | 'heading' | 'image' | 'ad' | 'nav' | 'link_list'
}

export interface ClipCleanupPreview {
  blocks: ClipCleanupBlock[]
  keepCount: number
  totalCount: number
}

export function previewClipCleanup(html: string): Promise<ClipCleanupPreview> {
  return postJson<ClipCleanupPreview>(`${API_BASE}/library/clips/preview-cleanup`, { html })
}

// ---- N125/N126/N127 邮件详情（附件 / 正文显示模式 / 身份提示） -----------------

export interface MailMessageSummary {
  messageId: string
  subject: string
  sender: string
  receivedAt: string
  attachmentCount: number
  skippedAttachments: number
  blockedMediaCount: number
  hasIdentityHints: boolean
}

export function listMailMessages(listUuid: string, signal?: AbortSignal): Promise<{ items: MailMessageSummary[] }> {
  return request<{ items: MailMessageSummary[] }>(
    `${API_BASE}/mail/lists/${encodeURIComponent(listUuid)}/messages`,
    signal,
  )
}

export interface MailMessageDetail {
  messageId: string
  listUuid: string
  subject: string
  sender: string
  receivedAt: string
  text: string
  html: string
  blockedMedia: string[]
  attachments: { id: string; filename: string; mime: string; size: number }[]
  skippedAttachments: {
    filename: string
    bytes: number
    mime: string
    status: string
    reason: string
  }[]
  identityHints: {
    fromAddress?: string
    fromDisplay?: string
    replyToMismatch?: boolean
    replyToAddress?: string
    displayNameDomainMismatch?: boolean
    displayNameDomains?: string[]
  } | null
}

export function getMailMessageDetail(
  listUuid: string,
  messageId: string,
  signal?: AbortSignal,
): Promise<MailMessageDetail> {
  return request<MailMessageDetail>(
    `${API_BASE}/mail/lists/${encodeURIComponent(listUuid)}/messages/${encodeURIComponent(messageId)}/detail`,
    signal,
  )
}

/** N125：附件下载地址（content-disposition: attachment 由服务端保证；
 * <a download> 直下，浏览器不渲染内容）。 */
export function mailAttachmentUrl(attachmentId: string): string {
  return `${API_BASE}/mail/attachments/${encodeURIComponent(attachmentId)}`
}

/** 剪藏完整详情（F089/N122）：content + original + revised + locked +
 * candidate。 */
export interface ClipFull {
  ref: string
  url: string
  title: string
  byline: string | null
  fetchedAt: string
  createdAt: string
  locked: boolean
  content: { html: string; text: string }
  original: { html: string; text: string }
  revised: { revisedAt: string; note: string | null; baseContentHash: string | null } | null
  candidate: { title: string; fetchedAt: string; text: string } | null
}

export function getClipFull(uuid: string, signal?: AbortSignal): Promise<ClipFull> {
  return request<ClipFull>(
    `${API_BASE}/library/clips/${encodeURIComponent(toClipId(uuid))}/full`,
    signal,
  )
}
