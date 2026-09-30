/** FIX-055 — 管理台统计卡与列表共用同一刷新源（失效联动）。
 *
 * 问题：成员列表（['admin','users']）、邀请列表（['admin','invites']）、
 * FreshRSS 池（['admin','pool']）各自的 mutation 只失效自己的查询，
 * 而容量卡（['admin','capacity']，含活跃成员/待激活邀请/池计数）与
 * 系统计数（['admin','system']，成员/邀请/池计数）不随之失效——
 * 管理员暂停一个成员后，列表立即显示「已暂停」，容量卡的「活跃成员」
 * 与系统面板的「成员（活跃）」仍是旧数字（两处口径不同步）。
 *
 * 契约（红先行钉定）：改变服务端计数的 mutation 成功后，必须同时失效
 * ['admin','capacity'] 与 ['admin','system']（及审计尾 ['admin','audit']，
 * 数字变化同样应出现在「最近动态」）。指标口径本身由服务端单一来源
 * （GET /admin/capacity、GET /admin/system），前端不自创。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdminAuditEntry, AdminInvite, AdminSystemInfo, AdminUser } from '../api/client'
import AdminScreen from '../components/admin/AdminScreen'
import { useAuthStore, type AuthIdentity } from '../store/auth'

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
const NOW_MS = Date.now()
const ISO = (offsetMs: number) => new Date(NOW_MS + offsetMs).toISOString()

const USERS: AdminUser[] = [
  { id: 'u1', username: 'alice', role: 'owner', status: 'active', displayName: null, schemeName: null, createdAt: ISO(-86_400_000) },
  { id: 'u3', username: 'carol', role: 'member', status: 'paused', displayName: null, schemeName: null, createdAt: ISO(-3_600_000) },
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
    activeUsers: 1,
    invites: 1,
    freshrssPoolReady: 2,
    freshrssPoolAssigned: 1,
    sessions: 4,
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
  mocks.getFreshRssPool.mockResolvedValue({
    ready: 2,
    held: 0,
    assigned: 1,
    members: [],
  })
  mocks.getAdminSystem.mockResolvedValue(SYSTEM)
  mocks.listAdminAudit.mockResolvedValue(AUDIT)
  mocks.listInviteSchemes.mockResolvedValue([])
  mocks.getInviteFunnel.mockResolvedValue({
    totals: { generated: 1, pending: 1, activated: 0, expired: 0, revoked: 0, failedActivation: 0 },
    byScheme: [],
  })
  mocks.getRegistrationPolicy.mockResolvedValue({
    allowPublicRegistration: false,
    updatedAt: null,
    updatedBy: null,
  })
  mocks.getAdminCapacity.mockResolvedValue({
    pool: { ready: 2, held: 0, assigned: 1 },
    invites: { pending: 1, held: 0 },
    users: { active: 1, paused: 1 },
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
  mocks.resumeAdminUser.mockResolvedValue(undefined)
  mocks.revokeAdminInvite.mockResolvedValue(undefined)
  mocks.registerFreshRssPool.mockResolvedValue(undefined)
})

describe('FIX-055: 计数型 mutation 后容量卡与系统计数同源刷新', () => {
  it('恢复成员 → 容量卡（活跃成员）与系统计数重取', async () => {
    renderAdmin()
    const cards = await screen.findByTestId('capacity-cards')
    expect(cards).toHaveTextContent('活跃成员')
    const capacityAfterMount = mocks.getAdminCapacity.mock.calls.length
    const systemAfterMount = mocks.getAdminSystem.mock.calls.length
    expect(capacityAfterMount).toBeGreaterThan(0)
    expect(systemAfterMount).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: '恢复' }))
    await waitFor(() => {
      expect(mocks.resumeAdminUser).toHaveBeenCalledWith('u3')
    })
    await waitFor(
      () => {
        expect(mocks.getAdminCapacity.mock.calls.length).toBeGreaterThan(capacityAfterMount)
        expect(mocks.getAdminSystem.mock.calls.length).toBeGreaterThan(systemAfterMount)
      },
      { timeout: 3_000 },
    )
  })

  it('撤销邀请 → 容量卡（待激活邀请）与系统计数重取', async () => {
    renderAdmin()
    await screen.findByTestId('capacity-cards')
    const capacityAfterMount = mocks.getAdminCapacity.mock.calls.length
    const systemAfterMount = mocks.getAdminSystem.mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: '撤销邀请' }))
    await waitFor(
      () => {
        expect(mocks.getAdminCapacity.mock.calls.length).toBeGreaterThan(capacityAfterMount)
        expect(mocks.getAdminSystem.mock.calls.length).toBeGreaterThan(systemAfterMount)
      },
      { timeout: 3_000 },
    )
  })

  it('登记 FreshRSS 入池 → 容量卡（池计数）与系统计数重取', async () => {
    renderAdmin()
    await screen.findByTestId('pool-counts')
    const capacityAfterMount = mocks.getAdminCapacity.mock.calls.length
    const systemAfterMount = mocks.getAdminSystem.mock.calls.length

    fireEvent.change(screen.getByLabelText('FreshRSS 用户名'), { target: { value: 'frss-frank' } })
    fireEvent.change(screen.getByLabelText('FreshRSS 地址'), { target: { value: 'https://freshrss.example.com' } })
    fireEvent.change(screen.getByLabelText('API 密码（只写）'), { target: { value: 'x'.repeat(24) } })
    fireEvent.click(screen.getByRole('button', { name: '登记入池' }))
    await waitFor(
      () => {
        expect(mocks.getAdminCapacity.mock.calls.length).toBeGreaterThan(capacityAfterMount)
        expect(mocks.getAdminSystem.mock.calls.length).toBeGreaterThan(systemAfterMount)
      },
      { timeout: 3_000 },
    )
  })
})
