/** FIX-154 — 删除库内容后，客户端搜索缓存必须失效（WEB 腿）。
 *
 * 背景：服务端失效是直读（FIX-320 BASELINE_OK，BFF 每次搜索现算），
 * 不推送任何失效事件——因此「删除后搜索结果仍可点开已删内容」的
 * 唯一来源是 WEB 的 TanStack Query 缓存。删除书签/剪藏/快照的
 * mutation 此前只失效各自列表缓存（['library','bookmarks'] 等），
 * 从不触碰 ['search','results']：已删除内容继续出现在缓存搜索结果里，
 * 点击后 resolve 才发现 stale/404。
 *
 * 契约：删除（及回收站恢复/永久删除——两者同样改变索引成员资格）
 * 成功后，搜索结果查询必须重新拉取，缓存不再供应已删条目。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  useDeleteBookmarkMutation,
  useDeleteClipMutation,
  useDeleteSnapshotMutation,
  useSearch,
} from '../api/queries'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function searchPayload() {
  return {
    items: [
      {
        entryRef: 's1',
        title: '被删条目',
        feedTitle: '源',
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

function mockApi() {
  const searchCalls: string[] = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.startsWith('/api/v1/search?')) {
      searchCalls.push(url)
      return Promise.resolve(jsonResponse(searchPayload()))
    }
    if (/\/api\/v1\/library\/(bookmarks|clips|snapshots)\//.test(url) && method === 'DELETE') {
      return Promise.resolve(new Response(null, { status: 204 }))
    }
    return Promise.resolve(jsonResponse({}))
  })
  return { fetchMock, searchCalls }
}

/** 测试挂载件：跑一个搜索查询 + 三个删除按钮（各自挂一个 mutation）。 */
function Harness() {
  const search = useSearch('被删', {})
  const deleteBookmark = useDeleteBookmarkMutation()
  const deleteClip = useDeleteClipMutation()
  const deleteSnapshot = useDeleteSnapshotMutation()
  return (
    <div>
      <p aria-label="结果数">{search.data?.pages[0]?.items.length ?? 0}</p>
      <button type="button" onClick={() => deleteBookmark.mutate('library:b1')}>删书签</button>
      <button type="button" onClick={() => deleteClip.mutate('library:c1')}>删剪藏</button>
      <button type="button" onClick={() => deleteSnapshot.mutate('snap-1')}>删快照</button>
    </div>
  )
}

function renderHarness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-154 — 删除库内容后搜索缓存失效', () => {
  it.each([
    ['删书签', 'library/bookmarks/b1'],
    ['删剪藏', 'library/clips/c1'],
    ['删快照', 'library/snapshots/snap-1'],
  ])('%s 成功后 → 搜索结果重新拉取（不再供应已删条目）', async (buttonLabel, deletedPath) => {
    const { fetchMock, searchCalls } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    renderHarness()

    // 搜索就位：1 次结果请求
    await waitFor(() => expect(searchCalls.length).toBe(1))

    // 删除 → DELETE 到位
    fireEvent.click(screen.getByRole('button', { name: buttonLabel }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u, init]) =>
        String(u).includes(deletedPath) && (init?.method ?? 'GET') === 'DELETE')).toBe(true)
    })

    // 搜索缓存已失效 → 结果查询重新发请求
    await waitFor(() => expect(searchCalls.length).toBeGreaterThanOrEqual(2))
  })
})
