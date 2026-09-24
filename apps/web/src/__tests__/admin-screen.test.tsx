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
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
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
    { name: 'sqlite', configured: true, status: 'healthy', latencyMs: null },
    { name: 'freshrss', configured: true, status: 'healthy', latencyMs: 23 },
    { name: 'rsshub', configured: false, status: 'unconfigured', latencyMs: null },
    { name: 'obsidian', configured: false, status: 'unconfigured', latencyMs: null },
    { name: 'webdav', configured: false, status: 'unconfigured', latencyMs: null },
    { name: 'ai', configured: true, status: 'configured', latencyMs: null },
    { name: 'imap', configured: false, status: 'unconfigured', latencyMs: null },
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
