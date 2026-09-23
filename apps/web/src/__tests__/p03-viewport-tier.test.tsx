/** P03 — 视口分层（viewport tier）与平板 shell。
 *
 * - useViewportTier 断点边界：767→compact / 768→tablet / 1023→tablet /
 *   1024→desktop（mocked matchMedia，精确到像素）；
 * - useIsMobile 派生：compact + tablet → true（<1024 语义），desktop → false；
 *   jsdom 无 matchMedia 的回退（'compact' → true）由既有各测试真实覆盖，
 *   这里再锁一层契约；
 * - 平板 shell：tier=tablet 渲染常驻侧栏（竖排默认折叠 rail）且无
 *   MobileTabBar；compact 仍渲染 MobileTabBar；
 * - useTabletPortrait：834 → true / 835 → false / compact 档恒 false。
 *
 * 真实像素断点由 Playwright（ipad-834 / ipad-1194）与浏览器验证；
 * 这里锁定 hook 逻辑与 shell 挂载契约。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, renderHook, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { useIsMobile } from '../lib/use-is-mobile'
import { useTabletPortrait, useViewportTier } from '../lib/use-viewport-tier'
import type { EntryListResponse } from '../api/types'

/** 按视口宽度 mock matchMedia：支持 min/max-width 的 rem 查询（1rem=16px）。
 * add/removeEventListener 为 no-op（不测跨断点迁移，只测档位计算）。 */
function stubViewport(width: number): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => {
      const max = /max-width:\s*([\d.]+)rem/.exec(query)
      const min = /min-width:\s*([\d.]+)rem/.exec(query)
      let matches = false
      if (max) matches = width <= parseFloat(max[1]) * 16
      if (min) matches = width >= parseFloat(min[1]) * 16
      return {
        matches,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useViewportTier — 断点边界（P03）', () => {
  it.each([
    [767, 'compact'],
    [768, 'tablet'],
    [834, 'tablet'],
    [1023, 'tablet'],
    [1024, 'desktop'],
  ] as const)('%ipx → %s', (width, expected) => {
    stubViewport(width)
    const { result } = renderHook(() => useViewportTier())
    expect(result.current).toBe(expected)
  })

  it('jsdom / SSR 无 matchMedia → 回退 compact（移动端语义不变）', () => {
    // 不 stub：jsdom 无 matchMedia
    const { result } = renderHook(() => useViewportTier())
    expect(result.current).toBe('compact')
  })
})

describe('useIsMobile — 派生语义（<1024 为 true）', () => {
  it.each([
    [390, true],
    [767, true],
    [768, true],
    [1023, true],
    [1024, false],
  ] as const)('%ipx → %s', (width, expected) => {
    stubViewport(width)
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(expected)
  })

  it('jsdom 无 matchMedia → true（既有「视为移动端」约定不回归）', () => {
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(true)
  })
})

describe('useTabletPortrait — 竖排判定（≤834 且 tablet 档）', () => {
  it.each([
    [834, true],
    [835, false],
    [390, false], // compact 档恒 false（竖排默认只属于平板层）
    [1024, false], // desktop 档
  ] as const)('%ipx → %s', (width, expected) => {
    stubViewport(width)
    const { result } = renderHook(() => useTabletPortrait())
    expect(result.current).toBe(expected)
  })
})

// ---- 平板 / compact shell 挂载契约 ----

const FEEDS = [
  { title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml', category: null },
]

function entryItem(ref: string, title: string): EntryListResponse['items'][number] {
  return {
    entryRef: ref,
    title,
    feedTitle: '示例源 A',
    author: null,
    url: null,
    publishedAt: '2026-08-28T00:00:00Z',
    read: false,
    starred: false,
  }
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

/** shell.test.tsx 同款 fetch mock：feeds / entries 最小 fixture；
 * 其余端点（settings / version.json 等）诚实 404，不阻塞 shell 断言。 */
function stubShellApi(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
      if (url.startsWith('/api/v1/entries')) {
        return jsonResponse({ items: [entryItem('e1.a', '文章 平板 A')], nextCursor: null })
      }
      return new Response(
        JSON.stringify({ error: { type: 'not_found', message: 'p03 stub' } }),
        { status: 404, headers: { 'content-type': 'application/json' } },
      )
    }),
  )
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

describe('平板 shell（tier=tablet）', () => {
  it('竖排（834）：常驻侧栏（默认折叠 rail）渲染，无底部导航岛', async () => {
    stubViewport(834)
    stubShellApi()
    renderApp()

    // 侧栏折叠 rail（竖排默认）——与展开侧栏共享「主导航」语义前缀
    await screen.findAllByText('文章 平板 A')
    expect(screen.getByRole('navigation', { name: /主导航/ })).toBeInTheDocument()
    // 平板层无底栏（compact 专属）
    expect(screen.queryByRole('navigation', { name: '底部导航' })).toBeNull()
  })

  it('横排（960）：展开侧栏渲染 + 无底部导航岛', async () => {
    stubViewport(960)
    stubShellApi()
    renderApp()

    await screen.findAllByText('文章 平板 A')
    // 非折叠：展开侧栏 nav（Sidebar 的「主导航」）存在，折叠 rail 不存在
    expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
    expect(
      screen.queryByRole('navigation', { name: '主导航（已折叠）' }),
    ).toBeNull()
    expect(screen.queryByRole('navigation', { name: '底部导航' })).toBeNull()
  })

  it('竖排折叠 rail 可展开（会话内状态，不写持久化设置）', async () => {
    stubViewport(834)
    stubShellApi()
    renderApp()

    await screen.findAllByText('文章 平板 A')
    const rail = screen.getByRole('navigation', { name: '主导航（已折叠）' })
    fireEvent.click(within(rail).getByRole('button', { name: '展开侧栏' }))
    expect(
      screen.getByRole('navigation', { name: '主导航' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('navigation', { name: '主导航（已折叠）' }),
    ).toBeNull()
  })
})

describe('compact shell（tier=compact）', () => {
  it('390：底部导航岛仍在（MobileTabBar 仅 compact 档渲染）', async () => {
    stubViewport(390)
    stubShellApi()
    const { container } = renderApp()

    await screen.findAllByText('文章 平板 A')
    expect(screen.getByRole('navigation', { name: '底部导航' })).toBeInTheDocument()
    // compact 的侧栏保持既有 DOM 契约：aside 挂载但由 CSS 隐藏
    //（hidden lg:block；真实可见性归浏览器，导航走 Header/Drawer/TabBar）
    const aside = container.querySelector('aside')
    expect(aside).not.toBeNull()
    expect(aside?.className).toContain('hidden')
  })
})
