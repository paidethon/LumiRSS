/** FIX-152 — 移动端稍后读：打开条目进详情 + 返回保留列表状态。
 *
 * 契约（与 0014a Gate 2 收藏腿同一移动布局机制）：
 * - home section + view='read-later'（稍后读 = 服务端时间线视图），
 *   点时间线行卡片 → selectedEntryRef 置位 → 列表让位（max-lg:hidden），
 *   Reader 全屏加载详情；
 * - 点「返回文章列表」→ selectedEntryRef 清空，section/view/scope
 *   不变（仍是 home + read-later），列表从 Query 缓存恢复且不重新请求
 *   时间线；
 * - 收藏腿由 acceptance-0014a.test.tsx Gate 2 覆盖，本文件补稍后读腿。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { useReaderUi } from '../store/reader-ui'
import type { EntryListResponse } from '../api/types'

const FEEDS = [
  { title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml', category: null },
]

function entry(ref: string): EntryListResponse['items'][number] {
  return {
    entryRef: ref,
    title: `稍后读文章 ${ref}`,
    feedTitle: '示例源 A',
    author: null,
    url: null,
    publishedAt: '2026-08-28T00:00:00Z',
    read: false,
    starred: false,
  }
}

function timelineRow(ref: string) {
  return {
    itemRef: `rss:${ref}`,
    addedAt: '2026-09-01T08:00:00Z',
    stale: false,
    entry: entry(ref),
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function mockApi() {
  const timelineCalls: string[] = []
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
    if (url.startsWith('/api/v1/workspaces/read-later/timeline')) {
      timelineCalls.push(url)
      return jsonResponse({ items: [timelineRow('e1.later')], nextCursor: null })
    }
    if (url.startsWith('/api/v1/workspaces/read-later/items')) {
      return jsonResponse({
        items: [{ itemRef: 'rss:e1.later', addedAt: '2026-09-01T08:00:00Z', position: 0 }],
      })
    }
    if (url.startsWith('/api/v1/entries/e1.later')) {
      return jsonResponse({
        entryRef: 'e1.later',
        title: '稍后读文章 e1.later',
        feedTitle: '示例源 A',
        author: null,
        url: 'https://example.com/article',
        publishedAt: null,
        read: false,
        starred: false,
        contentText: '稍后读正文',
        contentHtml: '<p>稍后读正文</p>',
      })
    }
    if (url.startsWith('/api/v1/entries')) {
      return jsonResponse({ items: [], nextCursor: null })
    }
    return jsonResponse({})
  })
  return { fetchMock, timelineCalls }
}

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({
    section: 'home',
    view: 'read-later',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
  // jsdom 无 IntersectionObserver（无限滚动哨兵）
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe() {}
      disconnect() {}
      unobserve() {}
    },
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('FIX-152 — 移动端稍后读：打开进详情 + 返回保留列表', () => {
  it('点稍后读行 → Reader 全屏加载详情；back 返回列表（section/view/scope 不变，时间线不重拉）', async () => {
    const { fetchMock, timelineCalls } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<App />))

    // 稍后读列表可见（行标题来自时间线端点）
    const rowButtons = await screen.findAllByRole('button', { name: /稍后读文章 e1\.later/ })
    expect(rowButtons.length).toBeGreaterThan(0)
    const callsAfterLoad = timelineCalls.length
    expect(callsAfterLoad).toBeGreaterThan(0)

    // 打开文章 → selectedEntryRef 置位，列表让位，Reader 全屏
    fireEvent.click(rowButtons[0]!)
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.later')

    const main = document.querySelector('main')!
    const listSection = Array.from(main.querySelectorAll(':scope > section'))[0] as HTMLElement
    // compact 档列表让位 = 整列 hidden（App timelineReaderOpenCls）
    await waitFor(() => expect(listSection).toHaveClass('hidden'))

    // Reader 全屏加载详情正文
    await screen.findByText('稍后读正文')
    const readerSection = Array.from(main.querySelectorAll(':scope > section')).find((s) =>
      s.textContent?.includes('稍后读正文'),
    ) as HTMLElement
    expect(readerSection).toBeDefined()
    expect(readerSection).not.toHaveClass('hidden')

    // 状态保持：仍是 home + read-later（没有跳到别的 section/视图）
    expect(useReaderUi.getState().section).toBe('home')
    expect(useReaderUi.getState().view).toBe('read-later')

    // back → 返回列表；时间线不重新请求（Query 缓存恢复）
    fireEvent.click(screen.getByRole('button', { name: '返回文章列表' }))
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
    expect(useReaderUi.getState().section).toBe('home')
    expect(useReaderUi.getState().view).toBe('read-later')
    await waitFor(() => expect(listSection).not.toHaveClass('hidden'))
    expect(
      (await within(listSection).findAllByText(/稍后读文章 e1\.later/)).length,
    ).toBeGreaterThan(0)
    expect(timelineCalls.length).toBe(callsAfterLoad)
  })
})
