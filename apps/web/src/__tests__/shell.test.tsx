import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

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

/** 0011：RSS 订阅默认收起（disclosure）——展开后才能看到 feed 列表。
 * 主导航查询统一限定在侧栏 nav 内，避免与底部导航岛/移动顶栏同名控件歧义。 */
const sidebarNav = () => within(screen.getByRole('navigation', { name: '主导航' }))

function expandRssDisclosure() {
  fireEvent.click(sidebarNav().getByRole('button', { name: /RSS 订阅/ }))
}

describe('Test E — Shell loading', () => {
  it('feeds / entries pending 时存在 loading UI', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => new Promise<Response>(() => {})),
    )
    renderApp()

    // 0011：RSS 根节点默认收起，展开后才出现订阅 skeleton（AC3）
    expandRssDisclosure()
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

    expect((await screen.findAllByText('未读文章')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('已读收藏').length).toBeGreaterThan(0)
    // feedTitle 出现在 sidebar feed 按钮与 entry 行两处
    //（0011：feed 按钮在 disclosure 内，先展开）
    expandRssDisclosure()
    expect(screen.getAllByText('示例源 A').length).toBeGreaterThanOrEqual(2)
    // 0009 Gate 2：收藏标记改为 lucide 星形图标（aria-label 保留）
    //（0011：桌面 EntryRow + 移动 EntryCard 双渲染 → 两个星标）
    expect(screen.getAllByLabelText('已收藏').length).toBe(2)
    // 未读状态不只靠颜色：标题字重差异（font-medium vs font-normal）。
    // 圆点是纯视觉信号（aria-hidden），语义由字重 + 结构承载（AC10）。
    const unreadTitles = screen.getAllByText('未读文章')
    const readTitles = screen.getAllByText('已读收藏')
    for (const t of unreadTitles) expect(t.className).toContain('font-medium')
    for (const t of readTitles) expect(t.className).toContain('font-normal')
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

    // 0011：工作区「收藏」限定在主导航内（底部导航岛同名 tab 不歧义）
    fireEvent.click(sidebarNav().getByRole('button', { name: '收藏' }))
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
    expect((await screen.findAllByText('文章 e1.a')).length).toBeGreaterThan(0)
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

    // 0011：「未读」为时间线行的过滤子项（在主导航内）
    fireEvent.click(sidebarNav().getByRole('button', { name: '未读' }))
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      const unreadCall = calls.find((u) => u.includes('view=unread'))
      expect(unreadCall).toBeDefined()
    })

    fireEvent.click(sidebarNav().getByRole('button', { name: '收藏' }))
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
    // 0011：桌面 Row + 移动 Card 双渲染（双份文本）
    expect((await screen.findAllByText('文章 e1.a')).length).toBeGreaterThan(0)

    // 0011：feed 在 RSS disclosure 内（默认收起），先展开
    expandRssDisclosure()
    fireEvent.click(sidebarNav().getByRole('button', { name: '示例源 A' }))
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      expect(
        calls.find((u) => u.includes(`feedUrl=${encodeURIComponent('https://a.example.com/feed.xml')}`)),
      ).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: /全部信息流/ }))
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      const allFeedsCalls = calls.filter((u) => u.startsWith('/api/v1/entries') && !u.includes('feedUrl='))
      expect(allFeedsCalls.length).toBeGreaterThanOrEqual(2)
    })
  })
})

describe('Test K — Entry selection', () => {
  it('点击 entry → selected UI + Reader 发起 Detail 请求（0006 行为）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
      // Detail：/api/v1/entries/{ref}（无 query）
      if (/^\/api\/v1\/entries\/e1\./.test(url)) {
        return jsonResponse({
          entryRef: 'e1.a',
          title: '可点击的文章',
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
      if (url.startsWith('/api/v1/entries')) {
        return jsonResponse(page([entry('e1.a', { title: '可点击的文章' })]))
      }
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    expect(screen.getByText('选择一篇文章开始阅读')).toBeInTheDocument()
    // 0011：双渲染下取第一个可点击实例
    const clickables = await screen.findAllByRole('button', { name: /可点击的文章/ })
    fireEvent.click(clickables[0]!)

    // 0006：选择后真实请求 Detail（GET /api/v1/entries/e1.a）
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => /\/api\/v1\/entries\/e1\./.test(String(c[0])))).toBe(true)
    })
    // selected 状态体现在 aria-pressed（两个实例均应选中）
    for (const b of screen.getAllByRole('button', { name: /可点击的文章/ })) {
      expect(b).toHaveAttribute('aria-pressed', 'true')
    }
  })

  it('切换 view 后 selection 清空，右栏回到占位文案', async () => {
    vi.stubGlobal('fetch', mockApi(
      () => jsonResponse(FEEDS),
      (url) =>
        // Reader（Detail）请求 pending：切 view 后回到占位文案即可
        /\/api\/v1\/entries\/e1\./.test(url)
          ? new Promise<Response>(() => {})
          : jsonResponse(page([entry('e1.a', { title: '会被取消选中的文章' })])),
    ))
    renderApp()

    fireEvent.click((await screen.findAllByRole('button', { name: /会被取消选中的文章/ }))[0]!)
    expect(screen.queryByText('选择一篇文章开始阅读')).not.toBeInTheDocument()

    fireEvent.click(sidebarNav().getByRole('button', { name: '未读' }))
    expect(await screen.findByText('选择一篇文章开始阅读')).toBeInTheDocument()
  })
})

describe('Test L — 无限滚动（0011：替换「加载更多」按钮）', () => {
  // jsdom 无 IntersectionObserver 真实回调：mock 为手动触发 isIntersecting，
  // 验证哨兵滚入 → 自动 fetchNextPage（cursor 原样透传）。
  let intersectCb: IntersectionObserverCallback | null = null
  beforeEach(() => {
    intersectCb = null
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(cb: IntersectionObserverCallback) {
          intersectCb = cb
        }
        observe() {}
        disconnect() {}
        unobserve() {}
      },
    )
  })

  it('哨兵滚入视口 → 自动拉下一页，cursor 原样传回，两页都渲染', async () => {
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

    expect((await screen.findAllByText('第一页文章')).length).toBeGreaterThan(0)
    // 哨兵滚入（IntersectionObserver 回调 isIntersecting=true）
    act(() => {
      intersectCb?.(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      )
    })

    expect((await screen.findAllByText('第二页文章')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('第一页文章').length).toBeGreaterThan(0)
    expect(screen.getByText('已经到底了')).toBeInTheDocument()

    // 第二次请求的 cursor 与第一页返回的 nextCursor 完全一致（opaque 透传）
    const secondCall = String(fetchMock.mock.calls.filter((c) => String(c[0]).startsWith('/api/v1/entries'))[1]![0])
    expect(new URL(secondCall, 'http://local.test').searchParams.get('cursor')).toBe(cursor)
  })

  it('无 nextCursor → 无哨兵拉取，显示「已经到底了」终态', async () => {
    vi.stubGlobal('fetch', mockApi(
      () => jsonResponse(FEEDS),
      () => jsonResponse(page([entry('e1.only', { title: '唯一一篇文章' })], null)),
    ))
    renderApp()

    expect((await screen.findAllByText('唯一一篇文章')).length).toBeGreaterThan(0)
    expect(screen.getByText('已经到底了')).toBeInTheDocument()
    // 无下一页：哨兵不注册观察器（无回调可触发）
    expect(intersectCb).toBeNull()
  })
})
