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
  { title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml', category: null },
  { title: '示例源 B', feedUrl: 'https://b.example.com/feed.xml', category: null },
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
    scope: { kind: 'all' },
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
    // 抽屉里是同一份 Sidebar 导航（0011 修正补充：工作区 = 稍后读 + 收藏）
    expect(withinDrawer('全部信息源')).toBeInTheDocument()
    expect(withinDrawer('稍后读')).toBeInTheDocument()
    expect(withinDrawer('收藏')).toBeInTheDocument()
    expect(withinDrawer('全部信息源')).toBeInTheDocument()
  })

  it('遮罩点击 → drawer 关闭', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    fireEvent.click(menuButton())
    // 0011：遮罩是 aria-hidden div（Sheet primitive），关闭走 pointerDown
    const overlay = drawer()!.parentElement!.querySelector('div[aria-hidden="true"]')!
    fireEvent.pointerDown(overlay)
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
    // 0011：Sheet 的 Escape 监听挂在 document（Dialog 同款）
    fireEvent.keyDown(document, { key: 'Escape' })
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

    // 0011：双渲染（Row+Card）取第一个实例
    fireEvent.click((await screen.findAllByRole('button', { name: /文章 e1\.a/ }))[0]!)
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => /\/api\/v1\/entries\/e1\./.test(String(c[0])))).toBe(true)
    })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    fireEvent.click(screen.getByRole('button', { name: '返回文章列表' }))
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()

    // 重新选中，验证导航会再次清空 selection
    fireEvent.click((await screen.findAllByRole('button', { name: /文章 e1\.a/ }))[0]!)
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    fireEvent.click(screen.getByRole('button', { name: '返回文章列表' }))

    fireEvent.click(menuButton())
    // 0011 修正补充：「未读」为全部信息流行的过滤子项（drawer 内）
    fireEvent.click(withinDrawer('未读'))

    expect(useReaderUi.getState().view).toBe('unread')
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
    expect(drawer()).toBeNull()
  })
})

describe('Test D — Feed selection', () => {
  it('drawer 中点具体 feed → selectedFeedUrl 正确、section 回首页、drawer 关闭', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    fireEvent.click(menuButton())
    // 0011：RSS tree 默认收起——展开 tree + 未分组分类后点 feed（AC3/AC4）
    fireEvent.click(withinDrawer(/展开 RSS 分类/))
    // feeds 数据异步到达：等分类节点出现后再展开
    await waitFor(() => withinDrawer(/展开 未分组/))
    fireEvent.click(withinDrawer(/展开 未分组/))
    const feedButton = await waitFor(() => {
      const btn = withinDrawer('示例源 B')
      expect(btn).toBeInTheDocument()
      return btn
    })
    fireEvent.click(feedButton)

    expect(useReaderUi.getState().scope).toEqual({ kind: 'rss-feed', feedUrl: 'https://b.example.com/feed.xml' })
    // feed 导航切回首页（0011 AC4）
    expect(useReaderUi.getState().section).toBe('home')
    expect(drawer()).toBeNull()
  })

  it('点 All Feeds → selectedFeedUrl=null、drawer 关闭', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    useReaderUi.setState({ scope: { kind: 'rss-feed', feedUrl: 'https://a.example.com/feed.xml' } })
    await screen.findByRole('button', { name: /全部信息源/ })
    fireEvent.click(menuButton())
    fireEvent.click(withinDrawer('全部信息源'))

    expect(useReaderUi.getState().scope).toEqual({ kind: 'all' })
    expect(drawer()).toBeNull()
  })
})

describe('Drawer accessibility', () => {
  it('menu button aria-expanded false→true 切换；0011：drawer 为完整 modal（role=dialog + aria-modal）', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    expect(menuButton()).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(menuButton())
    expect(menuButton()).toHaveAttribute('aria-expanded', 'true')

    const panel = drawer()!
    // 0011 Gate 2（用户批准）：升级为完整 modal 语义
    expect(panel).toHaveAttribute('role', 'dialog')
    expect(panel).toHaveAttribute('aria-modal', 'true')
    // 初始焦点：第一个可聚焦元素（✕ 关闭钮）
    expect(document.activeElement?.textContent?.trim()).toBe('✕')
  })

  it('打开时锁定背景滚动（body overflow hidden），关闭后恢复', () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    expect(document.body.style.overflow).not.toBe('hidden')
    fireEvent.click(menuButton())
    expect(document.body.style.overflow).toBe('hidden')
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(document.body.style.overflow).not.toBe('hidden')
  })

  it('焦点 trap：Tab 循环在面板内；关闭后焦点恢复触发按钮', () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    // 键盘流程：先聚焦菜单钮再打开（fireEvent.click 不自动聚焦）
    menuButton().focus()
    fireEvent.click(menuButton())
    const panel = drawer()!
    const focusables = Array.from(
      panel.querySelectorAll('button'),
    ) as HTMLElement[]
    expect(focusables.length).toBeGreaterThan(1)

    // Tab 在面板内循环：从最后一个再 Tab 回第一个（Trap 拦截）
    focusables[focusables.length - 1]!.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(panel.contains(document.activeElement)).toBe(true)

    // 关闭后焦点恢复到触发按钮（菜单）
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(document.activeElement).toBe(menuButton())
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

    // 0011：feeds error/skeleton 在 RSS disclosure 内（默认收起），
    // 先展开桌面侧栏的 disclosure 再等 error 出现
    fireEvent.click(screen.getByRole('button', { name: '展开 RSS 分类' }))
    await screen.findByText('订阅加载失败')
    fireEvent.click(menuButton())
    // drawer 是独立 Sidebar 实例，其 disclosure 也需展开
    fireEvent.click(withinDrawer(/展开 RSS 分类/))
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
    // 重试后 feeds 数据恢复：分类节点出现，展开后 feed 可见
    await waitFor(() => withinDrawer(/展开 未分组/))
    fireEvent.click(withinDrawer(/展开 未分组/))
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
    const label = b.getAttribute('aria-label') ?? ''
    return typeof name === 'string'
      ? text === name || label === name
      : name.test(text) || name.test(label)
  })
  if (found === undefined) {
    throw new Error(`button ${name} not found inside drawer`)
  }
  return found as HTMLElement
}
