/** 管理台交付面 Web 测试 — N191 额度编辑器 / N192 容量卡 / N195 升级预览
 * 卡 / N196 升级进度（严格只读，负向断言无执行控件）。
 *
 * 与 admin-screen.test.tsx 同一约定：vi.mock('../api/client')，BFF 不
 * 参与测试，直接给归一后的 DTO 专注 UI 行为。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  type AdminAuditEntry,
  type AdminCapacity,
  type AdminDeployStatus,
  type AdminRollbackReadiness,
  type AdminInvite,
  type AdminSystemInfo,
  type AdminUpgradePreview,
  type AdminUser,
  type AdminUserQuota,
  type InviteFunnel,
  type InviteScheme,
} from '../api/client'
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
  clearAdminUserQuota: vi.fn(),
  pauseAdminUserBackground: vi.fn(),
  resumeAdminUserBackground: vi.fn(),
  getAdminCapacity: vi.fn(),
  getAdminUpgradePreview: vi.fn(),
  getAdminDeployStatus: vi.fn(),
  getAdminRollbackReadiness: vi.fn(),
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
    clearAdminUserQuota: mocks.clearAdminUserQuota,
    pauseAdminUserBackground: mocks.pauseAdminUserBackground,
    resumeAdminUserBackground: mocks.resumeAdminUserBackground,
    getAdminCapacity: mocks.getAdminCapacity,
    getAdminUpgradePreview: mocks.getAdminUpgradePreview,
    getAdminDeployStatus: mocks.getAdminDeployStatus,
    getAdminRollbackReadiness: mocks.getAdminRollbackReadiness,
  }
})

const OWNER: AuthIdentity = { userId: 'u1', username: 'alice', role: 'owner' }

const NOW_MS = Date.now()
const ISO = (offsetMs: number) => new Date(NOW_MS + offsetMs).toISOString()

const USERS: AdminUser[] = [
  { id: 'u1', username: 'alice', role: 'owner', status: 'active', displayName: '运营者', schemeName: null, createdAt: ISO(-86_400_000) },
  { id: 'u3', username: 'carol', role: 'member', status: 'active', displayName: null, schemeName: null, createdAt: ISO(-3_600_000) },
]

const INVITES: AdminInvite[] = []
const SCHEMES: InviteScheme[] = []
const AUDIT: AdminAuditEntry[] = []
const FUNNEL: InviteFunnel = {
  totals: { generated: 0, pending: 0, activated: 0, expired: 0, revoked: 0, failedActivation: 0 },
  byScheme: [],
}
const SYSTEM: AdminSystemInfo = {
  version: '0.2.0',
  commit: 'abcdef1234',
  python: '3.12.0',
  uptimeS: 60,
  process: { rssBytes: 1, peakRssBytes: 2, cpuTimeS: 0.1 },
  counts: {
    users: 2, activeUsers: 2, invites: 0, freshrssPoolReady: 0,
    freshrssPoolAssigned: 0, sessions: 0, feeds: 0, entriesIndexed: 0, libraryItems: 0,
  },
  services: [],
  tasks: [],
}

const CAPACITY: AdminCapacity = {
  pool: { ready: 1, held: 0, assigned: 1 },
  invites: { pending: 3, held: 0 },
  users: { active: 2, paused: 0 },
  lowCapacity: true,
}

const PREVIEW_OK: AdminUpgradePreview = {
  available: true,
  reason: null,
  currentVersion: '0.2.0',
  targetVersion: '0.3.0',
  newMigrations: ['0115_n191_user_quotas.sql', '0116_n193_background_pause.sql'],
  minCompat: '0.1.0',
  blocked: false,
  blockedReason: null,
}

const QUOTA_CAROL: AdminUserQuota = {
  userId: 'u3',
  caps: { maxSources: 5, aiQuotaPerDay: null },
  backgroundPaused: false,
  backgroundPauseReason: null,
  updatedAt: null,
  updatedBy: null,
}

const DEPLOY_RUNNING: AdminDeployStatus = {
  available: true,
  reason: null,
  deploy: {
    imageTag: 'abcdef123456',
    startedAt: ISO(-120_000),
    updatedAt: ISO(-30_000),
    stages: {
      backup: { status: 'ok', startedAt: ISO(-120_000), finishedAt: ISO(-90_000), note: null },
      pull: { status: 'running', startedAt: ISO(-90_000), finishedAt: null, note: null },
    },
    result: null,
  },
}

const ROLLBACK_NOT_READY: AdminRollbackReadiness = {
  canRollback: false,
  previousImage: { state: 'present', tag: 'v1.2.2', reason: null },
  backup: {
    state: 'unverified',
    name: 'lumirss-20260925T000000Z.backup',
    reason: '校验未通过（见 findings）',
    verifyOk: false,
    findings: { checksumOk: false, manifestCountsMatch: true, readable: true, versionCompatible: true },
  },
  schema: { current: 130, backup: 122, unchanged: false },
  dbDowngrade: 'SQLite 迁移只向前：无法降级。',
  note: '本检查只读。回滚由运维侧 ./lumirss rollback 执行——这里没有任何执行控件。',
}

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
  mocks.listInviteSchemes.mockResolvedValue(SCHEMES)
  mocks.getInviteFunnel.mockResolvedValue(FUNNEL)
  mocks.getRegistrationPolicy.mockResolvedValue({ allowPublicRegistration: false, updatedAt: null, updatedBy: null })
  mocks.getAdminCapacity.mockResolvedValue(CAPACITY)
  mocks.getAdminUpgradePreview.mockResolvedValue(PREVIEW_OK)
  mocks.getAdminDeployStatus.mockResolvedValue(DEPLOY_RUNNING)
  mocks.getAdminRollbackReadiness.mockResolvedValue(ROLLBACK_NOT_READY)
  mocks.getAdminUserQuota.mockResolvedValue(QUOTA_CAROL)
  mocks.setAdminUserQuota.mockImplementation((_userId: string, caps: { maxSources: number | null }) =>
    Promise.resolve({ ...QUOTA_CAROL, caps, updatedAt: ISO(0), updatedBy: 'u1' }),
  )
  mocks.clearAdminUserQuota.mockResolvedValue({ ...QUOTA_CAROL, caps: { maxSources: null, aiQuotaPerDay: null } })
})

// ===== N192 容量卡 ==========================================================

describe('N192 邀请容量仪表卡', () => {
  it('渲染真实计数 + 低容量警示（ready+held < pending）', async () => {
    renderAdmin()
    const ready = await screen.findByTestId('capacity-ready')
    expect(ready).toHaveTextContent('1')
    expect(screen.getByTestId('capacity-pending')).toHaveTextContent('3')
    expect(await screen.findByTestId('capacity-warning')).toHaveTextContent('容量不足')
  })

  it('容量充足时不渲染警示', async () => {
    mocks.getAdminCapacity.mockResolvedValue({ ...CAPACITY, lowCapacity: false })
    renderAdmin()
    const section = await screen.findByTestId('admin-capacity')
    await waitFor(() => expect(within(section).getByTestId('capacity-ready')).toBeInTheDocument())
    await waitFor(() => expect(screen.queryByTestId('capacity-warning')).not.toBeInTheDocument())
  })
})

// ===== N195 升级预览卡 ======================================================

describe('N195 升级影响预览卡', () => {
  it('清单未配置 → 诚实说明，不编造预览', async () => {
    mocks.getAdminUpgradePreview.mockResolvedValue({
      ...PREVIEW_OK,
      available: false,
      reason: 'LUMIRSS_RELEASE_MANIFEST is not configured.',
    })
    renderAdmin()
    const note = await screen.findByTestId('upgrade-preview-unavailable')
    expect(note).toHaveTextContent('LUMIRSS_RELEASE_MANIFEST')
  })

  it('可升级 → 目标版本 + 迁移清单 + 未发现不兼容项', async () => {
    renderAdmin()
    const body = await screen.findByTestId('upgrade-preview-body')
    expect(within(body).getByTestId('upgrade-preview-migrations')).toHaveTextContent('2 个')
    expect(within(body).getByTestId('upgrade-preview-migration-list')).toHaveTextContent('0115_n191_user_quotas.sql')
    expect(within(body).getByTestId('upgrade-preview-ok')).toBeInTheDocument()
    expect(screen.queryByTestId('upgrade-preview-blocked')).not.toBeInTheDocument()
  })

  it('不兼容 → blocked 原因可见，成功语消失', async () => {
    mocks.getAdminUpgradePreview.mockResolvedValue({
      ...PREVIEW_OK,
      blocked: true,
      blockedReason: 'Target version 0.1.0 is OLDER than the current 0.2.0.',
    })
    renderAdmin()
    const blocked = await screen.findByTestId('upgrade-preview-blocked')
    expect(blocked).toHaveTextContent('OLDER')
    expect(screen.queryByTestId('upgrade-preview-ok')).not.toBeInTheDocument()
  })
})

// ===== N196 升级进度（严格只读）=============================================

describe('N196 升级任务进度（只读）', () => {
  it('渲染阶段状态与结果，且卡内没有任何执行控件（负向断言）', async () => {
    renderAdmin()
    const section = await screen.findByTestId('admin-deploy-status')
    expect(await screen.findByTestId('deploy-stage-backup')).toHaveTextContent('完成')
    await waitFor(() => expect(screen.getByTestId('deploy-stage-pull')).toHaveTextContent('进行中'))
    // 负向：进度卡内零按钮 —— 没有「开始升级/重试/回滚」任何执行控件。
    expect(within(section).queryAllByRole('button')).toHaveLength(0)
  })

  it('未配置进度文件 → 诚实说明', async () => {
    mocks.getAdminDeployStatus.mockResolvedValue({
      available: false,
      reason: 'LUMIRSS_DEPLOY_STATUS_FILE is not configured.',
      deploy: null,
    })
    renderAdmin()
    const note = await screen.findByTestId('deploy-status-unavailable')
    expect(note).toHaveTextContent('LUMIRSS_DEPLOY_STATUS_FILE')
  })
})

// ===== N197 回滚就绪检查（只读要素清单）=====================================

describe('N197 回滚就绪检查（只读）', () => {
  it('要素清单：前镜像 / 备份 / schema 状态与 dbDowngrade 诚实说明', async () => {
    renderAdmin()
    const section = await screen.findByTestId('admin-rollback-readiness')
    expect(await within(section).findByTestId('rollback-element-previous-image')).toHaveTextContent('v1.2.2')
    expect(within(section).getByTestId('rollback-element-backup')).toHaveTextContent('校验未通过')
    expect(within(section).getByTestId('rollback-element-schema')).toHaveTextContent('不一致')
    expect(within(section).getByTestId('rollback-db-downgrade')).toHaveTextContent('只向前')
    expect(within(section).getByTestId('rollback-verdict')).toHaveTextContent('当前不可回滚')
  })

  it('要素齐全 → 「可以回滚（由运维侧执行）」，但卡内零按钮（负向断言）', async () => {
    mocks.getAdminRollbackReadiness.mockResolvedValue({
      ...ROLLBACK_NOT_READY,
      canRollback: true,
      backup: {
        state: 'verified',
        name: 'lumirss-20260925T000000Z.backup',
        reason: null,
        verifyOk: true,
        findings: { checksumOk: true, manifestCountsMatch: true, readable: true, versionCompatible: true },
      },
      schema: { current: 130, backup: 130, unchanged: true },
    })
    renderAdmin()
    const section = await screen.findByTestId('admin-rollback-readiness')
    expect(await within(section).findByTestId('rollback-verdict')).toHaveTextContent('可以回滚')
    // 负向：清单卡内零按钮 —— 永远没有一键回滚执行控件。
    expect(within(section).queryAllByRole('button')).toHaveLength(0)
  })
})

// ===== N191 额度编辑器 + 后台任务暂停 =======================================

describe('N191 成员额度编辑器（成员行）', () => {
  it('打开编辑器回填当前策略，保存走 PUT（空 = 清除该上限）', async () => {
    renderAdmin()
    fireEvent.click(await screen.findByTestId('quota-open-carol'))
    const form = await screen.findByTestId('quota-form')
    const sources = within(form).getByTestId('quota-max-sources') as HTMLInputElement
    await waitFor(() => expect(sources.value).toBe('5'))
    fireEvent.change(sources, { target: { value: '8' } })
    fireEvent.submit(form)
    await waitFor(() =>
      expect(mocks.setAdminUserQuota).toHaveBeenCalledWith('u3', { maxSources: 8, aiQuotaPerDay: null }),
    )
  })

  it('清除策略走 DELETE', async () => {
    renderAdmin()
    fireEvent.click(await screen.findByTestId('quota-open-carol'))
    fireEvent.click(await screen.findByTestId('quota-clear'))
    await waitFor(() => expect(mocks.clearAdminUserQuota).toHaveBeenCalledWith('u3'))
  })

  it('后台任务暂停需要原因，恢复一键（N193）', async () => {
    // 暂停成功后编辑器会重取策略行：第一次（打开）返回未暂停，
    // 之后（暂停成功的 refetch）返回已暂停——mock 按序给出，无竞态。
    mocks.getAdminUserQuota
      .mockResolvedValueOnce(QUOTA_CAROL)
      .mockResolvedValue({ ...QUOTA_CAROL, backgroundPaused: true, backgroundPauseReason: '夜间降负载' })
    renderAdmin()
    fireEvent.click(await screen.findByTestId('quota-open-carol'))
    const reason = await screen.findByTestId('background-reason')
    fireEvent.change(reason, { target: { value: '夜间降负载' } })
    fireEvent.submit(reason.closest('form') as HTMLFormElement)
    await waitFor(() => expect(mocks.pauseAdminUserBackground).toHaveBeenCalledWith('u3', '夜间降负载'))

    // 暂停后编辑器显示原因 + 恢复按钮。
    mocks.resumeAdminUserBackground.mockResolvedValue(undefined)
    fireEvent.click(await screen.findByTestId('background-resume', {}, { timeout: 3000 }))
    await waitFor(() => expect(mocks.resumeAdminUserBackground).toHaveBeenCalledWith('u3'))
  })

  it('owner 行不显示额度表单与后台暂停控件', async () => {
    renderAdmin()
    fireEvent.click(await screen.findByTestId('quota-open-alice'))
    expect(await screen.findByText(/运营者账号不参与成员额度/)).toBeInTheDocument()
    expect(screen.queryByTestId('quota-form')).not.toBeInTheDocument()
    expect(screen.queryByTestId('background-pause-area')).not.toBeInTheDocument()
    expect(mocks.getAdminUserQuota).not.toHaveBeenCalled()
  })
})

describe('新端点错误态（403 诚实转述）', () => {
  it('容量查询 403 → 错误文案可见', async () => {
    mocks.getAdminCapacity.mockRejectedValue(new ApiError(403, 'forbidden', 'Administrator role required.'))
    renderAdmin()
    const section = await screen.findByTestId('admin-capacity')
    await waitFor(() => expect(within(section).getByRole('alert')).toBeInTheDocument())
  })
})
