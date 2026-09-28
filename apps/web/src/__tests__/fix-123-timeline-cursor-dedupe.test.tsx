/** FIX-123 回归 — 无限滚动分页的 cursor 去重与终止。
 *
 * 缺陷场景：服务端异常（或上游分页错乱）让 nextCursor 重复返回已经
 * 请求过的 cursor → getNextPageParam 永远给出「下一页」→ fetchNextPage
 * 无限循环，同一页反复追加；跨页重叠的条目在列表里重复出现。
 *
 * 修复契约：
 * - 查询层：getNextPageParam 发现候选 cursor 已在 pageParams 里 → 返回
 *   undefined（hasNextPage=false，分页诚实终止）——entries / read-later
 *   时间线 / search 双腿 cursor 同一规则；
 * - 展示层：列表 flatMap 后按 entryRef 保序去重（重叠页不再重复显示）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useEntries, useReadLaterTimeline, useSearch } from '../api/queries'
import { dedupeByEntryRef, dedupeByItemRef } from '../components/EntryList'
import type { EntryListItem, EntryListResponse } from '../api/types'
import type { ContentScope } from '../lib/navigation'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function item(ref: string, overrides: Partial<EntryListItem> = {}): EntryListItem {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: '2026-09-01T00:00:00Z',
    read: false,
    starred: false,
    ...overrides,
  }
}

function entriesPage(items: EntryListItem[], nextCursor: string | null): EntryListResponse {
  return { items, nextCursor }
}

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const Wrapper = ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client }, children)
  return { client, Wrapper }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-123 — 重复 cursor 终止（查询层）', () => {
  it('useEntries：服务端把同一 cursor 返回两次 → 第二次后 hasNextPage=false，fetchNextPage 不再发请求', async () => {
    // 页1（cursor=null）→ c1；页2（cursor=c1）→ 又返回 c1（异常重复）。
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://lumirss.test')
      const cursor = url.searchParams.get('cursor')
      if (cursor === null) {
        return Promise.resolve(jsonResponse(entriesPage([item('e1'), item('e2')], 'c1')))
      }
      return Promise.resolve(jsonResponse(entriesPage([item('e3'), item('e4')], 'c1')))
    })
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()
    const scope: ContentScope = { kind: 'all' }
    const { result } = renderHook(() => useEntries(scope, 'all'), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.data?.pages.length).toBe(1))
    await act(async () => {
      await result.current.fetchNextPage()
    })
    await waitFor(() => expect(result.current.data?.pages.length).toBe(2))

    // 修复契约：候选 cursor 已请求过 → 分页终止。
    expect(result.current.hasNextPage).toBe(false)
    const callsAfterTwoPages = fetchMock.mock.calls.length
    await act(async () => {
      await result.current.fetchNextPage()
    })
    expect(fetchMock.mock.calls.length).toBe(callsAfterTwoPages)
    client.clear()
  })

  it('useReadLaterTimeline：同一规则终止（cursor 重复 → hasNextPage=false）', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://lumirss.test')
      const cursor = url.searchParams.get('cursor')
      if (cursor === null) {
        return Promise.resolve(
          jsonResponse({ items: [{ itemRef: 'w1', addedAt: '2026-09-01T00:00:00Z', stale: false }], nextCursor: 'c1' }),
        )
      }
      return Promise.resolve(
        jsonResponse({ items: [{ itemRef: 'w2', addedAt: '2026-09-02T00:00:00Z', stale: false }], nextCursor: 'c1' }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()
    const { result } = renderHook(() => useReadLaterTimeline('newest'), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.data?.pages.length).toBe(1))
    await act(async () => {
      await result.current.fetchNextPage()
    })
    await waitFor(() => expect(result.current.data?.pages.length).toBe(2))
    expect(result.current.hasNextPage).toBe(false)
    const callsAfterTwoPages = fetchMock.mock.calls.length
    await act(async () => {
      await result.current.fetchNextPage()
    })
    expect(fetchMock.mock.calls.length).toBe(callsAfterTwoPages)
    client.clear()
  })

  it('useSearch：双腿 cursor 对（cursor, libraryCursor）重复 → 终止', async () => {
    const body = {
      items: [],
      hasMore: true,
      nextCursor: 'c1',
      libraryHasMore: true,
      libraryNextCursor: 'l1',
      libraryError: null,
      elapsedMs: 1,
      index: { entryCount: 0, partial: false },
    }
    const fetchMock = vi.fn(() =>
      Promise.resolve(jsonResponse({ ...body, nextCursor: 'c1', libraryNextCursor: 'l1' })),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()
    const { result } = renderHook(() => useSearch('词', {}), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.data?.pages.length).toBe(1))
    await act(async () => {
      await result.current.fetchNextPage()
    })
    await waitFor(() => expect(result.current.data?.pages.length).toBe(2))
    // 服务端异常：永远返回同一对 (c1, l1) → 修复后终止。
    expect(result.current.hasNextPage).toBe(false)
    const callsAfterTwoPages = fetchMock.mock.calls.length
    await act(async () => {
      await result.current.fetchNextPage()
    })
    expect(fetchMock.mock.calls.length).toBe(callsAfterTwoPages)
    client.clear()
  })
})

describe('FIX-123 — 跨页重复条目去重（展示层，纯函数）', () => {
  it('dedupeByEntryRef：保序保留首次出现，重复 entryRef 丢弃', () => {
    const rows = [item('e1'), item('e2'), item('e1', { title: '重复出现的 e1' }), item('e3'), item('e2')]
    expect(dedupeByEntryRef(rows).map((r) => r.entryRef)).toEqual(['e1', 'e2', 'e3'])
  })

  it('dedupeByItemRef：read-later 行同规则', () => {
    const rows = [
      { itemRef: 'w1', addedAt: '1', stale: false },
      { itemRef: 'w2', addedAt: '2', stale: false },
      { itemRef: 'w1', addedAt: '3', stale: false },
    ]
    expect(dedupeByItemRef(rows).map((r) => r.itemRef)).toEqual(['w1', 'w2'])
  })
})
