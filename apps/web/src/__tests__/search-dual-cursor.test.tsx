/** Unified search 双腿分页回归（pool #10/#11）。
 *
 * 1. RSS 腿与库腿 cursor 独立推进：两腿都有 next 时都透传；一腿耗尽
 *    后传 null（服务端据此跳过该腿），双耗尽时停止翻页。
 * 2. 库腿命中跨页按 ref 去重（兼容旧服务端每页重发同一切片的行为）。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { useSearch } from '../api/queries'
import { mergeUnique } from '../lib/merge-unique'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
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

describe('useSearch 双腿独立 keyset', () => {
  it('两腿都未耗尽时双 cursor 同时推进；耗尽腿传 null；双耗尽停止', async () => {
    const requests: string[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://lumirss.test')
      requests.push(url.search)
      const rssPage = url.searchParams.get('cursor')
      const libPage = url.searchParams.get('libraryCursor')
      return Promise.resolve(
        jsonResponse({
          items: rssPage === null ? [{ entryRef: 'rss.first' }] : [],
          nextCursor: rssPage === null ? 'rss-2' : null,
          hasMore: rssPage === null,
          elapsedMs: 1,
          index: { entryCount: 1, lastSyncedAt: null },
          library:
            libPage === null
              ? [{ ref: 'clip:1', kind: 'clip', title: 'clip one' }]
              : [],
          libraryHasMore: libPage === null,
          libraryNextCursor: libPage === null ? 'lib-2' : null,
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()
    const { result } = renderHook(() => useSearch('词', {}), {
      wrapper: Wrapper,
    })

    await waitFor(() => expect(result.current.data?.pages.length).toBe(1))
    await act(async () => {
      await result.current.fetchNextPage()
    })
    await waitFor(() =>
      expect(result.current.data?.pages.length).toBe(2),
    )

    // 第一页：无 cursor；第二页：双腿各带下一游标。
    expect(requests[0]).not.toContain('cursor=')
    expect(requests[1]).toContain('cursor=rss-2')
    expect(requests[1]).toContain('libraryCursor=lib-2')

    // 第二页后 RSS 腿耗尽（hasMore=false）：第三页 cursor=null、
    // libraryCursor=null → 双腿都完，hasNextPage=false。
    expect(result.current.hasNextPage).toBe(false)
    client.clear()
  })

  it('只有库腿继续时：cursor 省略 + libraryCursor 推进；旧服务端重发切片被 mergeUnique 去重', async () => {
    const requests: string[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://lumirss.test')
      requests.push(url.search)
      const libPage = url.searchParams.get('libraryCursor')
      // 第二页重发 clip:1（模拟旧服务端固定切片行为）+ 新增 clip:2。
      const hits =
        libPage === null
          ? [{ ref: 'clip:1', kind: 'clip', title: 'clip one' }]
          : [
              { ref: 'clip:1', kind: 'clip', title: 'clip one' },
              { ref: 'clip:2', kind: 'clip', title: 'clip two' },
            ]
      return Promise.resolve(
        jsonResponse({
          items: [],
          nextCursor: null,
          hasMore: false,
          elapsedMs: 1,
          index: { entryCount: 0, lastSyncedAt: null },
          library: hits,
          libraryHasMore: libPage === null,
          libraryNextCursor: libPage === null ? 'lib-2' : null,
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()
    const { result } = renderHook(() => useSearch('词', {}), {
      wrapper: Wrapper,
    })

    await waitFor(() => expect(result.current.data?.pages.length).toBe(1))
    await act(async () => {
      await result.current.fetchNextPage()
    })
    await waitFor(() => expect(result.current.data?.pages.length).toBe(2))
    // RSS 腿耗尽：cursor 参数整个省略（不传 null 字符串）。
    expect(requests[1]).not.toMatch(/[?&]cursor=/)
    expect(requests[1]).toContain('libraryCursor=lib-2')
    // 跨页合并的原始序列含重复 → SearchPage 用 mergeUnique 去重后
    // 用户只看到 clip:1、clip:2 各一张卡。
    const raw = result.current.data!.pages.flatMap((p) => p.library ?? [])
    expect(raw.map((h) => h.ref)).toEqual(['clip:1', 'clip:1', 'clip:2'])
    expect(
      mergeUnique(raw, (h) => h.ref).map((h) => h.ref),
    ).toEqual(['clip:1', 'clip:2'])
    client.clear()
  })
})
