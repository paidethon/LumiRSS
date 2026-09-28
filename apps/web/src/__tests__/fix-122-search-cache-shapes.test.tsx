/** FIX-122 — 搜索缓存形状分层（InfiniteData vs 普通 list）回归验证。
 *
 * 历史事故（P0 2026-09-18）：保存视图清单曾与搜索结果共用 ['search']
 * 裸前缀；useEntryStateMutation 按前缀枚举缓存时把普通 list 误当
 * InfiniteData 调 data.pages.map →「n.pages.map is not a function」，
 * 服务端已 204 前端仍误报「状态更新失败」。
 *
 * 基线现状（BASELINE_OK 验证）：queries.ts 以 SEARCH_RESULTS_KEY =
 * ['search','results'] / SAVED_VIEWS_KEY = ['search','saved-views']
 * 分层，状态写入只枚举 results 子空间。本文件以真实形状双重验证：
 *  1) results 子空间（InfiniteData.pages）按过滤语义精确补丁；
 *  2) 同前缀下的普通 list（保存视图清单，SavedSearchList 形状）绝不被
 *     当页结构展开——原样保留、onSuccess 不抛错。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SEARCH_RESULTS_KEY, useEntryStateMutation } from '../api/queries'
import type { EntryListItem } from '../api/types'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    setEntryState: vi.fn().mockResolvedValue(undefined),
  }
})

function entryItem(ref: string): EntryListItem {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: '2026-09-01T00:00:00Z',
    read: false,
    starred: false,
  }
}

/** 保存视图清单真实形状（SavedSearchList：普通 list，无 pages）。 */
const SAVED_VIEWS_SEED = {
  items: [
    {
      id: 'v1',
      name: '未读 · 技术分类',
      query: '示例',
      view: 'unread',
      categoryKey: 'tech',
      contentTypes: null,
      workspaceId: null,
      filters: null,
      pinned: false,
      pinOrder: null,
      hasFeedToken: false,
      createdAt: '2026-09-01T00:00:00Z',
    },
  ],
}

let queryClient: QueryClient

beforeEach(() => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
})

afterEach(() => {
  queryClient.clear()
})

let settle: () => void
let failed: (error: unknown) => void
function Harness() {
  const mutation = useEntryStateMutation()
  return (
    <button
      type="button"
      onClick={() => {
        mutation.mutateAsync({ entryRef: 'e1', patch: { read: true } }).then(
          () => settle(),
          (error: unknown) => failed(error),
        )
      }}
    >
      mark-read
    </button>
  )
}

function renderHarness() {
  render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  )
  return document.querySelector<HTMLButtonElement>('button[type="button"]')!
}

/** 成功路径不抛错（含 onSuccess 缓存补丁全程）。 */
async function expectSuccess() {
  let settled = false
  let rejection: unknown
  settle = () => { settled = true }
  failed = (error) => { rejection = error }
  fireEvent.click(renderHarness())
  await waitFor(() => expect(settled || rejection !== undefined).toBe(true))
  expect(rejection).toBeUndefined()
}

describe('FIX-122 搜索缓存形状分层（真实形状）', () => {
  it('results 子空间（InfiniteData）按 unread 语义移除已读项；onSuccess 不抛错', async () => {
    const filtersKey = { q: '示例', state: 'unread' as const, favorite: null }
    queryClient.setQueryData([...SEARCH_RESULTS_KEY, filtersKey], {
      pages: [{ items: [entryItem('e1')], nextCursor: null, hasMore: false }],
      pageParams: [null],
    })

    await expectSuccess()

    const patched = queryClient.getQueryData<{
      pages: { items: EntryListItem[] }[]
    }>([...SEARCH_RESULTS_KEY, filtersKey])
    expect(patched?.pages[0]?.items.map((i) => i.entryRef)).toEqual([])
  })

  it('同前缀普通 list（保存视图清单）不被误当 InfiniteData：原样保留、零异常', async () => {
    queryClient.setQueryData(['search', 'saved-views'], SAVED_VIEWS_SEED)

    // 修复前：onSuccess 对普通 list 调 data.pages.map 抛
    // 「n.pages.map is not a function」→ mutateAsync reject、UI 误报
    // 「状态更新失败」。基线约定：成功路径零异常，普通 list 原样保留。
    await expectSuccess()
    expect(queryClient.getQueryData(['search', 'saved-views'])).toEqual(SAVED_VIEWS_SEED)
  })
})
