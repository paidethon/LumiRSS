/** 管理台（/admin → AdminScreen）Web 测试 — 0067 + P11 + N001–N004。
 *
 * 覆盖：member 访问 403 提示页、成员列表（角色/状态/方案徽标 + 暂停/
 * 恢复/撤销会话/重置密码，危险操作确认对话框）、重置密码一次性
 * 链接展示、邀请创建（一次性完整链接 + 复制）/ 列表 / 撤销、等待生效
 * 徽标（N002）、邀请方案 CRUD + 批量生成对话框（N001）、邀请漏斗
 * 计数卡片 + 方案筛选（N004）、FreshRSS 池状态（计数含预约 + 登记 +
 * 成员绑定列表）、系统面板（版本/运行时/计数/服务健康/后台任务 +
 * 审计尾部 + 刷新 + 错误态）。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）；
 * BFF 不参与测试。admin 列表的 snake_case/epoch 秒形状由 client
 * 归一，这里用真实 BFF 形状的 fixture 验证归一与渲染。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  type AdminAuditEntry,
  type AdminInvite,
  type AdminSystemInfo,
  type AdminUser,
  type InviteFunnel,
  type InviteScheme,
} from '../api/client'
import AdminScreen from '../components/admin/AdminScreen'
import { getStepUpToken, mintAdminStepUp } from '../lib/step-up'
import { useAuthStore, type AuthIdentity } from '../store/auth'

// 合成占位值（非真实凭据）
const SYNTHETIC_POOL_SECRET = ['pool', 'secret', '1'].join('-')
const mocks = vi.hoisted(() => ({
  listAdminUsers: vi.fn(),
  listAdminInvites: vi.fn(),
  createAdminInvite: vi.fn(),
  revokeAdminInvite: vi.fn(),
  pauseAdminUser: vi.fn(),
  resumeAdminUser: vi.fn(),
  revokeAdminUserSessions: vi.fn(),
  resetAdminUserPassword: vi.fn(),
  mintAdminStepUpToken: vi.fn(),
  getFreshRssPool: vi.fn(),
  registerFreshRssPool: vi.fn(),
  getAdminSystem: vi.fn(),
  listAdminAudit: vi.fn(),
  listInviteSchemes: vi.fn(),
  createInviteScheme: vi.fn(),
  deleteInviteScheme: vi.fn(),
  generateInvitesFromScheme: vi.fn(),
  getInviteFunnel: vi.fn(),
  getRegistrationPolicy: vi.fn(),
  updateRegistrationPolicy: vi.fn(),
  getAdminUserQuota: vi.fn(),
  setAdminUserQuota: vi.fn(),
  getAdminCapacity: vi.fn(),
  getAdminUpgradePreview: vi.fn(),
  getAdminDeployStatus: vi.fn(),
}))

vi.mock('../api/client', () => {
  // FIX-028：不用 importOriginal —— 真实 client 与 lib/step-up 存在模块环，
  // importOriginal 会把 lib 侧绑到第二个 client 实例上（令牌状态分裂）。
  // 这里给出测试所需的运行时导出（其余 client 导出在本套件只以 type-only
  // 形式引用，编译后无运行时引用）。
  class ApiError extends Error {
    readonly status: number
    readonly type: string
    readonly retryAfterSeconds: number | null
    readonly extra: Record<string, string> | null
    readonly redirectChain: unknown[] | null
    constructor(
      status: number,
      type: string,
      message: string,
      retryAfterSeconds: number | null = null,
      extra: Record<string, string> | null = null,
      redirectChain: unknown[] | null = null,
    ) {
      super(message)
      this.name = 'ApiError'
      this.status = status
      this.type = type
      this.retryAfterSeconds = retryAfterSeconds
      this.extra = extra
      this.redirectChain = redirectChain
    }
  }
  return {
    ApiError,
    listAdminUsers: mocks.listAdminUsers,
    listAdminInvites: mocks.listAdminInvites,
    createAdminInvite: mocks.createAdminInvite,
    revokeAdminInvite: mocks.revokeAdminInvite,
    pauseAdminUser: mocks.pauseAdminUser,
    resumeAdminUser: mocks.resumeAdminUser,
    revokeAdminUserSessions: mocks.revokeAdminUserSessions,
    resetAdminUserPassword: mocks.resetAdminUserPassword,
    getFreshRssPool: mocks.getFreshRssPool,
    registerFreshRssPool: mocks.registerFreshRssPool,
    getAdminSystem: mocks.getAdminSystem,
    listAdminAudit: mocks.listAdminAudit,
    listInviteSchemes: mocks.listInviteSchemes,
    createInviteScheme: mocks.createInviteScheme,
    deleteInviteScheme: mocks.deleteInviteScheme,
    generateInvitesFromScheme: mocks.generateInvitesFromScheme,
    getInviteFunnel: mocks.getInviteFunnel,
    getRegistrationPolicy: mocks.getRegistrationPolicy,
    updateRegistrationPolicy: mocks.updateRegistrationPolicy,
    getAdminUserQuota: mocks.getAdminUserQuota,
    setAdminUserQuota: mocks.setAdminUserQuota,
    getAdminCapacity: mocks.getAdminCapacity,
    getAdminUpgradePreview: mocks.getAdminUpgradePreview,
    getAdminDeployStatus: mocks.getAdminDeployStatus,
    mintAdminStepUpToken: mocks.mintAdminStepUpToken,
  }
})

const OWNER: AuthIdentity = { userId: 'u1', username: 'alice', role: 'owner' }
const MEMBER: AuthIdentity = { userId: 'u2', username: 'bob', role: 'member' }

/** vi.mock 替换了 client 函数 —— 归一（snake_case/epoch → DTO）不在本
 * 套件职责内（见 admin-api-client.test.ts，走真实 client + fetch stub）。
 * 这里直接给归一后的 DTO，专注 UI 行为。时间用动态值（过期判定按墙钟）。*/
const NOW_MS = Date.now()
const ISO = (offsetMs: number) => new Date(NOW_MS + offsetMs).toISOString()

const USERS: AdminUser[] = [
  { id: 'u1', username: 'alice', role: 'owner', status: 'active', displayName: '运营者', schemeName: null, createdAt: ISO(-86_400_000) },
  { id: 'u3', username: 'carol', role: 'member', status: 'paused', displayName: null, schemeName: '新人套餐', createdAt: ISO(-3_600_000) },
]

const INVITES: AdminInvite[] = [
  {
    id: 'i1',
    kind: 'signup',
    label: '给 dave 的邀请',
    targetUsername: null,
    schemeId: null,
    notBefore: null,
    heldPoolAccount: null,
    createdAt: ISO(-3_600_000),
    expiresAt: ISO(72 * 3_600_000),
    usedAt: null,
    revokedAt: null,
  },
]

/** 预约生效邀请（N002）：notBefore 在未来 → 台账显示「等待生效」且可撤销。 */
const SCHEDULED_INVITES: AdminInvite[] = [
  {
    id: 'i2',
    kind: 'signup',
    label: '预约生效邀请',
    targetUsername: null,
    schemeId: 's1',
    notBefore: ISO(3_600_000),
    heldPoolAccount: 'frss-held',
    createdAt: ISO(-60_000),
    expiresAt: ISO(72 * 3_600_000),
    usedAt: null,
    revokedAt: null,
  },
]

/** 邀请方案 fixture（N001，已归一 DTO）。 */
const SCHEMES: InviteScheme[] = [
  {
    id: 's1',
    name: '新人套餐',
    ttlHours: 48,
    initialSourceUrls: ['https://a.example/feed.xml', 'https://b.example/rss.xml'],
    freshrssPoolHold: true,
    quotaNote: '每人 3 源',
    createdAt: ISO(-86_400_000),
  },
]

/** 邀请漏斗 fixture（N004，服务端真实行聚合的同款形状）。 */
const FUNNEL: InviteFunnel = {
  totals: { generated: 5, pending: 2, activated: 1, expired: 1, revoked: 1, failedActivation: 1 },
  byScheme: [
    { schemeId: 's1', schemeName: '新人套餐', generated: 2, pending: 1, activated: 1, expired: 0, revoked: 0 },
    { schemeId: null, schemeName: null, generated: 3, pending: 1, activated: 0, expired: 1, revoked: 1 },
  ],
}

/** P11 系统面板 fixture：与真实 BFF /admin/system 响应同构（已归一 DTO）。 */
const SYSTEM: AdminSystemInfo = {
  version: '0.2.0',
  commit: 'abc1234dead',
  python: '3.12.1',
  uptimeS: 90_061,
  process: { rssBytes: 120_586_240, peakRssBytes: 130_023_424, cpuTimeS: 42.7 },
  counts: {
    users: 3,
    activeUsers: 2,
    invites: 5,
    freshrssPoolReady: 2,
    freshrssPoolAssigned: 1,
    sessions: 4,
    feeds: 12,
    entriesIndexed: 345,
    libraryItems: 67,
  },
  services: [
    { name: 'sqlite', configured: true, status: 'healthy', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
    { name: 'freshrss', configured: true, status: 'healthy', latencyMs: 23, checkedAt: ISO(-5_000), stale: false },
    { name: 'rsshub', configured: false, status: 'unconfigured', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
    { name: 'obsidian', configured: false, status: 'unconfigured', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
    { name: 'webdav', configured: false, status: 'unconfigured', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
    { name: 'ai', configured: true, status: 'configured', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
    { name: 'imap', configured: false, status: 'unconfigured', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
  ],
  tasks: [
    { name: 'search_sync', enabled: true, state: 'running', lastRunAt: null },
    { name: 'obsidian_scan', enabled: false, state: 'off', lastRunAt: null },
    { name: 'digest_scheduler', enabled: true, state: 'running', lastRunAt: null },
    { name: 'mail_imap', enabled: true, state: 'running', lastRunAt: null },
    { name: 'gpt_digest_scheduler', enabled: true, state: 'running', lastRunAt: null },
    { name: 'rag_idle', enabled: true, state: 'running', lastRunAt: null },
    { name: 'rag_index', enabled: false, state: 'off', lastRunAt: null },
  ],
}

/** 审计尾部 fixture（操作者只以 id 出现——API 已脱敏的同款形状）。 */
const AUDIT: AdminAuditEntry[] = [
  { at: ISO(-60_000), actor: 'u1', action: 'invite_create_signup', objectType: 'invite', objectId: 'i9', outcome: 'ok', detail: null },
  { at: ISO(-7_200_000), actor: 'u1', action: 'user_role_change', objectType: 'user', objectId: 'u3', outcome: 'ok', detail: 'admin' },
  { at: null, actor: 'u1', action: 'future_unknown_action', objectType: null, objectId: null, outcome: 'error', detail: null },
]

beforeEach(() => {
  window.addEventListener('unhandledrejection', (e) => {
    console.log('DBG unhandled rejection:', e.reason)
  })
})

function renderAdmin() {
  return render(
    <QueryClientProvider
      // retry:false：错误态用例不被 TanStack 默认重试拖慢（行为不变）。
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AdminScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  useAuthStore.setState({ status: 'authenticated', mode: 'session', identity: OWNER })
  vi.clearAllMocks()
  // 默认成功响应（各用例可覆盖）
  mocks.listAdminUsers.mockResolvedValue(USERS)
  mocks.listAdminInvites.mockResolvedValue(INVITES)
  mocks.getFreshRssPool.mockResolvedValue({
    ready: 2,
    held: 1,
    assigned: 1,
    members: [
      { id: 'u2', username: 'bob', bound: true, boundTo: 'frss-bob' },
      { id: 'u9', username: 'erin', bound: false, boundTo: null },
    ],
  })
  mocks.getAdminSystem.mockResolvedValue(SYSTEM)
  mocks.listAdminAudit.mockResolvedValue(AUDIT)
  mocks.listInviteSchemes.mockResolvedValue(SCHEMES)
  mocks.getInviteFunnel.mockResolvedValue(FUNNEL)
  // P0-05：默认策略关闭（服务端默认 OFF 的同款形状）。
  mocks.getRegistrationPolicy.mockResolvedValue({
    allowPublicRegistration: false,
    updatedAt: null,
    updatedBy: null,
  })
  // N191/N192/N195/N196：新管理台区块的默认诚实空态（不打扰既有用例）。
  mocks.getAdminCapacity.mockResolvedValue({
    pool: { ready: 0, held: 0, assigned: 0 },
    invites: { pending: 0, held: 0 },
    users: { active: 0, paused: 0 },
    lowCapacity: false,
  })
  mocks.getAdminUpgradePreview.mockResolvedValue({
    available: false,
    reason: 'not configured',
    currentVersion: null,
    targetVersion: null,
    newMigrations: [],
    minCompat: null,
    blocked: false,
    blockedReason: null,
  })
  mocks.getAdminDeployStatus.mockResolvedValue({
    available: false,
    reason: 'not configured',
    deploy: null,
  })
})

describe('权限门（后端 403 的前端转述）', () => {
  it('member 访问 → 403 提示页，不渲染任何管理区块', async () => {
    useAuthStore.setState({ identity: MEMBER })
    renderAdmin()
    const forbidden = await screen.findByTestId('admin-forbidden')
    expect(forbidden).toHaveTextContent('没有访问权限')
    expect(screen.queryByLabelText('成员列表')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('邀请管理')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('FreshRSS 池')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('系统状态')).not.toBeInTheDocument()
    // 越权渲染不发生 → 系统查询也不该发出。
    expect(mocks.getAdminSystem).not.toHaveBeenCalled()
  })

  it('身份未核实 → 显示核实中（不发管理查询前的越权渲染）', () => {
    useAuthStore.setState({ identity: null })
    renderAdmin()
    expect(screen.getByRole('status')).toHaveTextContent('正在核实身份')
  })
})

describe('成员列表', () => {
  it('渲染角色/状态徽标（含方案徽标，N001）', async () => {
    renderAdmin()
    const list = await screen.findByTestId('admin-user-list')
    expect(list).toHaveTextContent('alice')
    expect(list).toHaveTextContent('运营者')
    expect(list).toHaveTextContent('正常')
    expect(list).toHaveTextContent('carol')
    expect(list).toHaveTextContent('已暂停')
    expect(list).toHaveTextContent('方案 · 新人套餐')
  })

  it('carol 已暂停 → 显示「恢复」；alice 正常 → 显示「暂停」', async () => {
    renderAdmin()
    await screen.findByTestId('admin-user-list')
    expect(screen.getByRole('button', { name: '恢复' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '暂停' })).toBeInTheDocument()
  })

  it('暂停是危险操作：先确认，确认后调用 pause 端点', async () => {
    mocks.pauseAdminUser.mockResolvedValue(undefined)
    renderAdmin()
    await screen.findByTestId('admin-user-list')
    fireEvent.click(screen.getByRole('button', { name: '暂停' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('暂停')
    expect(mocks.pauseAdminUser).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: '暂停' }))
    await waitFor(() => {
      expect(mocks.pauseAdminUser).toHaveBeenCalledWith('u1')
    })
  })

  it('确认对话框可取消（不发请求）', async () => {
    renderAdmin()
    await screen.findByTestId('admin-user-list')
    fireEvent.click(screen.getAllByRole('button', { name: '撤销会话' })[0]!)
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: '取消' }))
    expect(mocks.revokeAdminUserSessions).not.toHaveBeenCalled()
  })

  it('重置密码：确认后展示一次性恢复链接（只显示一次）', async () => {
    mocks.resetAdminUserPassword.mockResolvedValue({
      recoveryToken: 'inv_rec789',
      invite: { id: 'i9', kind: 'recovery' },
    })
    renderAdmin()
    await screen.findByTestId('admin-user-list')
    fireEvent.click(screen.getAllByRole('button', { name: '重置密码' })[0]!)
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: '重置密码' }))
    const link = await screen.findByTestId('one-time-link')
    expect(link).toHaveTextContent(`/activate?token=inv_rec789`)
    expect(mocks.resetAdminUserPassword).toHaveBeenCalledWith('u1')
  })
})

describe('邀请管理', () => {
  it('列表渲染台账（label/状态徽标），有效邀请有撤销按钮', async () => {
    renderAdmin()
    const list = await screen.findByTestId('admin-invite-list')
    expect(list).toHaveTextContent('给 dave 的邀请')
    expect(list).toHaveTextContent('有效')
    expect(screen.getByRole('button', { name: '撤销' })).toBeInTheDocument()
  })

  it('创建邀请 → 一次性展示完整激活链接 + 复制按钮', async () => {
    mocks.createAdminInvite.mockResolvedValue({
      token: 'inv_new123',
      invite: { id: 'i2', kind: 'signup', label: null },
    })
    renderAdmin()
    await screen.findByTestId('admin-invite-list')
    fireEvent.click(screen.getByRole('button', { name: '创建邀请' }))
    const link = await screen.findByTestId('one-time-link')
    expect(link).toHaveTextContent(`${window.location.origin}/activate?token=inv_new123`)
    expect(mocks.createAdminInvite).toHaveBeenCalledWith({ kind: 'signup', label: null, ttlHours: 72 })
    // 复制按钮存在（clipboard 由 jsdom 环境决定，不强制成功）
    expect(screen.getByRole('button', { name: /复制链接/ })).toBeInTheDocument()
  })

  it('创建失败（403 等）→ 表单内诚实报错', async () => {
    mocks.createAdminInvite.mockRejectedValue(new ApiError(403, 'forbidden', 'Administrator role required.'))
    renderAdmin()
    await screen.findByTestId('admin-invite-list')
    fireEvent.click(screen.getByRole('button', { name: '创建邀请' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('需要管理员权限')
  })

  it('撤销邀请：确认对话框 → revokeAdminInvite', async () => {
    mocks.revokeAdminInvite.mockResolvedValue(undefined)
    renderAdmin()
    await screen.findByTestId('admin-invite-list')
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: '撤销邀请' }))
    await waitFor(() => {
      expect(mocks.revokeAdminInvite).toHaveBeenCalledWith('i1')
    })
  })

  it('预约生效邀请（N002）→ 「等待生效」徽标 + 生效时间，仍可撤销', async () => {
    mocks.listAdminInvites.mockResolvedValue(SCHEDULED_INVITES)
    renderAdmin()
    const list = await screen.findByTestId('admin-invite-list')
    expect(list).toHaveTextContent('等待生效')
    expect(list).toHaveTextContent('起生效')
    expect(list).toHaveTextContent('方案')
    // 未开闸的邀请必须能收回——撤销按钮仍在。
    expect(screen.getByRole('button', { name: '撤销' })).toBeInTheDocument()
  })
})

describe('邀请方案（N001）', () => {
  it('方案列表渲染（名称/TTL/预约标记/初始源数/配额备注）', async () => {
    renderAdmin()
    const list = await screen.findByTestId('scheme-list')
    expect(list).toHaveTextContent('新人套餐')
    expect(list).toHaveTextContent('48 小时')
    expect(list).toHaveTextContent('预约池名额')
    expect(list).toHaveTextContent('2 个初始源')
    expect(list).toHaveTextContent('每人 3 源')
  })

  it('保存方案表单 → createInviteScheme（多行 URL 逐行拆分）', async () => {
    mocks.createInviteScheme.mockResolvedValue(SCHEMES[0]!)
    renderAdmin()
    await screen.findByTestId('scheme-list')
    // 邀请表单也有「有效期（小时）」——先圈定方案表单再查询。
    const form = within(screen.getByTestId('scheme-create-form'))
    fireEvent.change(form.getByLabelText('方案名称'), { target: { value: '深度阅读套餐' } })
    fireEvent.change(form.getByLabelText('有效期（小时）'), { target: { value: '24' } })
    fireEvent.change(form.getByLabelText('初始订阅源（每行一个 URL，可选）'), {
      target: { value: 'https://x.example/1.xml\nhttps://x.example/2.xml\n\n' },
    })
    fireEvent.click(form.getByLabelText('生成时预约 FreshRSS 池名额'))
    fireEvent.change(form.getByLabelText('配额备注（可选）'), { target: { value: '每人 2 源' } })
    fireEvent.click(form.getByRole('button', { name: '保存方案' }))
    await waitFor(() => {
      expect(mocks.createInviteScheme).toHaveBeenCalledWith({
        name: '深度阅读套餐',
        ttlHours: 24,
        initialSourceUrls: ['https://x.example/1.xml', 'https://x.example/2.xml'],
        freshrssPoolHold: true,
        quotaNote: '每人 2 源',
      })
    })
  })

  it('批量生成对话框：输入数量 → 生成 N 个一次性链接（只显示一次）', async () => {
    mocks.generateInvitesFromScheme.mockResolvedValue({
      scheme: SCHEMES[0]!,
      invites: [
        { token: 'inv_b1', invite: { id: 'ib1', kind: 'signup', label: '新人套餐' } as AdminInvite },
        { token: 'inv_b2', invite: { id: 'ib2', kind: 'signup', label: '新人套餐' } as AdminInvite },
      ],
    })
    renderAdmin()
    await screen.findByTestId('scheme-list')
    fireEvent.click(screen.getByTestId('scheme-generate-s1'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('从「新人套餐」批量生成邀请')
    fireEvent.change(within(dialog).getByLabelText('生成数量'), { target: { value: '2' } })
    fireEvent.click(within(dialog).getByRole('button', { name: '生成' }))
    await waitFor(() => {
      expect(mocks.generateInvitesFromScheme).toHaveBeenCalledWith('s1', { count: 2 })
    })
    const links = await within(dialog).findAllByTestId('one-time-link')
    expect(links).toHaveLength(2)
    expect(links[0]).toHaveTextContent('token=inv_b1')
    expect(links[1]).toHaveTextContent('token=inv_b2')
  })

  it('池不足的批量生成（pool_empty）→ 对话框内诚实报错', async () => {
    mocks.generateInvitesFromScheme.mockRejectedValue(
      new ApiError(409, 'pool_empty', 'Pool has 0 ready account(s); 2 hold(s) were requested.'),
    )
    renderAdmin()
    await screen.findByTestId('scheme-list')
    fireEvent.click(screen.getByTestId('scheme-generate-s1'))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: '生成' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('ready account')
  })

  it('删除方案是危险操作：确认后调用 deleteInviteScheme', async () => {
    mocks.deleteInviteScheme.mockResolvedValue(undefined)
    renderAdmin()
    await screen.findByTestId('scheme-list')
    fireEvent.click(screen.getByRole('button', { name: '删除' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('删除方案')
    fireEvent.click(within(dialog).getByRole('button', { name: '删除方案' }))
    await waitFor(() => {
      expect(mocks.deleteInviteScheme).toHaveBeenCalledWith('s1')
    })
  })

  it('创建方案失败 → 表单内诚实报错', async () => {
    mocks.createInviteScheme.mockRejectedValue(new ApiError(403, 'forbidden', 'Administrator role required.'))
    renderAdmin()
    await screen.findByTestId('scheme-list')
    fireEvent.change(screen.getByLabelText('方案名称'), { target: { value: 'x 方案' } })
    fireEvent.click(screen.getByRole('button', { name: '保存方案' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('需要管理员权限')
  })
})

describe('邀请漏斗（N004）', () => {
  it('计数卡片渲染服务端聚合（无邀请码），按方案分桶明细', async () => {
    renderAdmin()
    const cards = await screen.findByTestId('funnel-cards')
    expect(cards).toHaveTextContent('5')
    expect(cards).toHaveTextContent('已生成')
    expect(cards).toHaveTextContent('待使用')
    expect(cards).toHaveTextContent('已激活')
    expect(screen.getByTestId('funnel-activated')).toHaveTextContent('1')
    expect(screen.getByTestId('funnel-expired')).toHaveTextContent('1')
    expect(screen.getByTestId('funnel-revoked')).toHaveTextContent('1')
    expect(screen.getByTestId('funnel-failed-activation')).toHaveTextContent('激活失败尝试：1 次')
    const buckets = screen.getByTestId('funnel-by-scheme')
    expect(buckets).toHaveTextContent('新人套餐')
    expect(buckets).toHaveTextContent('未分组（普通邀请）')
    // 漏斗载荷不含任何邀请码。
    expect(screen.queryByText(/inv_/)).not.toBeInTheDocument()
  })

  it('方案筛选 → getInviteFunnel 带 scheme_id 重新请求', async () => {
    renderAdmin()
    await screen.findByTestId('funnel-cards')
    expect(mocks.getInviteFunnel).toHaveBeenCalledWith(expect.anything(), null)
    fireEvent.change(screen.getByTestId('funnel-scheme-filter'), { target: { value: 's1' } })
    await waitFor(() => {
      expect(mocks.getInviteFunnel).toHaveBeenCalledWith(expect.anything(), 's1')
    })
  })

  it('真实动作后刷新：创建邀请使漏斗缓存失效并重取', async () => {
    mocks.createAdminInvite.mockResolvedValue({
      token: 'inv_f1',
      invite: { id: 'if1', kind: 'signup', label: null } as AdminInvite,
    })
    renderAdmin()
    await screen.findByTestId('funnel-cards')
    const callsAfterMount = mocks.getInviteFunnel.mock.calls.length
    expect(callsAfterMount).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: '创建邀请' }))
    await screen.findAllByTestId('one-time-link')
    await waitFor(() => {
      expect(mocks.getInviteFunnel.mock.calls.length).toBeGreaterThan(callsAfterMount)
    })
  })

  it('漏斗接口失败 → 区块内诚实报错，其余区块不受影响', async () => {
    mocks.getInviteFunnel.mockRejectedValue(new ApiError(403, 'forbidden', 'Administrator role required.'))
    renderAdmin()
    const section = await screen.findByTestId('invite-funnel')
    expect(await within(section).findByRole('alert')).toHaveTextContent('需要管理员权限')
    expect(screen.getByTestId('admin-invite-list')).toBeInTheDocument()
  })
})

describe('FreshRSS 池', () => {
  it('显示 ready/held/assigned 计数与成员绑定状态', async () => {
    renderAdmin()
    const counts = await screen.findByTestId('pool-counts')
    expect(counts).toHaveTextContent('可绑定 2')
    expect(counts).toHaveTextContent('已预约 1')
    expect(counts).toHaveTextContent('已分配 1')
    const members = await screen.findByTestId('pool-member-list')
    expect(members).toHaveTextContent('bob')
    expect(members).toHaveTextContent('已绑定 frss-bob')
    expect(members).toHaveTextContent('erin')
    expect(members).toHaveTextContent('待绑定')
  })

  it('登记表单 → POST /admin/pool（用户名/地址/API 密码）', async () => {
    mocks.registerFreshRssPool.mockResolvedValue(undefined)
    renderAdmin()
    await screen.findByTestId('pool-counts')
    fireEvent.change(screen.getByLabelText('FreshRSS 用户名'), { target: { value: 'frss-frank' } })
    fireEvent.change(screen.getByLabelText('FreshRSS 地址'), { target: { value: 'https://freshrss.example.com' } })
    fireEvent.change(screen.getByLabelText('API 密码（只写）'), { target: { value: SYNTHETIC_POOL_SECRET } })
    fireEvent.click(screen.getByRole('button', { name: '登记入池' }))
    await waitFor(() => {
      expect(mocks.registerFreshRssPool).toHaveBeenCalledWith({
        freshrssUsername: 'frss-frank',
        freshrssBaseUrl: 'https://freshrss.example.com',
        apiPassword: SYNTHETIC_POOL_SECRET,
        publicUrl: null,
      })
    })
    expect(await screen.findByRole('status')).toHaveTextContent('已登记入池')
  })

  it('登记冲突（pool_conflict）→ 透出服务端提示', async () => {
    mocks.registerFreshRssPool.mockRejectedValue(
      new ApiError(409, 'pool_conflict', 'This FreshRSS account is already registered.'),
    )
    renderAdmin()
    await screen.findByTestId('pool-counts')
    fireEvent.change(screen.getByLabelText('FreshRSS 用户名'), { target: { value: 'frss-frank' } })
    fireEvent.change(screen.getByLabelText('FreshRSS 地址'), { target: { value: 'https://freshrss.example.com' } })
    fireEvent.change(screen.getByLabelText('API 密码（只写）'), { target: { value: SYNTHETIC_POOL_SECRET } })
    fireEvent.click(screen.getByRole('button', { name: '登记入池' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already registered')
  })
})

describe('系统面板（P11）', () => {
  it('渲染版本/运行时/内存与存储计数', async () => {
    renderAdmin()
    const runtime = await screen.findByTestId('admin-system-runtime')
    expect(runtime).toHaveTextContent('0.2.0 (abc1234)')
    expect(runtime).toHaveTextContent('3.12.1')
    expect(runtime).toHaveTextContent('1 天 1 小时')
    expect(runtime).toHaveTextContent('115 MB / 124 MB')
    expect(runtime).toHaveTextContent('42.7 秒')
    const counts = screen.getByTestId('admin-system-counts')
    expect(counts).toHaveTextContent('3（2）')
    expect(counts).toHaveTextContent('2 / 1')
    expect(counts).toHaveTextContent('12 / 345 / 67')
  })

  it('服务健康列表：已配置正常态/未配置态/延迟，状态带文字标签', async () => {
    renderAdmin()
    const services = await screen.findByTestId('admin-system-services')
    expect(services).toHaveTextContent('Lumi 数据库')
    expect(services).toHaveTextContent('FreshRSS')
    expect(within(services).getByText('23 ms')).toBeInTheDocument()
    expect(services).toHaveTextContent('未配置')
    // 「正常」出现多次（sqlite/freshrss），用列表内全体文本断言。
    expect(services).toHaveTextContent('正常')
    expect(services).toHaveTextContent('已配置')
  })

  it('后台任务列表：运行中与未启用如实区分', async () => {
    renderAdmin()
    const tasks = await screen.findByTestId('admin-system-tasks')
    expect(tasks).toHaveTextContent('订阅投影同步')
    expect(tasks).toHaveTextContent('运行中')
    expect(tasks).toHaveTextContent('Obsidian 扫描')
    expect(tasks).toHaveTextContent('未启用')
  })

  it('审计尾部渲染最近动态（未知动作原样透出，非 ok 结果带徽标）', async () => {
    renderAdmin()
    const audit = await screen.findByTestId('admin-audit-list')
    expect(audit).toHaveTextContent('创建注册邀请')
    expect(audit).toHaveTextContent('1 分钟前')
    expect(audit).toHaveTextContent('变更角色')
    expect(audit).toHaveTextContent('admin')
    // 审计不含用户名——操作者 id 不渲染为成员名。
    expect(audit).toHaveTextContent('future_unknown_action')
    expect(within(audit).getByText('error')).toBeInTheDocument()
  })

  it('审计为空 → 诚实空态', async () => {
    mocks.listAdminAudit.mockResolvedValue([])
    renderAdmin()
    await screen.findByTestId('admin-system-audit')
    expect(screen.getByText('暂无操作记录。')).toBeInTheDocument()
  })

  it('系统接口失败 → 区块内诚实报错，其余区块不受影响', async () => {
    mocks.getAdminSystem.mockRejectedValue(new ApiError(403, 'forbidden', 'Administrator role required.'))
    renderAdmin()
    const section = await screen.findByTestId('admin-system')
    expect(await within(section).findByRole('alert')).toHaveTextContent('需要管理员权限')
    // 成员列表（独立查询）照常渲染。
    expect(screen.getByTestId('admin-user-list')).toBeInTheDocument()
  })

  it('刷新按钮 → 重取系统与审计两个查询', async () => {
    renderAdmin()
    await screen.findByTestId('admin-system-runtime')
    expect(mocks.getAdminSystem).toHaveBeenCalledTimes(1)
    expect(mocks.listAdminAudit).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByTestId('admin-system-refresh'))
    await waitFor(() => {
      expect(mocks.getAdminSystem).toHaveBeenCalledTimes(2)
      expect(mocks.listAdminAudit).toHaveBeenCalledTimes(2)
    })
  })

  it('N194 探针时效：正常服务显示「检测于 X 前」；过期服务标注「可能过期」并取代正常徽标', async () => {
    const staleServices = [
      { name: 'sqlite', configured: true, status: 'healthy', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
      { name: 'freshrss', configured: true, status: 'healthy', latencyMs: 23, checkedAt: ISO(-360_000), stale: true },
      { name: 'rsshub', configured: false, status: 'unconfigured', latencyMs: null, checkedAt: null, stale: false },
      { name: 'obsidian', configured: false, status: 'unconfigured', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
      { name: 'webdav', configured: false, status: 'unconfigured', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
      { name: 'ai', configured: true, status: 'configured', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
      { name: 'imap', configured: false, status: 'unconfigured', latencyMs: null, checkedAt: ISO(-5_000), stale: false },
    ]
    mocks.getAdminSystem.mockResolvedValue({ ...SYSTEM, services: staleServices })
    renderAdmin()
    const services = await screen.findByTestId('admin-system-services')
    // 正常探针：附带探针时间（相对时间随渲染时刻略有漂移，用模式断言）
    expect(services).toHaveTextContent(/检测于 \d+ 秒前/)
    // 过期探针：专用标记（可能过期），正常「正常」徽标被取代
    const staleBadge = await screen.findByTestId('admin-service-stale-freshrss')
    expect(staleBadge).toHaveTextContent(/检测于 \d+ 分钟前（可能过期）/)
    expect(staleBadge).toHaveTextContent('可能过期')
    // freshrss 行内不再出现独立的「正常」徽标文本——行内只有过期态。
    expect(within(staleBadge).queryByText('正常')).not.toBeInTheDocument()
  })
})

describe('账户与注册（P0-05 注册策略开关）', () => {
  const POLICY_UPDATED = {
    allowPublicRegistration: true,
    updatedAt: ISO(-30_000),
    updatedBy: 'u1',
  }

  it('关闭态渲染：开关 off + 描述文案 + 当前状态；无变更记录时不显示时间', async () => {
    renderAdmin()
    const section = await screen.findByTestId('registration-policy')
    const switchControl = await within(section).findByRole('switch', { name: '公开注册' })
    expect(switchControl).toHaveAttribute('aria-checked', 'false')
    expect(section).toHaveTextContent('允许任何可以访问此 LumiRSS 实例的人创建普通成员账号')
    expect(section).toHaveTextContent('邀请链接仍然可以使用')
    expect(section).toHaveTextContent('当前状态：已关闭')
    expect(section).not.toHaveTextContent('最近变更')
  })

  it('开启态渲染：开关 on（含 updatedAt/updatedBy 展示）', async () => {
    mocks.getRegistrationPolicy.mockResolvedValue(POLICY_UPDATED)
    renderAdmin()
    const section = await screen.findByTestId('registration-policy')
    const switchControl = await within(section).findByRole('switch', { name: '公开注册' })
    expect(switchControl).toHaveAttribute('aria-checked', 'true')
    expect(section).toHaveTextContent('当前状态：已开放')
    expect(section).toHaveTextContent('最近变更')
    expect(section).toHaveTextContent('由 u1')
  })

  it('切换开关 → PUT /admin/registration-policy 携带新值，成功后按服务端响应刷新', async () => {
    mocks.updateRegistrationPolicy.mockResolvedValue(POLICY_UPDATED)
    renderAdmin()
    const section = await screen.findByTestId('registration-policy')
    fireEvent.click(await within(section).findByRole('switch', { name: '公开注册' }))
    await waitFor(() => {
      expect(mocks.updateRegistrationPolicy).toHaveBeenCalledTimes(1)
    })
    expect(mocks.updateRegistrationPolicy).toHaveBeenCalledWith(true)
    // 服务端权威响应回填：状态与开关翻到开启。
    await waitFor(() => {
      expect(section).toHaveTextContent('当前状态：已开放')
    })
    expect(within(section).getByRole('switch', { name: '公开注册' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
  })

  it('PUT 失败 → 开关回滚到服务端值并诚实提示', async () => {
    mocks.updateRegistrationPolicy.mockRejectedValue(
      new ApiError(403, 'forbidden', 'Administrator role required.'),
    )
    renderAdmin()
    const section = await screen.findByTestId('registration-policy')
    fireEvent.click(await within(section).findByRole('switch', { name: '公开注册' }))
    // 乐观翻到 on 后失败 → 回滚 off + 错误文案。
    await waitFor(() => {
      expect(within(section).getByRole('alert')).toHaveTextContent('需要管理员权限')
    })
    expect(within(section).getByRole('switch', { name: '公开注册' })).toHaveAttribute(
      'aria-checked',
      'false',
    )
    expect(section).toHaveTextContent('当前状态：已关闭')
  })
})

// ===== FIX-052 基线验证 ======================================================
// 审计项「管理页标签切换丢失 URL 状态」对照当前实现为 BASELINE_OK（N/A）：
// AdminScreen 没有标签页状态——全部分区在单一滚动页同时渲染，/admin
// 深链接打开的就是完整管理台，不存在「URL 只能定位到默认分区」的丢失面。
// 本用例将该结构属性固化为回归防线：若未来引入分区标签页，必须同步把
// 分区写进 URL（否则本用例失败）。

describe('FIX-052 基线：管理台无标签页门控，深链接即全部分区', () => {
  it('/admin 渲染时不同区域的分区同时可见（无 tab 状态可丢失）', async () => {
    renderAdmin()
    await screen.findByTestId('admin-user-list')
    // 成员（左上）、邀请（右上）、系统（页尾）——来自三个互不相邻的
    // 区域，同帧可见即「无分区标签页」结构成立。
    expect(screen.getByLabelText('成员列表')).toBeInTheDocument()
    expect(screen.getByLabelText('邀请管理')).toBeInTheDocument()
    expect(screen.getByLabelText('系统状态')).toBeInTheDocument()
    // 同理不存在任何 role=tab 的分区切换器。
    expect(screen.queryAllByRole('tab')).toHaveLength(0)
  })
})

// ===== FIX-034 基线验证 ======================================================
// 审计项「启用/禁用/删除按钮作用于选中行而非当前行」对照当前实现为
// BASELINE_OK：MembersSection 没有「选中行」状态——每个动作按钮都在
// users.data.map 的行闭包里绑定各自的 user.id。本用例渲染两行成员，
// 点第二行的动作，断言请求只命中该行 id（若未来引入共享 selected id
// 引用，本用例失败）。

describe('FIX-034 基线：成员行动作按行绑定（不存在「选中行」引用）', () => {
  it('点击 carol（第 2 行）「恢复」只对 carol 发 resume；确认动作同样只作用于所在行', async () => {
    mocks.resumeAdminUser.mockResolvedValue({})
    mocks.revokeAdminUserSessions.mockResolvedValue({})
    renderAdmin()
    const list = await screen.findByTestId('admin-user-list')
    expect(within(list).getByText('alice')).toBeInTheDocument()
    expect(within(list).getByText('carol')).toBeInTheDocument()

    // 直接动作：carol（已暂停）行唯一的「恢复」按钮 → resume('u3')，
    // 绝不触达 alice（'u1'）。
    fireEvent.click(screen.getByRole('button', { name: '恢复' }))
    await waitFor(() => expect(mocks.resumeAdminUser).toHaveBeenCalledTimes(1))
    expect(mocks.resumeAdminUser).toHaveBeenCalledWith('u3')
    expect(mocks.resumeAdminUser).not.toHaveBeenCalledWith('u1')

    // 确认动作：carol 行的「撤销会话」（按行定位）→ 确认 → revoke('u3')
    const carolRow = within(list).getByText('carol').closest('li')
    expect(carolRow).not.toBeNull()
    fireEvent.click(within(carolRow as HTMLElement).getByRole('button', { name: '撤销会话' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('carol')
    fireEvent.click(within(dialog).getByRole('button', { name: '撤销会话' }))
    await waitFor(() => expect(mocks.revokeAdminUserSessions).toHaveBeenCalledTimes(1))
    expect(mocks.revokeAdminUserSessions).toHaveBeenCalledWith('u3')
    expect(mocks.pauseAdminUser).not.toHaveBeenCalled()
  })
})

// ===== FIX-040 基线验证 ======================================================
// 审计项「用户搜索内容和翻页位置在详情返回后丢失」对照当前实现为
// BASELINE_OK（N/A）：管理台成员列表没有搜索框、没有分页游标、没有
// 详情路由——listAdminUsers(signal?) 契约无任何 query 参数，全部成员
// 单页直出。不存在可丢失的搜索/翻页状态。本用例固化该结构属性：
// 卸载重进后列表完整重载，且每次查询都无过滤实参（若未来引入搜索/
// 分页/详情，必须把状态持久化到 URL，否则本用例的「无实参」断言会
// 提醒同步本防线）。

describe('FIX-040 基线：成员列表无搜索/分页/详情路由——无「返回丢上下文」面', () => {
  it('卸载重进后列表完整重载；查询不带任何过滤/游标实参', async () => {
    const first = renderAdmin()
    await screen.findByTestId('admin-user-list')
    first.unmount()

    renderAdmin()
    const list = await screen.findByTestId('admin-user-list')
    expect(within(list).getByText('alice')).toBeInTheDocument()
    expect(within(list).getByText('carol')).toBeInTheDocument()
    // listAdminUsers 每次调用只有 signal 一个实参——没有可丢失的过滤状态。
    expect(mocks.listAdminUsers.mock.calls.length).toBeGreaterThanOrEqual(2)
    for (const call of mocks.listAdminUsers.mock.calls) {
      expect(call).toHaveLength(1)
    }
  })
})

// ===== FIX-282 基线验证 ======================================================
// 审计项「清除选择器值发出空字符串而契约要求 null」对照当前实现为
// BASELINE_OK：全库审计未发现违反点——每处「空=清除」的提交路径都做
// 了 '' → null 转换（funnel 筛选 / 额度上限 / voiceURI / categoryId /
// compareWith / SaveSearchDialog.workspaceId 等）；MailSection 的
// listUuid 是唯一发 '' 的，但其契约语义就是 ''（BFF exclude_none 下
// null = 不改动，'' = 解绑，见 services/bff routers/mail.py）。本组
// 用例固化两条代表性路径的转换行为。

describe('FIX-282 基线：清除选择器值发 null（契约），不发空串', () => {
  it('漏斗方案筛选清除 → getInviteFunnel(signal, null)；全程无 \'\' 实参', async () => {
    renderAdmin()
    await screen.findByTestId('funnel-cards')
    expect(mocks.getInviteFunnel).toHaveBeenCalledWith(expect.anything(), null)
    // 等方案选项渲染完成再选择（s1 选项来自 listInviteSchemes）
    await screen.findByRole('option', { name: '新人套餐' })
    fireEvent.change(screen.getByTestId('funnel-scheme-filter'), { target: { value: 's1' } })
    await waitFor(() =>
      expect(mocks.getInviteFunnel).toHaveBeenCalledWith(expect.anything(), 's1'),
    )
    // 清除（选回「全部方案」）→ 契约 null，不是 ''
    fireEvent.change(screen.getByTestId('funnel-scheme-filter'), { target: { value: '' } })
    await waitFor(() =>
      expect(mocks.getInviteFunnel).toHaveBeenCalledWith(expect.anything(), null),
    )
    const schemeArgs = mocks.getInviteFunnel.mock.calls.map((call) => call[1])
    expect(schemeArgs).not.toContain('')
  })

  it('成员额度：AI 上限输入清空保存 → payload aiQuotaPerDay=null（非 \'\'）', async () => {
    mocks.getAdminUserQuota.mockResolvedValue({
      caps: { maxSources: 3, aiQuotaPerDay: 100 },
      backgroundPaused: false,
      backgroundPauseReason: null,
    })
    mocks.setAdminUserQuota.mockResolvedValue({
      caps: { maxSources: 3, aiQuotaPerDay: null },
    })
    renderAdmin()
    await screen.findByTestId('admin-user-list')
    fireEvent.click(screen.getByTestId('quota-open-carol'))
    const aiInput = await screen.findByTestId('quota-ai-per-day')
    fireEvent.change(aiInput, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: '保存额度' }))
    await screen.findByTestId('quota-saved-note')
    expect(mocks.setAdminUserQuota).toHaveBeenCalledWith('u3', {
      maxSources: 3,
      aiQuotaPerDay: null,
    })
  })
})

// ===== FIX-287 基线验证 ======================================================
// 审计项「受控输入在 undefined 与字符串间切换丢值」对照当前实现为
// BASELINE_OK：QuotaDialog 的输入状态恒为 string（null 上限 → ''，
// 数字 → String(n)），value 始终受控，从不在 undefined↔string 间切换。
// 本用例证明：服务端值 seeding 后输入为受控字符串、用户输入跨
// 保存重渲染存活、控制台零受控/非受控切换警告。

describe('FIX-287 基线：额度输入恒为受控字符串（无 undefined↔字符串切换）', () => {
  it('seeding 后输入受控；输入值跨保存重渲染存活；零切换警告', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    mocks.getAdminUserQuota.mockResolvedValue({
      caps: { maxSources: 3, aiQuotaPerDay: null },
      backgroundPaused: false,
      backgroundPauseReason: null,
    })
    mocks.setAdminUserQuota.mockResolvedValue({
      caps: { maxSources: 9, aiQuotaPerDay: null },
    })
    renderAdmin()
    await screen.findByTestId('admin-user-list')
    fireEvent.click(screen.getByTestId('quota-open-carol'))

    // 服务端 3 → 受控数字输入显示 3；null 的 AI 上限显示空（不是 undefined）
    const sources = await screen.findByTestId('quota-max-sources')
    expect(sources).toHaveValue(3)
    expect(screen.getByTestId('quota-ai-per-day')).toHaveValue(null)

    fireEvent.change(sources, { target: { value: '9' } })
    fireEvent.click(screen.getByRole('button', { name: '保存额度' }))
    await screen.findByTestId('quota-saved-note')
    // 保存成功 → setQueryData + 重渲染后，用户输入的 9 仍存活
    expect(screen.getByTestId('quota-max-sources')).toHaveValue(9)

    const consoleText = consoleError.mock.calls.map((args) => args.join(' ')).join('\n')
    expect(consoleText).not.toMatch(/uncontrolled/i)
    expect(consoleText).not.toMatch(/controlled input/i)
    consoleError.mockRestore()
  })
})

// FIX-028：二次认证（临时提权）弹窗的取消语义 —— 取消必须终止该次
// 敏感操作：(a) 确认中的危险动作被解除（确认对话框关闭，不留「可继续
// 执行」的半开状态）；(b) 取消时仍在途的铸造响应迟到成功也不得武装
// 令牌；(c) 取消同时解除本会话可能残留的已武装令牌。
//
// 注：jsdom 不派发表单提交（点击 submit 按钮与 fireEvent.submit 都不
// 触发 React onSubmit），经 form 的 React props 直接调用 onSubmit ——
// 与浏览器提交执行的是同一个 submit() 闭包。

type MintResult = { token: string; expiresInMinutes: number; header: string }

function submitStepUpForm(dialog: ReturnType<typeof within>): void {
  const form = dialog.getByLabelText('管理员密码').closest('form')
  expect(form).not.toBeNull()
  const props = Object.entries(form!).find(([k]) => k.startsWith('__reactProps$'))?.[1] as
    | { onSubmit?: (e: { preventDefault: () => void }) => void }
    | undefined
  expect(typeof props?.onSubmit).toBe('function')
  props!.onSubmit!({ preventDefault: () => {} })
}

const STEP_UP_403 = () =>
  new ApiError(403, 'step_up_required', '需要临时提权', null, {
    operation: 'user_paused',
    targetUserId: 'u1',
  })

async function openStepUpOverPause(): Promise<HTMLElement> {
  renderAdmin()
  await screen.findByTestId('admin-user-list')
  fireEvent.click(screen.getByRole('button', { name: '暂停' }))
  const confirmDialog = await screen.findByRole('dialog')
  fireEvent.click(within(confirmDialog).getByRole('button', { name: '暂停' }))
  return await screen.findByTestId('step-up-dialog')
}

describe('FIX-028：取消临时提权弹窗终止该次操作', () => {
  it('验证中取消 → 确认中的敏感操作被解除；迟到的铸造不武装令牌', async () => {
    mocks.pauseAdminUser.mockRejectedValue(STEP_UP_403())
    // 铸造请求挂起——用户在「验证中…」点击取消，响应之后才到达
    let resolveMint!: (v: MintResult) => void
    mocks.mintAdminStepUpToken.mockImplementation(
      () =>
        new Promise<MintResult>((resolve) => {
          resolveMint = resolve
        }),
    )
    const stepUp = await openStepUpOverPause()
    fireEvent.change(within(stepUp).getByLabelText('管理员密码'), {
      target: { value: 'pw-in-test' },
    })
    submitStepUpForm(within(stepUp))
    // 验证进行中取消
    fireEvent.click(within(stepUp).getByText('取消'))
    expect(screen.queryByTestId('step-up-dialog')).not.toBeInTheDocument()
    // 迟到的铸造成功也绝不能武装令牌
    resolveMint({ token: 'late-token-after-cancel', expiresInMinutes: 5, header: 'X-Lumi-Step-Up' })
    // 让迟到的铸造完整落定（lib 先武装、取消路径再解除——此后必须仍为空）
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(getStepUpToken()).toBeNull()
    // 该次操作被终止：确认对话框关闭，敏感端点没有被再次调用
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(mocks.pauseAdminUser).toHaveBeenCalledTimes(1)
  })

  it('取消也解除本会话残留的已武装令牌（下一次敏感请求重新走 403 流程）', async () => {
    // 预置：上一次铸造留下的未消费令牌仍在本会话内存里
    mocks.mintAdminStepUpToken.mockResolvedValue({
      token: 'stale-armed-token',
      expiresInMinutes: 5,
      header: 'X-Lumi-Step-Up',
    })
    await mintAdminStepUp('pw-in-test', { operation: 'user_paused', targetUserId: 'u1' })
    expect(getStepUpToken()).toBe('stale-armed-token')

    // 新一轮敏感操作 403 → 提权弹窗；这次用户选择取消
    mocks.pauseAdminUser.mockRejectedValue(STEP_UP_403())
    mocks.mintAdminStepUpToken.mockImplementation(
      () =>
        new Promise<MintResult>(() => {
          // 永不落定——用户在验证中放弃
        }),
    )
    const stepUp = await openStepUpOverPause()
    fireEvent.change(within(stepUp).getByLabelText('管理员密码'), {
      target: { value: 'pw-in-test' },
    })
    fireEvent.click(within(stepUp).getByText('取消'))
    expect(getStepUpToken()).toBeNull()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
