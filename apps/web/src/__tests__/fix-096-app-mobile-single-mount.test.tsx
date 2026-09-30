/**
 * FIX-096 — App 移动/桌面分支不再靠 CSS 隐藏双挂载业务页面。
 *
 * 修复前（compact <1024、section≠home）：移动 section 区挂载一份
 * SearchPage（可见），Timeline 列位的桌面分支又被 CSS（max-lg:hidden
 * + hidden lg:flex）藏起来但仍挂载同一 SearchPage——同一业务组件两份
 * 实例，各自持本地状态、各自跑一次性 effect；agent/graph 同理。
 * 修复后：移动端桌面列位不挂载页面本体（桌面 ≥1024 行为不变）。
 *
 * jsdom 无 matchMedia → tier='compact'，正好落在移动档。
 * 页面组件是 lazy 挂载：断言前先等动态 import 完成（双挂载缺陷在
 * 懒加载 resolve 后才会在 DOM 里出现第二份实例）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { useReaderUi } from '../store/reader-ui'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

beforeAll(async () => {
  // MobileNavigationDrawer 模块级 warm import（import('./ui/Sheet')）在
  // 环境拆除后才 resolve 会报 Unhandled Rejection——这里预先加载。
  await import('../components/ui/Sheet')
})

beforeEach(() => {
  window.localStorage.clear()
  // feeds 必须是数组（Sidebar 直接迭代）；其余端点给空 JSON——本测试
  // 只关心挂载拓扑，不关心数据。
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/feeds')) return jsonResponse([])
      return jsonResponse({ items: [], nextCursor: null })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-096: 移动端业务页面单实例挂载', () => {
  it('compact 档 section=search：SearchPage 只挂载一份（搜索输入框唯一）', async () => {
    useReaderUi.setState({ section: 'search', selectedEntryRef: null })
    const view = renderApp()
    // 等 lazy SearchPage 真正渲染出主搜索框
    await screen.findAllByPlaceholderText('搜索文章标题、正文或作者…')
    const inputs = document.querySelectorAll('input[aria-label="搜索"]')
    expect(inputs).toHaveLength(1)
    // 移动 section 区可见 + 桌面 Timeline 列位不再有隐藏的第二份
    expect(view.container.querySelector('section[aria-label="搜索"]')).not.toBeNull()
    view.unmount()
  })

  it('compact 档 section=graph：GraphPage 只挂载一份（桌面全宽 section 不重复挂载）', async () => {
    useReaderUi.setState({ section: 'graph', selectedEntryRef: null })
    const view = renderApp()
    await waitFor(() => {
      expect(view.container.querySelectorAll('[aria-label="标签与图谱"]').length).toBeGreaterThan(0)
    })
    expect(view.container.querySelectorAll('[aria-label="标签与图谱"]')).toHaveLength(1)
    view.unmount()
  })
})
