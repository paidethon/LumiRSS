/** FIX-125 回归 — 已读/未读/收藏状态在列表、详情与侧栏计数之间一致。
 *
 * 既有契约（query-memory.test 已覆盖，本文件复验并扩展）：
 * useEntryStateMutation.onSuccess 用同一次写入补丁三处缓存——
 *   detail（['entry', ref]）原地翻转；
 *   列表（['entries', …]）按 view 翻转/移除；
 *   搜索（['search','results', …]）同语义。
 *
 * 缺陷（本文件新增覆盖）：侧栏服务端派生计数（['pinned-view-count']，
 * 固定视图徽标）不随状态写入失效——标记已读/收藏后列表行即时变化，
 * 侧栏徽标仍是旧值，直到窗口重新聚焦才被 refetch 修正（漂移）。
 *
 * 修复契约：状态写入成功 → 派生计数缓存统一失效（与服务端同源刷新），
 * 三类视图不再各自为政。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useEntryStateMutation } from '../api/queries'
import type { EntryListItem } from '../api/types'

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

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const Wrapper = ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client }, children)
  return { client, Wrapper }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-125 — 一次写入，列表/详情/计数同源', () => {
  it('列表标记已读 → detail 翻转 + unread 行移除 + 侧栏计数缓存失效', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()

    client.setQueryData(['entries', { view: 'all', scope: { kind: 'all' } }], {
      pages: [{ items: [item('e1'), item('e2')], nextCursor: null }],
      pageParams: [null],
    })
    client.setQueryData(['entries', { view: 'unread', scope: { kind: 'all' } }], {
      pages: [{ items: [item('e1')], nextCursor: null }],
      pageParams: [null],
    })
    client.setQueryData(['entry', 'e1'], { ...item('e1'), contentText: '正文', contentHtml: null })
    client.setQueryData(['pinned-view-count', 'v-unread'], { count: 3, error: null })

    const { result } = renderHook(() => useEntryStateMutation(), { wrapper: Wrapper })
    await act(async () => {
      result.current.mutate({ entryRef: 'e1', patch: { read: true } })
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    // detail：原地翻转（正文不动）。
    const detail = client.getQueryData<EntryListItem & { contentText?: string }>(['entry', 'e1'])
    expect(detail?.read).toBe(true)
    expect(detail?.contentText).toBe('正文')

    // 列表：all 翻转、unread 移除。
    const all = client.getQueryData<{ pages: { items: EntryListItem[] }[] }>([
      'entries',
      { view: 'all', scope: { kind: 'all' } },
    ])
    expect(all?.pages[0]?.items.find((i) => i.entryRef === 'e1')?.read).toBe(true)
    const unread = client.getQueryData<{ pages: { items: EntryListItem[] }[] }>([
      'entries',
      { view: 'unread', scope: { kind: 'all' } },
    ])
    expect(unread?.pages[0]?.items.map((i) => i.entryRef)).not.toContain('e1')

    // 侧栏派生计数：同一次写入统一失效（下一次挂载/聚焦从服务端刷新）。
    expect(client.getQueryState(['pinned-view-count', 'v-unread'])?.isInvalidated).toBe(true)
    // 唯一网络调用是那次 PATCH（计数无挂载观察者，不产生额外 GET）。
    expect(fetchMock).toHaveBeenCalledTimes(1)
    client.clear()
  })

  it('详情侧加收藏 → 列表行 starred 同步翻转 + 计数缓存失效', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
    vi.stubGlobal('fetch', fetchMock)
    const { client, Wrapper } = wrapper()

    client.setQueryData(['entries', { view: 'all', scope: { kind: 'all' } }], {
      pages: [{ items: [item('e2')], nextCursor: null }],
      pageParams: [null],
    })
    client.setQueryData(['entry', 'e2'], { ...item('e2'), contentText: '正文', contentHtml: null })
    client.setQueryData(['pinned-view-count', 'v-fav'], { count: 1, error: null })

    const { result } = renderHook(() => useEntryStateMutation(), { wrapper: Wrapper })
    await act(async () => {
      result.current.mutate({ entryRef: 'e2', patch: { starred: true } })
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const detail = client.getQueryData<EntryListItem>(['entry', 'e2'])
    expect(detail?.starred).toBe(true)
    const all = client.getQueryData<{ pages: { items: EntryListItem[] }[] }>([
      'entries',
      { view: 'all', scope: { kind: 'all' } },
    ])
    expect(all?.pages[0]?.items.find((i) => i.entryRef === 'e2')?.starred).toBe(true)
    expect(client.getQueryState(['pinned-view-count', 'v-fav'])?.isInvalidated).toBe(true)
    client.clear()
  })
})
