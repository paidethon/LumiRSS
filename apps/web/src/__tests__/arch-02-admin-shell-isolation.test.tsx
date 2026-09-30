/** ARCH-02 — App 单一页面注册与外壳：/admin 路由隔离守卫（行为级）。
 *
 * 验收点（架构整改 ARCH-02）：
 * 1. 进入管理页不初始化无关阅读任务 —— 以真实 App 路由（useAppRoute →
 *    App.tsx 顶部早返回 AdminScreen）挂载到 /admin，断言 fetch 调用集合
 *    只含 /api/v1/admin/*（owner；member 为 forbidden 态零 API 请求），零
 *    timeline/entries/订阅树等阅读域端点；
 * 2. 切换路由无重复挂载/请求 —— /admin → / → /admin 来回切换，每次进入
 *    admin 各端点恰好一次（单实例挂载 = 单次请求；重复挂载会成对出现）。
 *
 * 允许的非 admin 例外（有意为之，非阅读域）：`/version.json` —— F117
 * App 级版本轮询（App.tsx 顶部 useEffect，任何顶层路由都会启动一次），
 * 是更新提示的应用基建探测，不是 timeline/entries/订阅树阅读查询。
 * 本测试钉死「非 admin 请求只可能是它」。
 *
 * 取证边界（jsdom 能证什么/不能证什么）：
 * - 能证：路由源单一判定下的组件挂载集合与网络请求集合（fetch stub 记录
 *   真实 client 路径）；无 CSS 双挂载、无查询重复发起。
 * - 不能证：真实视口下的媒体查询行为（归真实浏览器 e2e/smoke）、真实
 *   网络栈（归 BFF 集成测试）。本文件不 mock ../api/client —— 走真实
 *   request() 代码路径，只 stub 全局 fetch。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { navigateAppRoute } from '../lib/app-route'
import { useAuthStore, type AuthIdentity } from '../store/auth'
import { useReaderUi } from '../store/reader-ui'

const OWNER: AuthIdentity = { userId: 'u1', username: 'alice', role: 'owner' }
const MEMBER: AuthIdentity = { userId: 'u2', username: 'bob', role: 'member' }

/** 阅读域顶层端点段（admin 页面不得触发的查询域）。 */
const READING_SEGMENTS = [
  'entries',
  'feeds',
  'subscriptions',
  'categories',
  'favorites',
  'library',
  'workspaces',
  'search',
  'graph',
  'sources',
  'tags',
  'annotations',
  'whats-new',
] as const

function isReadingFetch(url: string): boolean {
  if (!url.startsWith('/api/v1/')) return false
  const seg = url.slice('/api/v1/'.length).split(/[/?]/)[0]
  return (READING_SEGMENTS as readonly string[]).includes(seg)
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** 记录全部 fetch URL；常见端点给最小合法形状（阅读外壳在 '/' 挂载时
 * Sidebar/Timeline 会消费 feeds/entries 形状，坏形状会渲染崩溃并污染
 * 路由切换取证）。queryFn 内形状解析失败会被 TanStack 捕获为 error 态，
 * 不影响「发起过哪些请求」的取证目标。 */
function stubFetchRecorder(): { calls: string[] } {
  const calls: string[] = []
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    calls.push(url)
    if (url.startsWith('/api/v1/feeds') || url.startsWith('/api/v1/subscriptions')) {
      return jsonResponse([])
    }
    if (url.startsWith('/api/v1/entries')) {
      return jsonResponse({ items: [], nextCursor: null })
    }
    if (url.includes('/admin/invite-funnel')) {
      return jsonResponse({
        generated: 0,
        pending: 0,
        activated: 0,
        expired: 0,
        revoked: 0,
      })
    }
    if (/\/admin\/(users|invites|invite-schemes)\b/.test(url)) return jsonResponse([])
    if (url.includes('/admin/audit')) return jsonResponse([])
    if (url.includes('/admin/help/feedback')) return jsonResponse({ items: [] })
    if (url.includes('/admin/rollback-readiness')) {
      // N197 回滚就绪是唯一非防御性解析的 admin 端点（typed request）
      return jsonResponse({
        canRollback: false,
        previousImage: { state: 'none', tag: null, reason: null },
        backup: { state: 'none', name: null, reason: null, verifyOk: false, findings: null },
        schema: { current: null, backup: null, unchanged: true },
        dbDowngrade: 'not_required',
        note: '',
      })
    }
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls }
}

function renderApp() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <App />
    </QueryClientProvider>,
  )
}

/** owner 进入 admin 后：全部请求 ⊆ {admin 端点, /version.json(F117)}。 */
function expectOnlyAdminDomain(calls: string[]): void {
  expect(calls.length).toBeGreaterThan(0)
  const nonAdmin = calls.filter((u) => !u.startsWith('/api/v1/admin/'))
  for (const url of nonAdmin) {
    expect(
      url,
      'admin 页面只允许 admin 域端点 + F117 /version.json 应用探测',
    ).toBe('/version.json')
  }
  const reading = calls.filter(isReadingFetch)
  expect(reading, `阅读域端点不得出现：${reading.join(', ')}`).toEqual([])
}

beforeEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  useReaderUi.setState({
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
  useAuthStore.setState({ status: 'authenticated', mode: 'session', identity: null })
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('ARCH-02: /admin 不初始化无关阅读查询（App 真实路由挂载）', () => {
  it('owner 直接挂载 /admin：fetch 集合 ⊆ {admin 端点, F117 版本探测}，零阅读域端点', async () => {
    useAuthStore.setState({ identity: OWNER })
    const { calls } = stubFetchRecorder()
    window.history.replaceState(null, '', '/admin')
    renderApp()

    // lazy AdminScreen chunk 解析 + sections 查询落地
    await screen.findByTestId('admin-screen')
    await waitFor(() => expect(calls.some((u) => u.startsWith('/api/v1/admin/'))).toBe(true))
    // 让同 tick 内的其余 section 查询全部出栈
    await waitFor(() =>
      expect(calls.filter((u) => u.startsWith('/api/v1/admin/')).length).toBeGreaterThanOrEqual(10),
    )

    expectOnlyAdminDomain(calls)
  })

  it('member 直接挂载 /admin：forbidden 态，零 API 请求（admin 与阅读域都无）', async () => {
    useAuthStore.setState({ identity: MEMBER })
    const { calls } = stubFetchRecorder()
    window.history.replaceState(null, '', '/admin')
    renderApp()

    await screen.findByTestId('admin-screen')
    await screen.findByTestId('admin-forbidden')
    // 让挂载后微任务里的潜在查询出栈再取证
    await waitFor(() => expect(screen.getByTestId('admin-forbidden')).toBeInTheDocument())

    const apiCalls = calls.filter((u) => u.startsWith('/api/v1/'))
    expect(apiCalls, 'member 的 admin 页不得发起任何 API 请求').toEqual([])
  })
})

describe('ARCH-02: 切换路由无重复挂载/请求（/ ⇆ /admin 守卫）', () => {
  it('每次进入 /admin 各 admin 端点恰好一次；进入后不再发阅读域请求', async () => {
    useAuthStore.setState({ identity: OWNER })
    const { calls } = stubFetchRecorder()
    renderApp()

    // 阅读外壳先就位
    await waitFor(() => expect(calls.length).toBeGreaterThan(0))

    // → /admin
    navigateAppRoute('admin')
    await screen.findByTestId('admin-screen')
    await waitFor(() =>
      expect(calls.filter((u) => u.startsWith('/api/v1/admin/')).length).toBeGreaterThanOrEqual(10),
    )

    const firstAdminIdx = calls.findIndex((u) => u.startsWith('/api/v1/admin/'))
    // 进入 admin 之前允许外壳的阅读查询；进入之后零阅读域请求
    for (const url of calls.slice(firstAdminIdx)) {
      expect(isReadingFetch(url), `进入 admin 后不得再发阅读域请求：${url}`).toBe(false)
    }

    // 单实例挂载：同一 admin 端点在一次进入内只发一次（双挂载必成对重复）
    const firstVisit = calls.filter((u) => u.startsWith('/api/v1/admin/'))
    expect(firstVisit.length).toBe(new Set(firstVisit).size)

    // → 返回阅读
    const firstVisitCount = firstVisit.length
    navigateAppRoute('app')
    await waitFor(() => expect(screen.queryByTestId('admin-screen')).not.toBeInTheDocument())
    expect(calls.filter((u) => u.startsWith('/api/v1/admin/')).length).toBe(firstVisitCount)

    // → 再进 /admin：无重复挂载。admin section 查询钉 staleTime 10s
    // （AdminScreen.tsx 各 section），10s 内再进入走缓存是合法复用而非
    // 重复挂载；重复挂载的证伪形状 = 同一次进入内同端点出现两次。
    // 断言：任一端点累计次数 ≤ 进入次数（本例 2），且第二次进入后仍零阅读域。
    navigateAppRoute('admin')
    await screen.findByTestId('admin-screen')
    await waitFor(() => expect(calls.filter((u) => u.startsWith('/api/v1/admin/')).length).toBeGreaterThan(firstVisitCount))
    const perUrl = new Map<string, number>()
    for (const url of calls.filter((u) => u.startsWith('/api/v1/admin/'))) {
      perUrl.set(url, (perUrl.get(url) ?? 0) + 1)
    }
    for (const [url, count] of perUrl) {
      expect(count, `端点 ${url} 两次进入累计 ${count} 次（应 ≤ 2，单次进入内至多 1）`).toBeLessThanOrEqual(2)
    }
    const lastAdminIdx = calls.map((u, i) => (u.startsWith('/api/v1/admin/') ? i : -1))
    const lastIdx = Math.max(...lastAdminIdx)
    for (const url of calls.slice(lastIdx)) {
      expect(isReadingFetch(url), `再次进入 admin 后不得发阅读域请求：${url}`).toBe(false)
    }
  })
})
