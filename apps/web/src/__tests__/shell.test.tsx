import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { EntryListResponse } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

const FEEDS = [
  { title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml' },
  { title: '示例源 B', feedUrl: 'https://b.example.com/feed.xml' },
]

function entry(ref: string, overrides: Partial<EntryListResponse['items'][number]> = {}) {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源 A',
    author: null,
    url: null,
    publishedAt: '2026-08-28T00:00:00Z',
    read: false,
    starred: false,
    ...overrides,
  }
}

function page(items: EntryListResponse['items'], nextCursor: string | null = null): EntryListResponse {
  return { items, nextCursor }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

type FetchHandler = (input: string) => Response | Promise<Response>

/** 按路径分发的 fetch mock：/api/v1/feeds 与 /api/v1/entries。 */
function mockApi(feedsHandler: FetchHandler, entriesHandler: FetchHandler) {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return feedsHandler(url)
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

beforeEach(() => {
  useReaderUi.setState({
    view: 'all',
    selectedFeedUrl: null,
    selectedEntryRef: null,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Test E — Shell loading', () => {
  it('feeds / entries pending 时存在 loading UI', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => new Promise<Response>(() => {})),
    )
    renderApp()

    expect(screen.getByLabelText('订阅加载中')).toBeInTheDocument()
    expect(screen.getByLabelText('文章加载中')).toBeInTheDocument()
  })
})

describe('Test F — Entry list 渲染', () => {
  it('真实渲染 title / feedTitle / read-unread / starred；正文不出现', async () => {
    const items = [
      entry('e1.a', { title: '未读文章', read: false, starred: false }),
      entry('e1.b', { title: '已读收藏', read: true, starred: true }),
    ]
    vi.stubGlobal('fetch', mockApi(
      () => jsonResponse(FEEDS),
      () => jsonResponse(page(items)),
    ))
    renderApp()

    expect(await screen.findByText('未读文章')).toBeInTheDocument()
    expect(screen.getByText('已读收藏')).toBeInTheDocument()
    // feedTitle 出现在 sidebar feed 按钮与 entry 行两处
    expect(screen.getAllByText('示例源 A').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByLabelText('未读')).toBeInTheDocument()
    expect(screen.getByLabelText('已收藏')).toBeInTheDocument()
    // 已读文章没有 unread 圆点
    expect(screen.queryAllByLabelText('未读')).toHaveLength(1)
    // 列表契约：数据里没有 contentText，正文绝不出现在 UI
    expect(document.body.textContent).not.toContain('contentText')
  })
})

describe('Test G — Empty state', () => {
  it('items=[] 显示 empty state，不是报错', async () => {
    vi.stubGlobal('fetch', mockApi(
      () => jsonResponse(FEEDS),
      () => jsonResponse(page([])),
    ))
    renderApp()

    expect(await screen.findByText('这里还没有文章')).toBeInTheDocument()
    expect(screen.queryByText('文章加载失败')).not.toBeInTheDocument()
  })

  it('Starred 空列表显示专属文案', async () => {
    vi.stubGlobal('fetch', mockApi(
      () => jsonResponse(FEEDS),
      () => jsonResponse(page([])),
    ))
    renderApp()

    fireEvent.click(await screen.findByRole('button', { name: 'Starred' }))
    expect(await screen.findByText('还没有收藏文章')).toBeInTheDocument()
  })
})

describe('Test H — Error state', () => {
  it('entries 请求失败 → error state + 重试；App 不崩溃', async () => {
    let fail = true
    vi.stubGlobal('fetch', mockApi(
      () => jsonResponse(FEEDS),
      () =>
        fail
          ? jsonResponse({ error: { type: 'upstream_error', message: '上游暂时不可用' } }, 502)
          : jsonResponse(page([entry('e1.a')])),
    ))
    renderApp()

    expect(await screen.findByText('文章加载失败')).toBeInTheDocument()
    expect(screen.getByText('上游暂时不可用')).toBeInTheDocument()

    fail = false
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('文章 e1.a')).toBeInTheDocument()
  })
})

describe('Test I — View 切换', () => {
  it('点击 Unread → 请求 view=unread；点击 Starred → view=starred', async () => {
    const fetchMock = mockApi(
      () => jsonResponse(FEEDS),
      () => jsonResponse(page([])),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderApp()
    await screen.findByText('没有未读文章').catch(() => {}) // 等初始加载完成

    fireEvent.click(await screen.findByRole('button', { name: 'Unread' }))
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      const unreadCall = calls.find((u) => u.includes('view=unread'))
      expect(unreadCall).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Starred' }))
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      expect(calls.find((u) => u.includes('view=starred'))).toBeDefined()
    })
  })
})

describe('Test J — Feed 切换', () => {
  it('点击 feed → 请求带 feedUrl；点击 All Feeds → 恢复无 feedUrl', async () => {
    const fetchMock = mockApi(
      () => jsonResponse(FEEDS),
      () => jsonResponse(page([entry('e1.a')])),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderApp()
    await screen.findByText('文章 e1.a')

    fireEvent.click(screen.getByRole('button', { name: '示例源 A' }))
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      expect(
        calls.find((u) => u.includes(`feedUrl=${encodeURIComponent('https://a.example.com/feed.xml')}`)),
      ).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: 'All Feeds' }))
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      const allFeedsCalls = calls.filter((u) => u.startsWith('/api/v1/entries') && !u.includes('feedUrl='))
      expect(allFeedsCalls.length).toBeGreaterThanOrEqual(2)
    })
  })
})

describe('Test K — Entry selection', () => {
  it('点击 entry → selected UI + ReaderPlaceholder 响应 + 不调用 detail API', async () => {
    const fetchMock = mockApi(
      () => jsonResponse(FEEDS),
      () => jsonResponse(page([entry('e1.a', { title: '可点击的文章' })])),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    expect(screen.getByText('选择一篇文章开始阅读')).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: /可点击的文章/ }))

    // 右栏响应：显示该文章 title（来自 Query cache，不是 detail API）
    expect(await screen.findAllByText('可点击的文章')).toHaveLength(2)
    // selected 状态体现在 aria-pressed
    expect(screen.getByRole('button', { name: /可点击的文章/ })).toHaveAttribute('aria-pressed', 'true')

    // 只调用了 /feeds 和 /entries —— 没有任何 detail 请求
    const calls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(calls.every((u) => u.startsWith('/api/v1/feeds') || u.startsWith('/api/v1/entries?'))).toBe(true)
    expect(calls.some((u) => /\/api\/v1\/entries\/e1\./.test(u))).toBe(false)
  })

  it('切换 view 后 selection 清空，右栏回到占位文案', async () => {
    vi.stubGlobal('fetch', mockApi(
      () => jsonResponse(FEEDS),
      () => jsonResponse(page([entry('e1.a', { title: '会被取消选中的文章' })])),
    ))
    renderApp()

    fireEvent.click(await screen.findByRole('button', { name: /会被取消选中的文章/ }))
    expect(screen.queryByText('选择一篇文章开始阅读')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Unread' }))
    expect(await screen.findByText('选择一篇文章开始阅读')).toBeInTheDocument()
  })
})

describe('Test L — Load more', () => {
  it('第一页 nextCursor → 点击加载更多 → cursor 原样传回 → 两页都渲染', async () => {
    const cursor = 'c1.fake-_cursor_0005'
    let callCount = 0
    const fetchMock = mockApi(
      () => jsonResponse(FEEDS),
      () => {
        callCount += 1
        return callCount === 1
          ? jsonResponse(page([entry('e1.page1', { title: '第一页文章' })], cursor))
          : jsonResponse(page([entry('e1.page2', { title: '第二页文章' })], null))
      },
    )
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    expect(await screen.findByText('第一页文章')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '加载更多' }))

    expect(await screen.findByText('第二页文章')).toBeInTheDocument()
    expect(screen.getByText('第一页文章')).toBeInTheDocument()
    expect(screen.getByText('已经到底了')).toBeInTheDocument()

    // 第二次请求的 cursor 与第一页返回的 nextCursor 完全一致（opaque 透传）
    const secondCall = String(fetchMock.mock.calls.filter((c) => String(c[0]).startsWith('/api/v1/entries'))[1]![0])
    expect(new URL(secondCall, 'http://local.test').searchParams.get('cursor')).toBe(cursor)
  })

  it('无 nextCursor → 不显示加载更多按钮', async () => {
    vi.stubGlobal('fetch', mockApi(
      () => jsonResponse(FEEDS),
      () => jsonResponse(page([entry('e1.only', { title: '唯一一篇文章' })], null)),
    ))
    renderApp()

    expect(await screen.findByText('唯一一篇文章')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '加载更多' })).not.toBeInTheDocument()
    expect(screen.getByText('已经到底了')).toBeInTheDocument()
  })
})
