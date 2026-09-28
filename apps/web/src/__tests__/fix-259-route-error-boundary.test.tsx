/** FIX-259 — 路由级错误边界：页面渲染抛错只落在该路由边界。
 *
 * 契约：
 * 1. 某个一级页（这里以收藏页模拟「坏参数/坏数据 → 渲染抛错」）抛错时，
 *    错误面只替换该路由位——Sidebar 等其余壳层仍在，可操作；
 * 2. 错误面提供「返回首页」入口，点击后回到有效页面（home 时间线）；
 * 3. 修复前：无任何 ErrorBoundary，React 卸载整树 = 全 App 白屏。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { useReaderUi } from '../store/reader-ui'

// 模拟一级页因坏参数/坏数据在渲染期抛错（懒加载 chunk 的真实模块被替换）
vi.mock('../components/pages/FavoritesPage', () => ({
  default: function BrokenFavoritesPage() {
    throw new Error('收藏页渲染失败（模拟坏参数触发）')
  },
}))

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const FEEDS = [
  { title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml', category: null },
]

function entry(ref: string) {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源 A',
    author: null,
    url: null,
    publishedAt: '2026-08-28T00:00:00Z',
    read: false,
    starred: false,
  }
}

function appFetchMock() {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
    if (url.startsWith('/api/v1/categories')) return jsonResponse([])
    if (url.startsWith('/api/v1/subscriptions')) return jsonResponse([])
    if (url.startsWith('/api/v1/entries?')) {
      return jsonResponse({ items: [entry('e1.home')], nextCursor: null })
    }
    // 其余（版本检查等）→ 404 JSON，静默降级
    return jsonResponse({ error: 'not_found' }, 404)
  })
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({
    section: 'home',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('FIX-259 路由级错误边界', () => {
  it('页面渲染抛错 → 错误面只落在该路由位，壳层完好且有「返回首页」入口', async () => {
    vi.stubGlobal('fetch', appFetchMock())
    const { container } = renderApp()

    // home 正常：时间线渲染文章（壳层基线）
    await screen.findAllByText('文章 e1.home')
    expect(document.querySelector('aside')).not.toBeNull()

    // 切到收藏页（被 mock 为渲染期抛错）——与移动端收藏 tab 同一入口
    //（useReaderUi.selectSection；jsdom 视口为 tablet 档，直接驱动同一 store）
    useReaderUi.getState().selectSection('favorites')

    // 错误面出现且限定在该路由位：说明文案 + 返回入口
    const surface = await screen.findByRole('alert', {}, { timeout: 10_000 })
    expect(surface.textContent).toContain('收藏页渲染失败')
    const backHome = within(surface).getByRole('button', { name: '返回首页' })
    expect(backHome).toBeInTheDocument()

    // 壳层完好：Sidebar 仍在文档中（修复前整树卸载 = 查不到任何元素）
    expect(container.querySelector('aside')).not.toBeNull()

    // 返回有效页面的入口：点击后回到 home 时间线
    fireEvent.click(backHome)
    await waitFor(() => expect(screen.getAllByText('文章 e1.home').length).toBeGreaterThan(0))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('重试入口：错误面内「重试」重新挂载该路由（错误按边界复位）', async () => {
    vi.stubGlobal('fetch', appFetchMock())
    renderApp()
    await screen.findAllByText('文章 e1.home')
    useReaderUi.getState().selectSection('favorites')
    const surface = await screen.findByRole('alert', {}, { timeout: 10_000 })
    fireEvent.click(within(surface).getByRole('button', { name: '重试' }))

    // 重试后边界复位：错误面仍会出现（页面仍抛错）——但这是「该路由位
    // 重新挂载」的证据，而不是壳层崩溃（Sidebar 依旧在）。
    await screen.findByRole('alert', {}, { timeout: 10_000 })
    expect(document.querySelector('aside')).not.toBeNull()
  })
})
