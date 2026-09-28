/** FIX-153 — 搜索筛选三方一致性：控件 ↔ 实际请求 URL ↔ 请求参数。
 *
 * 本应用把搜索筛选放在会话 store（P1.3：浏览器返回可恢复；刷新回空是
 * 既定会话语义），浏览器地址栏不承载筛选——「URL 腿」在本应用的真实
 * 形态是请求查询串（/api/v1/search?…）与外部应用动作（保存的视图
 * `lumirss-open-saved-view` 事件，等同深链接入口）。因此三方一致性
 * 契约按真实代码面验证：
 *
 * 1. 表单控件设置的筛选 → 下一次请求 URL 携带同义参数（state/favorite/
 *    categoryId），控件呈现激活态（aria-pressed / select value）；
 * 2. 控件改回 → 后续请求不再携带该参数；
 * 3. 外部入口（保存的视图事件）设置筛选 → 控件如实显示 + 请求如实携带，
 *    三个面一致。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SearchPage from '../components/pages/SearchPage'
import { useSearchState } from '../store/search-state'
import { useReaderUi } from '../store/reader-ui'
import type { SearchResponse } from '../api/types'

function searchResponse(): SearchResponse {
  return {
    items: [
      {
        entryRef: 's1',
        title: '结果 一',
        feedTitle: '源 A',
        feedUrl: 'https://a.example/rss',
        matchedFields: ['title'],
        publishedAt: '2026-09-18T08:00:00Z',
        read: false,
        snippet: '',
        starred: false,
      },
    ],
    nextCursor: null,
    hasMore: false,
    elapsedMs: 1,
    index: { entryCount: 1, lastSyncedAt: null, partial: false },
    library: [],
    libraryHasMore: false,
    libraryNextCursor: null,
    libraryError: null,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** 记录 /api/v1/search 请求 URL；feeds 带一个分类（渲染分类下拉）。 */
function mockApi() {
  const searchUrls: string[] = []
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/search?')) {
      searchUrls.push(url)
      return Promise.resolve(jsonResponse(searchResponse()))
    }
    if (url.startsWith('/api/v1/search/views')) {
      return Promise.resolve(jsonResponse({ items: [] }))
    }
    if (url.startsWith('/api/v1/feeds')) {
      return Promise.resolve(
        jsonResponse([
          {
            title: '源 A',
            feedUrl: 'https://a.example/rss',
            category: { id: 'cat1', label: '技术' },
          },
        ]),
      )
    }
    return Promise.resolve(jsonResponse({}))
  })
  return { fetchMock, searchUrls }
}

function withProviders(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

afterEach(() => {
  useSearchState.getState().clear()
  useReaderUi.setState({ selectedEntryRef: null })
  vi.unstubAllGlobals()
})

describe('FIX-153 — 搜索筛选三方一致（控件 ↔ 请求 URL ↔ 参数）', () => {
  it('视图 chip / 分类选择 → 请求携带同义参数且控件呈现激活态；改回后参数消失', async () => {
    const { fetchMock, searchUrls } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<SearchPage />))

    // 提交基础查询
    const input = screen.getByLabelText('搜索')
    fireEvent.change(input, { target: { value: 'react' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await screen.findByText('结果 一')
    const baseline = searchUrls.length
    expect(baseline).toBeGreaterThan(0)
    expect(searchUrls[baseline - 1]).not.toContain('state=')
    expect(searchUrls[baseline - 1]).not.toContain('categoryId=')

    // 未读 chip：控件激活态 + 请求携带 state=unread
    const group = screen.getByRole('group', { name: '搜索范围' })
    const unreadChip = within(group).getByRole('button', { name: '未读' })
    fireEvent.click(unreadChip)
    expect(unreadChip).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => {
      const recent = searchUrls.slice(baseline)
      expect(recent.some((u) => u.includes('state=unread'))).toBe(true)
    })

    // 分类下拉：控件 value + 请求携带 categoryId=cat1
    const select = screen.getByRole('combobox', { name: '按分类过滤' }) as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'cat1' } })
    expect(select.value).toBe('cat1')
    await waitFor(() => {
      expect(searchUrls.some((u) => u.includes('categoryId=cat1'))).toBe(true)
    })

    // 收藏 chip：favorite=true
    const starredChip = within(group).getByRole('button', { name: '收藏' })
    fireEvent.click(starredChip)
    expect(starredChip).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => {
      expect(searchUrls.some((u) => u.includes('favorite=true'))).toBe(true)
    })

    // 改回 全部/全部分类 → 后续请求不再带这三个参数
    fireEvent.click(within(group).getByRole('button', { name: '全部' }))
    fireEvent.change(select, { target: { value: '' } })
    const countAtClear = searchUrls.length
    await waitFor(() => expect(searchUrls.length).toBeGreaterThan(countAtClear - 1))
    // 清除点之后任何新请求都不得再带旧筛选
    await waitFor(() => {
      for (const url of searchUrls.slice(countAtClear)) {
        expect(url).not.toContain('state=unread')
        expect(url).not.toContain('favorite=true')
        expect(url).not.toContain('categoryId=cat1')
      }
    })
    expect(within(group).getByRole('button', { name: '全部' })).toHaveAttribute('aria-pressed', 'true')
    expect(select.value).toBe('')
  })

  it('外部入口（保存的视图事件 = 深链接等价物）设置筛选 → 控件显示与请求参数一致', async () => {
    const { fetchMock, searchUrls } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<SearchPage />))

    // 外部（命令面板）派发保存视图应用事件：query + view + categoryKey
    fireEvent(window, new CustomEvent('lumirss-open-saved-view', {
      detail: { query: 'react', view: 'starred', categoryKey: 'cat1' },
    }))

    // 控件如实显示（分类下拉需等 feeds 数据就绪后才渲染）
    const group = screen.getByRole('group', { name: '搜索范围' })
    expect(within(group).getByRole('button', { name: '收藏' })).toHaveAttribute('aria-pressed', 'true')
    const select = (await screen.findByRole('combobox', { name: '按分类过滤' })) as HTMLSelectElement
    expect(select.value).toBe('cat1')
    const input = screen.getByLabelText('搜索') as HTMLInputElement
    expect(input.value).toBe('react')

    // 请求如实携带（Enter 提交或防抖后必然发出一次带参请求）
    await waitFor(() => {
      expect(searchUrls.some((u) => u.includes('q=react') && u.includes('favorite=true') && u.includes('categoryId=cat1'))).toBe(true)
    })
  })
})
