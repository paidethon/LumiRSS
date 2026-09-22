/** 管理台（/admin → AdminScreen）Web 测试 — 0067。
 *
 * 覆盖：member 访问 403 提示页、成员列表（角色/状态徽标 + 暂停/
 * 恢复/撤销会话/重置密码，危险操作确认对话框）、重置密码一次性
 * 链接展示、邀请创建（一次性完整链接 + 复制）/ 列表 / 撤销、
 * FreshRSS 池状态（计数 + 登记 + 成员绑定列表）。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）；
 * BFF 不参与测试。admin 列表的 snake_case/epoch 秒形状由 client
 * 归一，这里用真实 BFF 形状的 fixture 验证归一与渲染。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type AdminInvite, type AdminUser } from '../api/client'
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
  { id: 'u1', username: 'alice', role: 'owner', status: 'active', displayName: '运营者', createdAt: ISO(-86_400_000) },
  { id: 'u3', username: 'carol', role: 'member', status: 'paused', displayName: null, createdAt: ISO(-3_600_000) },
]

const INVITES: AdminInvite[] = [
  {
    id: 'i1',
    kind: 'signup',
    label: '给 dave 的邀请',
    targetUsername: null,
    createdAt: ISO(-3_600_000),
    expiresAt: ISO(72 * 3_600_000),
    usedAt: null,
    revokedAt: null,
  },
]

function renderAdmin() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
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
    assigned: 1,
    members: [
      { id: 'u2', username: 'bob', bound: true, boundTo: 'frss-bob' },
      { id: 'u9', username: 'erin', bound: false, boundTo: null },
    ],
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
  })

  it('身份未核实 → 显示核实中（不发管理查询前的越权渲染）', () => {
    useAuthStore.setState({ identity: null })
    renderAdmin()
    expect(screen.getByRole('status')).toHaveTextContent('正在核实身份')
  })
})

describe('成员列表', () => {
  it('渲染角色/状态徽标', async () => {
    renderAdmin()
    const list = await screen.findByTestId('admin-user-list')
    expect(list).toHaveTextContent('alice')
    expect(list).toHaveTextContent('运营者')
    expect(list).toHaveTextContent('正常')
    expect(list).toHaveTextContent('carol')
    expect(list).toHaveTextContent('已暂停')
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
})

describe('FreshRSS 池', () => {
  it('显示 ready/assigned 计数与成员绑定状态', async () => {
    renderAdmin()
    const counts = await screen.findByTestId('pool-counts')
    expect(counts).toHaveTextContent('2')
    expect(counts).toHaveTextContent('1')
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
    fireEvent.change(screen.getByLabelText('API 密码（只写）'), { target: { value: 'pool-secret-1' } })
    fireEvent.click(screen.getByRole('button', { name: '登记入池' }))
    await waitFor(() => {
      expect(mocks.registerFreshRssPool).toHaveBeenCalledWith({
        freshrssUsername: 'frss-frank',
        freshrssBaseUrl: 'https://freshrss.example.com',
        apiPassword: 'pool-secret-1',
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
    fireEvent.change(screen.getByLabelText('API 密码（只写）'), { target: { value: 'pool-secret-1' } })
    fireEvent.click(screen.getByRole('button', { name: '登记入池' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already registered')
  })
})
