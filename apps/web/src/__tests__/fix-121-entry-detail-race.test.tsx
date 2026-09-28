/** FIX-121 回归 — 快速连续选文章时，旧（A）的 Detail 请求不得覆盖
 * 新选中项（B）的视图。
 *
 * 不变量（架构 §2：Detail 请求按 entryRef 分桶 + 过期即取消）：
 * - 切换选择 = 换 query key（['entry', entryRef]）：B 的视图只从
 *   ['entry','e1.B'] 渲染；
 * - A 失去唯一观察者时其在途请求被取消并回滚（TanStack Query v5
 *   removeObserver → retryer.cancel({revert:true})）：A 的迟到响应
 *   不会写缓存，更不会成为 B 的渲染数据；
 * - 回切 A 时重新请求并显示 A 自己的数据（桶不串）。
 *
 * 判定基准：行为由 useEntryDetail 的 key 化缓存 + 取消语义保证——
 * 本文件是「已正确 → 验证性测试」基线（BASELINE_OK）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Reader from '../components/Reader'
import type { EntryDetail } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

function detail(overrides: Partial<EntryDetail> & { entryRef: string; title: string }): EntryDetail {
  return {
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: '2026-08-28T10:00:00Z',
    read: false,
    starred: false,
    contentText: '纯文本正文',
    contentHtml: '<p>富文本正文</p>',
    ...overrides,
  }
}

const DETAIL_A = detail({ entryRef: 'e1.A', title: '文章甲（慢响应）' })
const DETAIL_B = detail({ entryRef: 'e1.B', title: '文章乙（快响应）' })

/** 可控 deferred：A 的响应在测试里手动迟到。 */
function createDeferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
}

class MockIO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', MockIO as unknown as typeof IntersectionObserver)
  useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

function renderReader() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <Reader />
      </QueryClientProvider>,
    ),
  }
}

describe('FIX-121 — 快速连选时 Detail 旧请求不覆盖新选中项', () => {
  it('选 A 后立刻选 B：A 请求被取消/迟到响应不落视图，B 正常显示；回切 A 重新请求并显示 A', async () => {
    const deferredA = createDeferred<EntryDetail>()
    let aCalls = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      // Detail：A 第一次迟到（deferred 手控），回切后每次给全新 Response
      // （Response body 一次性，不能复用同一实例）。
      if (url === '/api/v1/entries/e1.A') {
        aCalls += 1
        return aCalls === 1
          ? deferredA.promise.then(() => jsonResponse(DETAIL_A))
          : Promise.resolve(jsonResponse(DETAIL_A))
      }
      if (url === '/api/v1/entries/e1.B') return Promise.resolve(jsonResponse(DETAIL_B))
      // Reader 周边面板（summary/revisions/relations/…）与本次不变量无关。
      return Promise.resolve(jsonResponse({ items: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)
    const { queryClient } = renderReader()

    expect(screen.getByText('选择一篇文章开始阅读')).toBeInTheDocument()

    // 连续快速选择：A 先选中（请求已发出、未返回），B 紧随其后。
    act(() => {
      useReaderUi.setState({ selectedEntryRef: 'e1.A' })
    })
    act(() => {
      useReaderUi.setState({ selectedEntryRef: 'e1.B' })
    })

    // 竞态场景成立：两个 ref 的请求都已发出。
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      expect(calls).toContain('/api/v1/entries/e1.A')
      expect(calls).toContain('/api/v1/entries/e1.B')
    })

    // B 先就绪 → 视图显示 B。
    expect(await screen.findByText('文章乙（快响应）')).toBeInTheDocument()

    // A 的迟到响应此刻才返回（其在途请求已随失去观察者被取消回滚）。
    await act(async () => {
      deferredA.resolve(DETAIL_A)
      await deferredA.promise
    })

    // 核心不变量：视图仍是 B，A 的数据绝不渲染。
    expect(screen.getByText('文章乙（快响应）')).toBeInTheDocument()
    expect(screen.queryByText('文章甲（慢响应）')).not.toBeInTheDocument()
    // 取消语义：迟到的 A 响应被丢弃，不写入缓存桶。
    expect(queryClient.getQueryData(['entry', 'e1.A'])).toBeUndefined()

    // 回切 A：重新请求（取消过的旧请求不复活为脏数据），显示 A 自己的内容。
    act(() => {
      useReaderUi.setState({ selectedEntryRef: 'e1.A' })
    })
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter((c) => String(c[0]) === '/api/v1/entries/e1.A').length).toBe(2)
    })
    expect(await screen.findByText('文章甲（慢响应）')).toBeInTheDocument()
    expect(screen.queryByText('文章乙（快响应）')).not.toBeInTheDocument()
  })
})
