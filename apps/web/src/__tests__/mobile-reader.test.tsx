import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { EntryListResponse } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

/** 0007 Test E/F/G — Mobile Reader Flow。
 *
 * 手机 list↔reader 显隐由 hidden class（CSS media query）实现；
 * jsdom 不加载 CSS，因此这里断言 DOM class 语义（section 是否含
 * hidden），是"语义近似"——真实视觉效果归真实浏览器 smoke（见 Spec）。 */

const FEEDS = [
  { title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml' },
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

function detailResponse(ref: string, overrides: Record<string, unknown> = {}): Response {
  return jsonResponse({
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源 A',
    author: null,
    url: 'https://example.com/article',
    publishedAt: '2026-08-28T00:00:00Z',
    read: false,
    starred: false,
    contentText: '纯文本正文',
    contentHtml: '<p>安全的 <strong>富文本</strong>正文</p><script>alert(1)</script>',
    ...overrides,
  })
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** fetch mock：记录 PATCH 请求 body，供 Test G 断言 set 语义。 */
function mockApi() {
  const patchBodies: string[] = []
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
    if (/^\/api\/v1\/entries\/e1\.[^/]+\/state$/.test(url)) {
      patchBodies.push(String(init?.body))
      return new Response(null, { status: 204 })
    }
    if (/^\/api\/v1\/entries\/e1\./.test(url)) return detailResponse('e1.a')
    if (url.startsWith('/api/v1/entries')) {
      return jsonResponse({ items: [entry('e1.a')], nextCursor: null })
    }
    throw new Error(`unexpected fetch: ${url}`)
  })
  return { fetchMock, patchBodies }
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

/** main 下两个 section：[0]=Entry List，[1]=Reader（App 布局结构）。 */
function panes() {
  const main = document.querySelector('main')
  const sections = main?.querySelectorAll(':scope > section')
  if (sections === undefined || sections.length < 2) {
    throw new Error('App main sections not found')
  }
  return { list: sections[0]!, reader: sections[1]! }
}

const isHidden = (el: Element) => el.classList.contains('hidden')

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

describe('Test E — Entry → mobile Reader', () => {
  it('无选中：list 可见 / reader 隐藏；点 Entry 后反转', async () => {
    const { fetchMock } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    const { list, reader } = panes()
    expect(isHidden(list)).toBe(false)
    expect(isHidden(reader)).toBe(true)

    fireEvent.click(await screen.findByRole('button', { name: /文章 e1\.a/ }))
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')

    expect(isHidden(list)).toBe(true)
    expect(isHidden(reader)).toBe(false)
  })
})

describe('Test F — Reader back', () => {
  it('点 ← 返回 → selectEntry(null)，list 立即从 cache 恢复；不重新请求 Detail', async () => {
    const { fetchMock } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    fireEvent.click(await screen.findByRole('button', { name: /文章 e1\.a/ }))
    // 等 Detail 加载完成（“富文本”在 <strong> 内，不能整句匹配）
    await screen.findByText('富文本')
    const detailCalls = fetchMock.mock.calls.filter((c) =>
      /\/api\/v1\/entries\/e1\.a$/.test(String(c[0])),
    ).length
    expect(detailCalls).toBe(1)

    const back = screen.getByRole('button', { name: '返回文章列表' })
    fireEvent.click(back)

    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
    const { list, reader } = panes()
    expect(isHidden(list)).toBe(false)
    expect(isHidden(reader)).toBe(true)

    // 返回后列表立即显示 cache 里的数据（无 loading skeleton、无白屏），
    // 且不重新请求 Detail（cache 复用，不是 reload）。
    // 注：ReaderPlaceholder 重新挂载可能触发 entries 的 stale-on-mount
    // 后台 refetch（0005 既有行为，数据不丢、UI 无 loading）——那不是
    // reload；这里断言的是用户可感知的“不重新加载”。
    expect(screen.getByRole('button', { name: /文章 e1\.a/ })).toBeInTheDocument()
    expect(screen.queryByLabelText('文章加载中')).not.toBeInTheDocument()

    await new Promise((resolve) => setTimeout(resolve, 50))
    const detailCallsAfter = fetchMock.mock.calls.filter((c) =>
      /\/api\/v1\/entries\/e1\.a$/.test(String(c[0])),
    ).length
    expect(detailCallsAfter).toBe(detailCalls)
  })
})

describe('Test G — Mobile Reader 业务回归', () => {
  it('手机布局中 Reader 仍加载 Detail、安全渲染、Read/Star 发出 set 语义 PATCH', async () => {
    const { fetchMock, patchBodies } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    fireEvent.click(await screen.findByRole('button', { name: /文章 e1\.a/ }))
    const { reader } = panes()
    expect(isHidden(reader)).toBe(false)

    // Detail 请求真实发生
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => /\/api\/v1\/entries\/e1\.a$/.test(String(c[0])))).toBe(true)
    })

    // 安全正文渲染：富文本显示，script 载荷被 DOMPurify 移除
    expect(await screen.findByText('富文本')).toBeInTheDocument()
    expect(document.body.querySelector('.article-content script')).toBeNull()

    // Read：未读 → 「标记为已读」→ PATCH {"read": true}（set 语义）
    fireEvent.click(screen.getByRole('button', { name: '标记为已读' }))
    await waitFor(() => expect(patchBodies).toContain('{"read":true}'))

    // Star：未收藏 → 「收藏」→ PATCH {"starred": true}
    fireEvent.click(screen.getByRole('button', { name: '收藏' }))
    await waitFor(() => expect(patchBodies).toContain('{"starred":true}'))
  })
})
