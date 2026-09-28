/** FIX-127 回归 — 订阅树中「点击订阅名称」与「展开箭头」两行为分离。
 *
 * 契约（0011 §6–§9）：
 * - feed 名称主区域 → 导航到该订阅的文章列表（entries 请求带 feedUrl），
 *   绝不充当展开/收起箭头；
 * - chevron（aria-label 承载 展开/收起）→ 只切换树展开态，绝不触发
 *   导航/数据请求；
 * - 名称点击后树保持展开（可继续切换其它订阅）。
 *
 * 判定基准：Sidebar 树当前实现已满足（RSS 行/分类行/feed 行三层均
 * 主区域=scope、chevron=tree）——本文件为验证性基线（BASELINE_OK）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { EntryListResponse } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

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

const sidebarNav = () => within(screen.getByRole('navigation', { name: '主导航' }))

beforeEach(() => {
  useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-127 — 订阅名称点击 ≠ 展开箭头', () => {
  it('chevron 只切换树展开态（不发 feedUrl 请求）；feed 名称点击导航到该订阅列表且树保持展开', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
      if (url.startsWith('/api/v1/entries')) {
        return jsonResponse({ items: [entry('e1.a')], nextCursor: null })
      }
      // 周边查询（继续阅读/最近打开等）与本次契约无关。
      return jsonResponse({ items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getAllByText('文章 e1.a').length).toBeGreaterThan(0))

    const entriesCalls = () => fetchMock.mock.calls.map((c) => String(c[0])).filter((u) => u.startsWith('/api/v1/entries'))

    // 1) chevron 展开 RSS 树：aria-expanded 翻转，且不触发任何 feedUrl 导航请求。
    const rssChevron = sidebarNav().getByRole('button', { name: '展开 RSS 分类' })
    fireEvent.click(rssChevron)
    const categoryChevron = sidebarNav().getByRole('button', { name: /展开 未分组/ })
    expect(categoryChevron).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(categoryChevron)
    await waitFor(() => {
      expect(sidebarNav().getByRole('button', { name: /收起 未分组/ })).toHaveAttribute('aria-expanded', 'true')
    })
    // 树已可见（feed 名称按钮出现），但没有发生任何 feedUrl 过滤导航。
    expect(sidebarNav().getByRole('button', { name: '示例源 A' })).toBeInTheDocument()
    expect(entriesCalls().every((u) => !u.includes('feedUrl='))).toBe(true)

    // 2) feed 名称主区域点击 → 导航到该订阅的文章列表（feedUrl 请求发出），
    //    且树保持展开（名称点击绝不被当成箭头）。
    fireEvent.click(sidebarNav().getByRole('button', { name: '示例源 A' }))
    await waitFor(() => {
      expect(
        entriesCalls().some((u) => u.includes(`feedUrl=${encodeURIComponent('https://a.example.com/feed.xml')}`)),
      ).toBe(true)
    })
    expect(sidebarNav().getByRole('button', { name: /收起 未分组/ })).toHaveAttribute('aria-expanded', 'true')
  })
})
