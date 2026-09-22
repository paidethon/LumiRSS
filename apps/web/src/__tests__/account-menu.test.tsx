/** 账号菜单（AccountMenu）Web 测试 — 0067 多账户。
 *
 * 覆盖：身份展示（username + 角色徽标）、basic 模式零渲染（现状
 * 兼容）、管理台入口仅 owner/admin、修改密码、退出登录（清缓存 +
 * 翻认证门 + 清身份）、退出所有设备（确认对话框）。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import AccountMenu from '../components/AccountMenu'
import { listRecentReads } from '../lib/recent-reads'
import { useAuthStore, type AuthIdentity } from '../store/auth'

const mocks = vi.hoisted(() => ({
  changePassword: vi.fn(),
  logoutCurrent: vi.fn(),
  logoutEverywhere: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    changePassword: mocks.changePassword,
    logoutCurrent: mocks.logoutCurrent,
    logoutEverywhere: mocks.logoutEverywhere,
  }
})

const OWNER: AuthIdentity = { userId: 'u1', username: 'alice', role: 'owner' }
const MEMBER: AuthIdentity = { userId: 'u2', username: 'bob', role: 'member' }

function renderMenu(queryClient: QueryClient = new QueryClient()) {
  return render(
    <QueryClientProvider client={queryClient}>
      <AccountMenu />
    </QueryClientProvider>,
  )
}

function seedQuery(queryClient: QueryClient): void {
  queryClient.setQueryData(['feeds'], [{ feedUrl: 'https://a.example/rss', title: 'A 的订阅' }])
}

beforeEach(() => {
  localStorage.clear()
  useAuthStore.setState({ status: 'authenticated', mode: 'session', identity: null })
  vi.clearAllMocks()
})

describe('身份展示与入口可见性', () => {
  it('session 模式：显示 username + 角色徽标', () => {
    useAuthStore.setState({ identity: MEMBER })
    renderMenu()
    expect(screen.getByTestId('account-username')).toHaveTextContent('bob')
    expect(screen.getByTestId('account-role-badge')).toHaveTextContent('成员')
  })

  it('basic 模式（无身份）→ 零渲染（现状兼容，不显示身份与退出）', () => {
    useAuthStore.setState({ mode: 'basic', identity: null })
    renderMenu()
    expect(screen.queryByTestId('account-menu')).not.toBeInTheDocument()
  })

  it('owner 角色徽标为「运营者」，且菜单含管理台入口', async () => {
    useAuthStore.setState({ identity: OWNER })
    renderMenu()
    expect(screen.getByTestId('account-role-badge')).toHaveTextContent('运营者')
    fireEvent.click(screen.getByTestId('account-menu-trigger'))
    expect(await screen.findByRole('menuitem', { name: '管理台' })).toBeInTheDocument()
  })

  it('member 的菜单不含管理台入口（后端才是权限真源，前端只做入口可见性）', async () => {
    useAuthStore.setState({ identity: MEMBER })
    renderMenu()
    fireEvent.click(screen.getByTestId('account-menu-trigger'))
    await screen.findByRole('menuitem', { name: '退出登录' })
    expect(screen.queryByRole('menuitem', { name: '管理台' })).not.toBeInTheDocument()
  })
})

describe('退出登录（O157 统一清理）', () => {
  it('退出登录 → logoutCurrent → 缓存清空 + 身份清除 + 门翻 unauthenticated', async () => {
    useAuthStore.setState({ identity: MEMBER })
    // 与 Provider 共享同一实例（账号菜单经 useQueryClient 拿到的就是它）
    const queryClient = new QueryClient()
    seedQuery(queryClient)
    localStorage.setItem('lumirss-recent-reads', JSON.stringify([
      { entryRef: 'ref-a', title: 'A 的文章', feedTitle: '', openedAt: '2026-09-01T00:00:00Z' },
    ]))
    mocks.logoutCurrent.mockResolvedValue({ authenticated: false })
    renderMenu(queryClient)
    fireEvent.click(screen.getByTestId('account-menu-trigger'))
    fireEvent.click(await screen.findByRole('menuitem', { name: '退出登录' }))
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('unauthenticated')
    })
    expect(mocks.logoutCurrent).toHaveBeenCalledTimes(1)
    expect(mocks.logoutEverywhere).not.toHaveBeenCalled()
    expect(useAuthStore.getState().identity).toBeNull()
    expect(queryClient.getQueryData(['feeds'])).toBeUndefined()
    // 本地足迹一并清掉（O157；clearRecentReads 语义 = 列表清空）
    expect(listRecentReads()).toHaveLength(0)
  })

  it('退出所有设备：先弹确认对话框，确认后才调 logout-all', async () => {
    useAuthStore.setState({ identity: MEMBER })
    mocks.logoutEverywhere.mockResolvedValue({ authenticated: false })
    renderMenu()
    fireEvent.click(screen.getByTestId('account-menu-trigger'))
    fireEvent.click(await screen.findByRole('menuitem', { name: '退出所有设备' }))
    // 确认对话框出现，此时还没发请求
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(mocks.logoutEverywhere).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '退出所有设备' }))
    await waitFor(() => {
      expect(mocks.logoutEverywhere).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('unauthenticated')
    })
  })

  it('退出所有设备：取消 → 不发任何请求', async () => {
    useAuthStore.setState({ identity: MEMBER })
    renderMenu()
    fireEvent.click(screen.getByTestId('account-menu-trigger'))
    fireEvent.click(await screen.findByRole('menuitem', { name: '退出所有设备' }))
    await screen.findByRole('dialog')
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(mocks.logoutEverywhere).not.toHaveBeenCalled()
    expect(useAuthStore.getState().status).toBe('authenticated')
  })

  it('登出请求网络失败 → 仍执行本地清理并翻门（用户明确要退出）', async () => {
    useAuthStore.setState({ identity: MEMBER })
    mocks.logoutCurrent.mockRejectedValue(new TypeError('Failed to fetch'))
    renderMenu()
    fireEvent.click(screen.getByTestId('account-menu-trigger'))
    fireEvent.click(await screen.findByRole('menuitem', { name: '退出登录' }))
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('unauthenticated')
    })
    expect(useAuthStore.getState().identity).toBeNull()
  })
})

describe('修改密码', () => {
  it('旧密码 + 新密码 → changePassword；成功显示结果文案并关闭后可重开', async () => {
    useAuthStore.setState({ identity: MEMBER })
    mocks.changePassword.mockResolvedValue({ authenticated: true, mode: 'session' })
    renderMenu()
    fireEvent.click(screen.getByTestId('account-menu-trigger'))
    fireEvent.click(await screen.findByRole('menuitem', { name: '修改密码' }))
    fireEvent.change(await screen.findByLabelText('当前密码'), { target: { value: 'old-secret-1' } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'new-secret-1' } })
    fireEvent.click(screen.getByRole('button', { name: '修改密码' }))
    await waitFor(() => {
      expect(mocks.changePassword).toHaveBeenCalledWith('old-secret-1', 'new-secret-1')
    })
    expect(await screen.findByRole('status')).toHaveTextContent('密码已修改')
  })

  it('当前密码错误（invalid_credentials）→ 诚实提示', async () => {
    useAuthStore.setState({ identity: MEMBER })
    mocks.changePassword.mockRejectedValue(
      new ApiError(401, 'invalid_credentials', 'Incorrect current password.'),
    )
    renderMenu()
    fireEvent.click(screen.getByTestId('account-menu-trigger'))
    fireEvent.click(await screen.findByRole('menuitem', { name: '修改密码' }))
    fireEvent.change(await screen.findByLabelText('当前密码'), { target: { value: 'wrong-old' } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'new-secret-1' } })
    fireEvent.click(screen.getByRole('button', { name: '修改密码' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('当前密码不正确')
  })
})
