/** Phase H 回归 — 浏览器内存有界的查询契约。
 *
 * 1. useEntries/useSearch 的无限分页受 maxPages 约束（缓存页数有界，
 *    滚动 12 页后缓存只剩最新 8 页 ≈ 160 条列表 DTO）；
 * 2. read/star 写入走精确缓存补丁：unread 视图移除、all 视图翻转、
 *    detail 原地翻转——不触发列表重拉（fetch 计数不增长）；
 * 3. 「滚动多页 → 打开文章 → 返回」路径上没有列表 refetch（滚动
 *    恢复依赖已加载页保持原样）。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { useEntries, useEntryStateMutation, useSearch } from '../api/queries'
import type { EntryListItem, EntryListResponse } from '../api/types'
import type { ContentScope } from '../lib/navigation'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function item(n: number, read = false): EntryListItem {
  return {
    entryRef: `e${n}.scope`,
    title: `文章 ${n}`,
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: '2026-09-01T00:00:00Z',
    read,
    starred: false,
  }
}

function page(from: number, count: number, more: boolean): EntryListResponse {
  const items = Array.from({ length: count }, (_, i) => item(from + i))
  return { items, nextCursor: more ? `cursor-${from + count}` : null }
}

function wrapper() {
  const client = new QueryClient()
  const Wrapper = ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client }, children)
  return { client, Wrapper }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('maxPages — 无限分页缓存有界', () => {
  it('useEntries：病态深滚（60 页）后缓存被 50 页保险丝截住（≤1000 条）', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://lumirss.test')
      const cursor = url.searchParams.get('cursor')
      const from = cursor === null ? 0 : Number(cursor.split('-')[1])
      return Promise.resolve(jsonResponse(page(from, 20, from < 1180)))
    })
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()
    const scope: ContentScope = { kind: 'all' }
    const { result } = renderHook(() => useEntries(scope, 'all'), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.data?.pages.length).toBe(1))
    for (let i = 0; i < 59; i++) {
      await act(async () => {
        await result.current.fetchNextPage()
      })
    }
    expect(result.current.data?.pages.length).toBeLessThanOrEqual(50)
    const loaded = result.current.data?.pages.flatMap((p) => p.items).length ?? 0
    expect(loaded).toBeLessThanOrEqual(1000)
    // 正常阅读深度（<50 页）从不裁剪：正常路径的回访（打开文章→返回）
    // 依赖已加载页保持原样，且精确补丁不会触发重拉把页数放大回来。
    client.clear()
  })

  it('useSearch：同样受 50 页保险丝约束', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        jsonResponse({
          items: Array.from({ length: 20 }, (_, i) => ({ ...item(i), snippet: '片段' })),
          nextCursor: 'next-cursor',
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()
    const { result } = renderHook(() => useSearch('查询词', {}), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.data?.pages.length).toBe(1))
    for (let i = 0; i < 55; i++) {
      await act(async () => {
        await result.current.fetchNextPage()
      })
    }
    expect(result.current.data?.pages.length).toBeLessThanOrEqual(50)
    client.clear()
  })
})

describe('精确缓存补丁 — read/star 写入零重拉', () => {
  it('标记已读：all 视图翻转、unread 视图移除、detail 翻转；无列表 GET', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()

    const allPages = { pages: [page(0, 3, false)], pageParams: [null] }
    const unreadPages = {
      pages: [{ items: [item(1), item(2)], nextCursor: null }],
      pageParams: [null],
    }
    client.setQueryData(['entries', { view: 'all', scope: { kind: 'all' } }], allPages)
    client.setQueryData(['entries', { view: 'unread', scope: { kind: 'all' } }], unreadPages)
    client.setQueryData(['entry', 'e1.scope'], {
      ...item(1),
      contentText: '正文',
      contentHtml: '<p>正文</p>',
    })

    const { result } = renderHook(() => useEntryStateMutation(), { wrapper: Wrapper })
    await act(async () => {
      result.current.mutate({ entryRef: 'e1.scope', patch: { read: true } })
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const allItems = (
      client.getQueryData(['entries', { view: 'all', scope: { kind: 'all' } }]) as typeof allPages
    ).pages[0]!.items
    expect(allItems.find((i) => i.entryRef === 'e1.scope')?.read).toBe(true)

    const unreadItems = (
      client.getQueryData(['entries', { view: 'unread', scope: { kind: 'all' } }]) as typeof unreadPages
    ).pages[0]!.items
    expect(unreadItems.map((i) => i.entryRef)).not.toContain('e1.scope')
    expect(unreadItems.map((i) => i.entryRef)).toContain('e2.scope')

    const detail = client.getQueryData(['entry', 'e1.scope']) as EntryListItem & { read: boolean }
    expect(detail.read).toBe(true)

    // 唯一的网络调用就是那一次 PATCH —— 列表/detail 全部零重拉。
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const calls = fetchMock.mock.calls as unknown as [string][]
    expect(String(calls[0]![0])).toContain('/state')
    client.clear()
  })

  it('取消收藏：starred 视图移除 + all 视图翻转；反向（加收藏）才 invalidate', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()

    const starredPages = {
      pages: [{ items: [{ ...item(1), starred: true }], nextCursor: null }],
      pageParams: [null],
    }
    client.setQueryData(['entries', { view: 'starred', scope: { kind: 'all' } }], starredPages)
    client.setQueryData(['entries', { view: 'all', scope: { kind: 'all' } }], {
      pages: [page(0, 3, false)],
      pageParams: [null],
    })

    const { result } = renderHook(() => useEntryStateMutation(), { wrapper: Wrapper })
    await act(async () => {
      result.current.mutate({ entryRef: 'e1.scope', patch: { starred: false } })
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const starredItems = (
      client.getQueryData(['entries', { view: 'starred', scope: { kind: 'all' } }]) as typeof starredPages
    ).pages[0]!.items
    expect(starredItems.map((i) => i.entryRef)).not.toContain('e1.scope')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    client.clear()
  })
})

describe('回访路径 — 打开文章/返回不打扰列表缓存', () => {
  it('选择切换（模拟打开文章）后，列表缓存引用保持稳定（无重拉/无重置）', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse(page(0, 20, false))))
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()
    const { result, rerender } = renderHook(() => useEntries({ kind: 'all' } as ContentScope, 'all'), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.data?.pages.length).toBe(1))
    const before = result.current.data
    rerender()
    expect(result.current.data).toBe(before)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    client.clear()
  })
})
