/** FIX-009 — 管理员入口移动端可达守卫（BASELINE_OK 钉定）。
 *
 * 台账前提：管理员入口在移动端侧栏、折叠菜单中不得遮挡/不可达。
 * 核验结论（诚实证据）：基线已成立——移动端导航抽屉
 * （MobileNavigationDrawer，compact 档 ☰ 打开）复用同一份 <Sidebar/>，
 * 其底部的 AccountMenu（FIX-001 后 session 模式恒渲染）对 owner/admin
 * 提供「管理台」入口，点击 navigateAppRoute('admin') 进入管理台；
 * 平板折叠 rail（SidebarCollapsedRail）常驻「展开侧栏」按钮，展开后
 * 同一 AccountMenu 可达。桌面/移动共享单一入口组件，不存在第二套被
 * 遮挡的实现。本文件以行为测试钉死：抽屉内 owner 见管理台入口、
 * 点击进入 /admin；member 无该入口。
 *
 * jsdom 不计算 CSS layout：遮挡类问题（视觉层叠）归真实浏览器 smoke；
 * 本文件钉的是「入口存在 + 可交互 + 导航生效」的 DOM 语义契约。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { useAuthStore, type AuthIdentity } from '../store/auth'
import { useReaderUi } from '../store/reader-ui'

const OWNER: AuthIdentity = { userId: 'u1', username: 'alice', role: 'owner' }
const MEMBER: AuthIdentity = { userId: 'u2', username: 'bob', role: 'member' }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function mockApi(): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return jsonResponse([])
    if (url.startsWith('/api/v1/entries')) return jsonResponse({ items: [], nextCursor: null })
    return jsonResponse({})
  })
}

// 打开抽屉后按钮被 Base UI 模态隔离 inert + aria-hidden：DOM 查询在
// 两种状态下都稳定（与 mobile-navigation.test.tsx 同一适配）。
const menuButton = () => document.querySelector<HTMLButtonElement>('[aria-label="打开导航"]')!
const drawer = () => document.getElementById('mobile-navigation-drawer')

function renderApp() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <App />
    </QueryClientProvider>,
  )
}

beforeEach(async () => {
  localStorage.clear()
  vi.unstubAllGlobals()
  useReaderUi.setState({
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
  useAuthStore.setState({ status: 'authenticated', mode: 'session', identity: null })
  // Sheet / MobileNavigationDrawer 是 lazy 分包：预解析 chunk，让
  // fireEvent 后的同步结构断言确定性成立（与 mobile-navigation 同法）。
  await import('../components/ui/Sheet')
  await import('../components/MobileNavigationDrawer')
})

afterEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('FIX-009 移动端抽屉的管理台入口（BASELINE_OK 守卫）', () => {
  it('owner：抽屉内账户区块可见 → 菜单含管理台 → 点击导航 /admin', async () => {
    useAuthStore.setState({ identity: OWNER })
    vi.stubGlobal('fetch', mockApi())
    renderApp()
    fireEvent.click(menuButton())
    // 首个用例可能撞上 Sheet 分包的模块级预热（Suspense 兜底 null）——
    // waitFor 抽屉出现，不假设同步就绪。
    await waitFor(() => expect(drawer()).not.toBeNull())
    const trigger = document.querySelector<HTMLButtonElement>('[data-testid="account-menu-trigger"]')
    expect(trigger).not.toBeNull()
    expect(document.querySelector('[data-testid="account-username"]')).toHaveTextContent('alice')
    fireEvent.click(trigger!)
    fireEvent.click(await screen.findByRole('menuitem', { name: '管理台' }))
    await waitFor(() => {
      expect(window.location.pathname).toBe('/admin')
    })
  })

  it('member：抽屉内账户区块可见，但不含管理台入口', async () => {
    useAuthStore.setState({ identity: MEMBER })
    vi.stubGlobal('fetch', mockApi())
    renderApp()
    fireEvent.click(menuButton())
    const trigger = document.querySelector<HTMLButtonElement>('[data-testid="account-menu-trigger"]')
    expect(trigger).not.toBeNull()
    fireEvent.click(trigger!)
    await screen.findByRole('menuitem', { name: '退出登录' })
    expect(screen.queryByRole('menuitem', { name: '管理台' })).not.toBeInTheDocument()
  })
})
