/** P0 回归 — 搜索缓存 key 分层（2026-09-18 移动端专项）。
 *
 * 用户错误：「状态更新失败：undefined is not an object (evaluating
 * 'n.pages.map')」。根因：useEntryStateMutation.onSuccess 按 ['search']
 * 裸前缀枚举缓存，把保存视图清单（普通 query，形状 {items: […]}）误当
 * InfiniteData 调 data.pages.map —— BFF 已成功写入（204），但前端成功
 * 回调抛错，mutation 进入 error 态，ReaderHeader 误报「状态更新失败」。
 *
 * 本文件锁定契约：
 * 1. 同一 QueryClient 内分页搜索结果与保存视图清单并存时，已读/收藏
 *    mutation 必须成功（isError === false），保存视图缓存保持原样；
 * 2. 分页搜索缓存被精确补丁（all 翻转 / unread 过滤移除）；
 * 3. 双路游标字段（nextCursor/libraryNextCursor 等）在补丁后原样保留，
 *    fetchNextPage 仍可继续。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { SEARCH_RESULTS_KEY, useEntryStateMutation, useSearch } from '../api/queries'
import type { EntryListItem, SavedSearchViewList } from '../api/types'

/** 与 queries.ts 的 key 布局同构（['search', 'results', filters]）。 */
function resultsKey(filters: Record<string, unknown>) {
  return [...SEARCH_RESULTS_KEY, filters] as const
}

function patchResponse(): Response {
  return new Response(null, { status: 204 })
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

function savedViews(): SavedSearchViewList {
  return {
    items: [
      {
        id: 'view-1',
        name: '我的未读',
        query: 'lumirss',
        view: 'unread',
        categoryKey: 'all',
        createdAt: '2026-09-01T00:00:00Z',
        updatedAt: '2026-09-01T00:00:00Z',
      },
    ],
  }
}

/** 与 useSearch 实际缓存同构的分页搜索页（含双路游标与库腿字段）。 */
function searchPage(read = false) {
  return {
    items: [{ ...item(1, read), snippet: '片段' }, { ...item(2, read), snippet: '片段' }],
    nextCursor: 'rss-cursor-2',
    hasMore: true,
    library: [],
    libraryNextCursor: 'lib-cursor-2',
    libraryHasMore: true,
    elapsedMs: 1,
  }
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

describe('搜索缓存 key 分层 — 状态写入不撞保存视图缓存', () => {
  it('分页搜索 + 保存视图并存时 mutation 成功，视图缓存原样、结果缓存被补丁', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(patchResponse()))
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()

    // 预置：真实形状的保存视图缓存 + 两页分页搜索缓存。
    const key = resultsKey({ q: 'lumirss', state: null, favorite: null })
    const views = savedViews()
    client.setQueryData(['search', 'saved-views'], views)
    client.setQueryData(key, {
      pages: [searchPage(false), { ...searchPage(true), nextCursor: null, hasMore: false }],
      pageParams: [
        { cursor: null, libraryCursor: null },
        { cursor: 'rss-cursor-2', libraryCursor: null },
      ],
    })

    const { result } = renderHook(() => useEntryStateMutation(), { wrapper: Wrapper })
    await act(async () => {
      result.current.mutate({ entryRef: 'e1.scope', patch: { read: true } })
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    // 保存视图缓存必须原样保留（修复前这里被 pages.map 炸掉）。
    expect(client.getQueryData(['search', 'saved-views'])).toEqual(views)

    // 分页搜索缓存被精确补丁：e1 已读，e2 不动，游标字段保留。
    const patched = client.getQueryData<{ pages: ReturnType<typeof searchPage>[] }>(key)
    expect(patched?.pages[0]?.items.find((i) => i.entryRef === 'e1.scope')?.read).toBe(true)
    expect(patched?.pages[0]?.items.find((i) => i.entryRef === 'e2.scope')?.read).toBe(false)
    expect(patched?.pages[0]?.nextCursor).toBe('rss-cursor-2')
    expect(patched?.pages[0]?.libraryNextCursor).toBe('lib-cursor-2')
    expect(patched?.pages[1]?.nextCursor).toBe(null)

    // 服务端只收到那一次 PATCH。
    expect(fetchMock).toHaveBeenCalledTimes(1)
    client.clear()
  })

  it('unread 过滤的搜索结果：标记已读后条目移除，其余条目与游标保留', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(patchResponse()))
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()

    const key = resultsKey({ q: 'x', state: 'unread', favorite: null })
    client.setQueryData(key, {
      pages: [searchPage(false)],
      pageParams: [{ cursor: null, libraryCursor: null }],
    })
    const views = savedViews()
    client.setQueryData(['search', 'saved-views'], views)

    const { result } = renderHook(() => useEntryStateMutation(), { wrapper: Wrapper })
    await act(async () => {
      result.current.mutate({ entryRef: 'e1.scope', patch: { read: true } })
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const patched = client.getQueryData<{ pages: ReturnType<typeof searchPage>[] }>(key)
    expect(patched?.pages[0]?.items.map((i) => i.entryRef)).toEqual(['e2.scope'])
    expect(patched?.pages[0]?.nextCursor).toBe('rss-cursor-2')
    expect(client.getQueryData(['search', 'saved-views'])).toEqual(views)
    client.clear()
  })

  it('useSearch 实际查询：补丁后 fetchNextPage 仍可续页（游标未被破坏）', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://lumirss.test')
      if (url.pathname.endsWith('/state')) return Promise.resolve(patchResponse())
      const first = url.searchParams.get('cursor') === null
      return Promise.resolve(
        new Response(
          JSON.stringify(
            first
              ? searchPage(false)
              : { ...searchPage(true), nextCursor: null, hasMore: false, libraryNextCursor: null, libraryHasMore: false },
          ),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()
    client.setQueryData(['search', 'saved-views'], savedViews())

    const { result } = renderHook(
      () => useSearch('lumirss', { state: null, favorite: null }),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(result.current.data?.pages.length).toBe(1))

    const state = renderHook(() => useEntryStateMutation(), { wrapper: Wrapper })
    await act(async () => {
      state.result.current.mutate({ entryRef: 'e1.scope', patch: { read: true } })
    })
    await waitFor(() => expect(state.result.current.isSuccess).toBe(true))

    await act(async () => {
      await result.current.fetchNextPage()
    })
    // observer 通知经 notifyManager 异步 flush，与 dual-cursor 回归同法等待。
    await waitFor(() => expect(result.current.data?.pages.length).toBe(2))
    // 补丁写入的已读状态在续页后仍保留（第 1 页 e1 = true）。
    expect(result.current.data?.pages[0]?.items.find((i) => i.entryRef === 'e1.scope')?.read).toBe(true)
    expect(client.getQueryData(['search', 'saved-views'])).toEqual(savedViews())
    client.clear()
  })
})
