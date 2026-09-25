/** N148 相似标题区别提示 — 规范化/Jaccard 纯函数 + SearchPage chip。
 *
 * - 近同名（规范化 bigram Jaccard ≥ 0.8）→ 相关行渲染 相似标题 chip；
 * - 截然不同的标题 → 不渲染 chip（无误报）；
 * - chip 的对比 popover 并排展示 来源/时间/摘录，绝不合并结果行。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SearchPage from '../components/pages/SearchPage'
import { useSearchState } from '../store/search-state'
import { useReaderUi } from '../store/reader-ui'
import { useSearchBasket } from '../store/search-basket'
import {
  findSimilarTitleGroups,
  jaccardSimilarity,
  titleTokens,
  titlesSimilar,
} from '../lib/similar-titles'
import type { SearchResponse } from '../api/types'

describe('N148 相似标题纯函数', () => {
  it('规范化忽略大小写/标点/空白；bigram Jaccard ≥ 0.8 判相似', () => {
    expect([...titleTokens('Rust, 1.80!')].sort()).toEqual([...titleTokens('rust 180')].sort())
    expect(jaccardSimilarity(titleTokens('Rust 1.80 发布'), titleTokens('rust 180 发布'))).toBe(1)
    expect(titlesSimilar('Rust 1.80 发布', 'Rust 1.80 发布!')).toBe(true)
    expect(titlesSimilar('Rust 1.80 发布', 'Rust 1.80 发布啦（全新版本速览与深度解读）')).toBe(false)
    expect(titlesSimilar('完全不同的话题', 'Python 数据处理实战')).toBe(false)
  })

  it('findSimilarTitleGroups：相似对互列 ref；独立行不进组', () => {
    const items = [
      { entryRef: 'a', title: 'Rust 1.80 发布' },
      { entryRef: 'b', title: 'Rust 1.80 发布（转载）' },
      { entryRef: 'c', title: 'Python 数据处理' },
    ]
    const groups = findSimilarTitleGroups(items)
    expect(groups.get('a')).toEqual(['b'])
    expect(groups.get('b')).toEqual(['a'])
    expect(groups.has('c')).toBe(false)
  })
})

function searchResponse(items: Partial<SearchResponse['items'][number]>[]): SearchResponse {
  return {
    items: items.map((item) => ({
      entryRef: 'e1',
      title: '默认标题',
      feedTitle: '源A',
      feedUrl: 'https://a.example/rss',
      matchedFields: ['title'],
      publishedAt: '2026-09-23T08:00:00Z',
      read: false,
      snippet: '摘录内容',
      starred: false,
      ...item,
    })),
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

function withProviders(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

function stubFetch(routes: { prefix: string; respond: (req: { url: string }) => Response }[]) {
  const mock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    for (const route of routes) {
      if (url.startsWith(route.prefix)) {
        return Promise.resolve(route.respond({ url }))
      }
    }
    return Promise.resolve(jsonResponse({}))
  })
  vi.stubGlobal('fetch', mock)
}

const baseRoutes = () => [
  { prefix: '/api/v1/search/views', respond: () => jsonResponse({ items: [] }) },
  { prefix: '/api/v1/workspaces', respond: () => jsonResponse({ items: [] }) },
  { prefix: '/api/v1/feeds', respond: () => jsonResponse([]) },
  { prefix: '/api/v1/subscriptions', respond: () => jsonResponse([]) },
]

afterEach(() => {
  useSearchState.getState().clear()
  useReaderUi.setState({ selectedEntryRef: null })
  useSearchBasket.getState().reset()
  vi.unstubAllGlobals()
})

describe('N148 相似标题 chip（SearchPage）', () => {
  it('近同名标题行渲染 chip；独立标题行不受影响', async () => {
    stubFetch([
      ...baseRoutes(),
      {
        prefix: '/api/v1/search?',
        respond: () =>
          jsonResponse(
            searchResponse([
              { entryRef: 'dup-a', title: 'Rust 1.80 发布', feedTitle: '源A' },
              { entryRef: 'dup-b', title: 'Rust 1.80 发布（转载）', feedTitle: '源B' },
              { entryRef: 'other', title: 'Python 数据处理实战', feedTitle: '源C' },
            ]),
          ),
      },
    ])

    render(withProviders(<SearchPage />))
    const input = screen.getByLabelText('搜索')
    fireEvent.change(input, { target: { value: 'rust' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    // 两行近同名 → 各有一个 chip；独立行没有 chip。
    const chips = await screen.findAllByTestId('similar-title-chip')
    expect(chips).toHaveLength(2)

    // 打开对比 popover：并排展示两条（来源/时间/摘录）。
    fireEvent.click(chips[0])
    await waitFor(() => {
      const cards = screen.getAllByTestId('similar-title-card')
      expect(cards).toHaveLength(2)
      expect(screen.getByText('源A')).toBeInTheDocument()
      expect(screen.getByText('源B')).toBeInTheDocument()
    })
    // 结果行保持独立：三行都还在（绝不合并/隐藏；标题行带 data-entry-ref）。
    const rows = document.querySelectorAll('[data-entry-ref]')
    expect(rows).toHaveLength(3)
    expect(screen.getByText('Python 数据处理实战')).toBeInTheDocument()
  })
})
