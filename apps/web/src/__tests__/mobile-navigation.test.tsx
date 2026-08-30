import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { EntryListResponse } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

/** 0007 Test A–D + Drawer a11y。
 *
 * jsdom 不计算 CSS layout：本文件只断言 interaction / state / DOM
 * semantics；390px 的真实视觉效果归真实浏览器 smoke（见 Spec）。 */

const FEEDS = [
  { title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml' },
  { title: '示例源 B', feedUrl: 'https://b.example.com/feed.xml' },
]

function entry(ref: string): EntryListResponse['items'][number] {
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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** feeds / entries（列表）两条路径的 fetch mock；entriesHandler 可控失败。 */
function mockApi(
  entriesHandler: (url: string) => Response | Promise<Response> = () =>
    jsonResponse({ items: [entry('e1.a')], nextCursor: null }),
) {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
    if (/^\/api\/v1\/entries\/e1\./.test(url)) {
      return jsonResponse({
        entryRef: 'e1.a',
        title: '文章 e1.a',
        feedTitle: '示例源 A',
        author: null,
        url: null,
        publishedAt: null,
        read: false,
        starred: false,
        contentText: '纯文本正文',
        contentHtml: null,
      })
    }
    if (url.startsWith('/api/v1/entries')) return entriesHandler(url)
    throw new Error(`unexpected fetch: ${url}`)
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

const menuButton = () => screen.getByRole('button', { name: '打开导航' })
const drawer = () => document.getElementById('mobile-navigation-drawer')

beforeEach(() => {
  useReaderUi.setState({
    view: 'all',
    selectedFeedUrl: null,
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Test A — Drawer closed by default', () => {
  it('初始 drawer 不渲染，menu button 可用且 aria-expanded=false', () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    expect(menuButton()).toBeInTheDocument()
    expect(menuButton()).toHaveAttribute('aria-expanded', 'false')
    expect(menuButton()).toHaveAttribute('aria-controls', 'mobile-navigation-drawer')
    expect(drawer()).toBeNull()
  })
})

describe('Test B — Open / Close', () => {
  it('点 menu → drawer 打开（aria-expanded=true）', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    fireEvent.click(menuButton())
    expect(menuButton()).toHaveAttribute('aria-expanded', 'true')
    expect(drawer()).not.toBeNull()
    // 抽屉里是同一份 Sidebar 导航
    expect(withinDrawer('全部信息流')).toBeInTheDocument()
    expect(withinDrawer(/ME 时间线 · 未读/)).toBeInTheDocument()
    expect(withinDrawer(/ME 时间线 · 收藏/)).toBeInTheDocument()
    expect(withinDrawer('全部信息流')).toBeInTheDocument()
  })

  it('backdrop 点击 → drawer 关闭', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    fireEvent.click(menuButton())
    // backdrop 与 ✕ 是两个不同可访问名的 button（backdrop="关闭导航"，✕="关闭"）
    fireEvent.click(screen.getByRole('button', { name: '关闭导航' }))
    expect(drawer()).toBeNull()
    expect(menuButton()).toHaveAttribute('aria-expanded', 'false')
  })

  it('✕ 按钮 → drawer 关闭', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    fireEvent.click(menuButton())
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(drawer()).toBeNull()
  })

  it('Escape → drawer 关闭', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    fireEvent.click(menuButton())
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(drawer()).toBeNull()
  })
})

describe('Test C — View selection', () => {
  it('drawer 中点 Unread → view=unread、drawer 关闭、selection 清空', async () => {
    // 真实流程：先选中一篇文章 → ← 返回（Reader 打开时顶栏只有返回键）
    // → 打开 drawer → 选 Unread → selection 已被 0005 冻结语义清空
    const fetchMock = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    fireEvent.click(await screen.findByRole('button', { name: /文章 e1\.a/ }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => /\/api\/v1\/entries\/e1\./.test(String(c[0])))).toBe(true)
    })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    fireEvent.click(screen.getByRole('button', { name: '返回文章列表' }))
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()

    // 重新选中，验证导航会再次清空 selection
    fireEvent.click(screen.getByRole('button', { name: /文章 e1\.a/ }))
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    fireEvent.click(screen.getByRole('button', { name: '返回文章列表' }))

    fireEvent.click(menuButton())
    fireEvent.click(withinDrawer(/ME 时间线 · 未读/))

    expect(useReaderUi.getState().view).toBe('unread')
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
    expect(drawer()).toBeNull()
  })
})

describe('Test D — Feed selection', () => {
  it('drawer 中点具体 feed → selectedFeedUrl 正确、drawer 关闭', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    // 等 feeds 加载完成（drawer 与桌面 sidebar 共享同一 query cache）
    await screen.findByRole('button', { name: '示例源 B' })
    fireEvent.click(menuButton())
    fireEvent.click(withinDrawer('示例源 B'))

    expect(useReaderUi.getState().selectedFeedUrl).toBe('https://b.example.com/feed.xml')
    expect(drawer()).toBeNull()
  })

  it('点 All Feeds → selectedFeedUrl=null、drawer 关闭', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    useReaderUi.setState({ selectedFeedUrl: 'https://a.example.com/feed.xml' })
    await screen.findByRole('button', { name: /全部信息流/ })
    fireEvent.click(menuButton())
    fireEvent.click(withinDrawer('全部信息流'))

    expect(useReaderUi.getState().selectedFeedUrl).toBeNull()
    expect(drawer()).toBeNull()
  })
})

describe('Drawer accessibility', () => {
  it('menu button aria-expanded false→true 切换；drawer 为 aside landmark 且无 aria-modal', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    expect(menuButton()).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(menuButton())
    expect(menuButton()).toHaveAttribute('aria-expanded', 'true')

    const panel = drawer()!
    expect(panel.tagName).toBe('ASIDE')
    expect(panel).toHaveAttribute('aria-label', '导航')
    expect(panel.hasAttribute('aria-modal')).toBe(false)
    expect(panel.getAttribute('role')).toBeNull() // 未声明 modal dialog role
  })

  it('非导航按钮（订阅重试）点击后 drawer 不关闭', async () => {
    let feedsOk = false
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/feeds')) {
        return feedsOk
          ? jsonResponse(FEEDS)
          : jsonResponse({ error: { type: 'upstream_error', message: '上游不可用' } }, 502)
      }
      if (url.startsWith('/api/v1/entries')) {
        return jsonResponse({ items: [entry('e1.a')], nextCursor: null })
      }
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    // 等 feeds error 出现（drawer 与桌面 Sidebar 共享同一 query）
    await screen.findByText('订阅加载失败')
    fireEvent.click(menuButton())
    // drawer 挂载新 observer 会触发 stale-on-mount 的后台 refetch，
    // 期间 Sidebar 显示 skeleton；等 refetch 再次失败后 drawer 内出现重试
    const retryButton = await waitFor(() => {
      const btn = Array.from(
        drawer()!.querySelectorAll('button'),
      ).find((b) => b.textContent?.trim() === '重试')
      expect(btn).toBeDefined()
      return btn as HTMLElement
    })

    feedsOk = true
    fireEvent.click(retryButton)

    // 重试是数据操作，不是导航：drawer 保持打开
    expect(drawer()).not.toBeNull()
    expect(useReaderUi.getState().mobileSidebarOpen).toBe(true)
    // 重试后 feeds 数据恢复
    await waitFor(() => {
      expect(withinDrawer('示例源 A')).toBeInTheDocument()
    })
  })
})

/** 在 drawer panel 内按可访问名找 button（drawer 与 desktop sidebar
 * 是同一组件的两份实例，必须限定查询范围；文本 trim 容忍 JSX 缩进；
 * 0010 Gate C：支持 string（精确）与 RegExp（包含匹配））。 */
function withinDrawer(name: string | RegExp): HTMLElement {
  const buttons = Array.from(drawer()?.querySelectorAll('button') ?? [])
  const found = buttons.find((b) => {
    const text = b.textContent?.trim() ?? ''
    return typeof name === 'string' ? text === name : name.test(text)
  })
  if (found === undefined) {
    throw new Error(`button ${name} not found inside drawer`)
  }
  return found as HTMLElement
}
