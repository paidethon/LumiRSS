/** FIX-051 / FIX-054 / FIX-056 / FIX-044 / FIX-060 — 管理台基线守卫。
 *
 * R2 FIX 清扫批次裁决（基线 fb5418b）：五项在现有实现中已满足，本文件
 * 把各自的裁决依据钉成廉价守卫，防回归：
 *
 * - FIX-051（拆分）：AdminScreen 已按业务区拆成内聚 section 组件
 *   （同文件多组件，每区自带查询与数据依赖），页面骨架只做组合——
 *   裁决 BASELINE_OK；守卫钉定「区块组件清单 + 各自数据源 + 骨架组合」。
 * - FIX-054（危险操作视觉权重）：行内危险操作全部 ghost 变体、确认
 *   对话框确认键 danger 变体、主按钮位置只给建设性操作——BASELINE_OK。
 * - FIX-056（空列表/权限不足/服务故障三态）：区块各自区分 pending
 *   （骨架 + aria-busy）/ error（role=alert）/ empty（三级文字），
 *   页面级 403 是独立提示页——BASELINE_OK。
 * - FIX-044（邀请列表刷新）：创建/撤销失效 invites+funnel（已有测试），
 *   撤销也重取列表本文件钉定；服务端撤销后 token 立即失效由
 *   redeem_invite 的 pre-check + 条件 UPDATE 双重保证（accounts_store）。
 * - FIX-060（部署进度）：阶段状态只转述 ./lumirss update 写下的真实
 *   执行结果（running/ok/failed/interrupted），result 仅 success/failed
 *   才落「成功/失败」文案；「进行中」绝不显示为「完成」。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type {
  AdminAuditEntry,
  AdminDeployStatus,
  AdminInvite,
  AdminSystemInfo,
  AdminUser,
} from '../api/client'
import AdminScreen from '../components/admin/AdminScreen'
import { useAuthStore, type AuthIdentity } from '../store/auth'

const adminSource = readFileSync(
  resolve(__dirname, '../components/admin/AdminScreen.tsx'),
  'utf-8',
)

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
  getAdminUserQuota: vi.fn(),
  setAdminUserQuota: vi.fn(),
  getAdminCapacity: vi.fn(),
  getAdminUpgradePreview: vi.fn(),
  getAdminDeployStatus: vi.fn(),
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
    getAdminUserQuota: mocks.getAdminUserQuota,
    setAdminUserQuota: mocks.setAdminUserQuota,
    getAdminCapacity: mocks.getAdminCapacity,
    getAdminUpgradePreview: mocks.getAdminUpgradePreview,
    getAdminDeployStatus: mocks.getAdminDeployStatus,
  }
})

const OWNER: AuthIdentity = { userId: 'u1', username: 'alice', role: 'owner' }
const MEMBER: AuthIdentity = { userId: 'u2', username: 'bob', role: 'member' }
const NOW_MS = Date.now()
const ISO = (offsetMs: number) => new Date(NOW_MS + offsetMs).toISOString()

const USERS: AdminUser[] = [
  { id: 'u1', username: 'alice', role: 'owner', status: 'active', displayName: null, schemeName: null, createdAt: ISO(-86_400_000) },
  { id: 'u3', username: 'carol', role: 'member', status: 'active', displayName: null, schemeName: null, createdAt: ISO(-3_600_000) },
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

const SYSTEM: AdminSystemInfo = {
  version: '0.2.0',
  commit: '',
  python: '3.12.1',
  uptimeS: 100,
  process: { rssBytes: 1, peakRssBytes: 2, cpuTimeS: 0.1 },
  counts: {
    users: 2,
    activeUsers: 2,
    invites: 1,
    freshrssPoolReady: 0,
    freshrssPoolAssigned: 0,
    sessions: 1,
    feeds: 0,
    entriesIndexed: 0,
    libraryItems: 0,
  },
  services: [],
  tasks: [],
}

const AUDIT: AdminAuditEntry[] = []

function renderAdmin() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AdminScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  useAuthStore.setState({ status: 'authenticated', mode: 'session', identity: OWNER })
  vi.clearAllMocks()
  mocks.listAdminUsers.mockResolvedValue(USERS)
  mocks.listAdminInvites.mockResolvedValue(INVITES)
  mocks.getFreshRssPool.mockResolvedValue({ ready: 0, held: 0, assigned: 0, members: [] })
  mocks.getAdminSystem.mockResolvedValue(SYSTEM)
  mocks.listAdminAudit.mockResolvedValue(AUDIT)
  mocks.listInviteSchemes.mockResolvedValue([])
  mocks.getInviteFunnel.mockResolvedValue({
    totals: { generated: 1, pending: 1, activated: 0, expired: 0, revoked: 0, failedActivation: 0 },
    byScheme: [],
  })
  mocks.getRegistrationPolicy.mockResolvedValue({ allowPublicRegistration: false, updatedAt: null, updatedBy: null })
  mocks.getAdminCapacity.mockResolvedValue({
    pool: { ready: 0, held: 0, assigned: 0 },
    invites: { pending: 1, held: 0 },
    users: { active: 2, paused: 0 },
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
  mocks.revokeAdminInvite.mockResolvedValue(undefined)
})

// ===== FIX-051：业务区拆分结构 ==============================================

describe('FIX-051: AdminScreen 按业务区拆分为内聚 section 组件', () => {
  const SECTIONS = [
    'MembersSection',
    'InvitesSection',
    'SchemesSection',
    'RegistrationPolicySection',
    'FunnelSection',
    'PoolSection',
    'CapacitySection',
    'UpgradePreviewSection',
    'DeployStatusSection',
    'RollbackReadinessSection',
    'SystemSection',
  ] as const

  it('每个业务区是独立命名的函数组件', () => {
    const missing = SECTIONS.filter((name) => !adminSource.includes(`function ${name}(`))
    expect(missing).toEqual([])
  })

  it('每个区块自带数据依赖（自己的查询），不共享可变快照', () => {
    // 区块与它的数据源必须成对出现（各管各的 queryKey）。
    const pairs: [string, RegExp][] = [
      ['MembersSection', /listAdminUsers\(signal\)/],
      ['InvitesSection', /listAdminInvites\(signal\)/],
      ['SchemesSection', /listInviteSchemes\(signal\)/],
      ['FunnelSection', /getInviteFunnel\(signal/],
      ['PoolSection', /getFreshRssPool\(signal\)/],
      ['CapacitySection', /getAdminCapacity\(signal\)/],
      ['UpgradePreviewSection', /getAdminUpgradePreview\(signal\)/],
      ['DeployStatusSection', /getAdminDeployStatus\(signal\)/],
      ['RollbackReadinessSection', /getAdminRollbackReadiness\(signal\)/],
      ['SystemSection', /getAdminSystem\(signal\)/],
    ]
    for (const [section, dataSource] of pairs) {
      const start = adminSource.indexOf(`function ${section}(`)
      expect(start, section).toBeGreaterThanOrEqual(0)
      const next = adminSource.indexOf('\nfunction ', start + 1)
      const body = adminSource.slice(start, next === -1 ? adminSource.length : next)
      expect(body, `${section} 应自带 ${dataSource}`).toMatch(dataSource)
    }
  })

  it('页面骨架只组合区块（不自渲染业务行）', () => {
    for (const name of SECTIONS) {
      expect(adminSource).toContain(`<${name}${name === 'MembersSection' || name === 'InvitesSection' || name === 'SchemesSection' ? ' onConfirm' : ' />'}`)
    }
  })
})

// ===== FIX-054：危险操作视觉权重 ============================================

describe('FIX-054: 危险操作不占主按钮位（行内 ghost、确认键 danger）', () => {
  it('确认对话框确认键使用 danger 变体', () => {
    expect(adminSource).toMatch(/variant="danger"\s*\n\s*disabled=\{confirmPending\}/)
  })

  it('行内危险操作按钮（暂停/撤销会话/重置密码/撤销/删除）不是主按钮', async () => {
    renderAdmin()
    await screen.findByTestId('admin-user-list')
    // 成员有两行——同类按钮出现多次时逐一断言。
    const destructiveLabels = ['暂停', '撤销会话', '重置密码', '撤销']
    for (const label of destructiveLabels) {
      for (const button of screen.getAllByRole('button', { name: label })) {
        expect(button.className, label).not.toContain('bg-[var(--lumi-accent)]')
        expect(button.className, label).toContain('bg-transparent')
      }
    }
    // 方案删除（Trash2 行内）同样非主按钮——方案列表为空时跳过。
    const remove = screen.queryByRole('button', { name: '删除' })
    if (remove !== null) {
      expect(remove.className).not.toContain('bg-[var(--lumi-accent)]')
    }
  })

  it('确认对话框实际渲染 danger 键、主键位（accent）不在对话框中', async () => {
    renderAdmin()
    await screen.findByTestId('admin-invite-list')
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    const dialog = await screen.findByRole('dialog')
    const confirm = within(dialog).getByRole('button', { name: '撤销邀请' })
    expect(confirm.className).toContain('bg-[var(--lumi-danger)]')
    expect(confirm.className).not.toContain('bg-[var(--lumi-accent)]')
    within(dialog).getByRole('button', { name: '取消' })
  })
})

// ===== FIX-056：空列表 / 权限不足 / 服务故障 三态分离 ========================

describe('FIX-056: 邀请列表空态/错误态/加载态互不混淆', () => {
  it('空列表 → 专属空态文案，无 alert', async () => {
    mocks.listAdminInvites.mockResolvedValue([])
    renderAdmin()
    expect(await screen.findByText('还没有邀请记录。')).toBeInTheDocument()
    const section = screen.getByLabelText('邀请管理')
    expect(within(section).queryByRole('alert')).toBeNull()
  })

  it('服务故障 → role=alert 诚实报错，不显示空态文案', async () => {
    mocks.listAdminInvites.mockRejectedValue(new Error('upstream down'))
    renderAdmin()
    const section = screen.getByLabelText('邀请管理')
    expect(await within(section).findByRole('alert')).toBeInTheDocument()
    expect(within(section).queryByText('还没有邀请记录。')).toBeNull()
  })

  it('加载中 → 骨架（aria-busy），无 alert 无空态', async () => {
    mocks.listAdminInvites.mockReturnValue(new Promise(() => {}))
    renderAdmin()
    const section = screen.getByLabelText('邀请管理')
    await waitFor(() => {
      expect(section.querySelector('[aria-busy="true"]')).not.toBeNull()
    })
    expect(within(section).queryByRole('alert')).toBeNull()
    expect(within(section).queryByText('还没有邀请记录。')).toBeNull()
  })

  it('权限不足 → 页面级独立 403 提示（不渲染任何区块）', async () => {
    useAuthStore.setState({ identity: MEMBER })
    renderAdmin()
    expect(await screen.findByTestId('admin-forbidden')).toHaveTextContent('没有访问权限')
    expect(screen.queryByTestId('admin-invite-list')).toBeNull()
    expect(screen.queryByTestId('admin-user-list')).toBeNull()
  })
})

// ===== FIX-044：撤销后列表与派生视图刷新 ====================================

describe('FIX-044: 撤销邀请后列表立即重取（旧链接即刻台账化失效）', () => {
  it('撤销成功 → listAdminInvites 重取（台账翻新，撤销键消失于重取结果）', async () => {
    renderAdmin()
    await screen.findByTestId('admin-invite-list')
    const callsAfterMount = mocks.listAdminInvites.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: '撤销邀请' }))
    await waitFor(() => {
      expect(mocks.listAdminInvites.mock.calls.length).toBeGreaterThan(callsAfterMount)
    })
  })
})

// ===== FIX-060：部署阶段状态来自真实执行结果 ================================

describe('FIX-060: 升级进度只转述真实阶段结果（进行中 ≠ 完成）', () => {
  it('running 阶段显示「进行中」，ok 阶段显示「完成」，不把未完成当成功', async () => {
    const deploy: AdminDeployStatus = {
      available: true,
      reason: null,
      deploy: {
        imageTag: 'abc1234cafe',
        startedAt: ISO(-600_000),
        updatedAt: ISO(-60_000),
        stages: {
          backup: { status: 'ok', startedAt: ISO(-600_000), finishedAt: ISO(-540_000), note: null },
          health: { status: 'running', startedAt: ISO(-30_000), finishedAt: null, note: null },
        },
        result: null,
      },
    }
    mocks.getAdminDeployStatus.mockResolvedValue(deploy)
    renderAdmin()
    const body = await screen.findByTestId('deploy-status-body')
    expect(screen.getByTestId('deploy-stage-backup')).toHaveTextContent('完成')
    expect(screen.getByTestId('deploy-stage-health')).toHaveTextContent('进行中')
    // 请求已接受 / 进行中绝不显示为升级成功。
    expect(within(body).queryByText('升级成功')).toBeNull()
  })

  it('result 只在执行结果为 success 时才落「升级成功」', async () => {
    const deploy: AdminDeployStatus = {
      available: true,
      reason: null,
      deploy: {
        imageTag: null,
        startedAt: ISO(-600_000),
        updatedAt: ISO(-10_000),
        stages: {},
        result: { status: 'failed', finishedAt: ISO(-10_000) },
      },
    }
    mocks.getAdminDeployStatus.mockResolvedValue(deploy)
    renderAdmin()
    const body = await screen.findByTestId('deploy-status-body')
    expect(screen.getByTestId('deploy-status-result')).toHaveTextContent('升级失败')
    expect(within(body).queryByText('升级成功')).toBeNull()
  })
})
