/** R23 §5 — 快速连续切文竞态回归：旧文章的迟到响应不得覆盖当前正文。
 *
 * EntryList→Reader 数据流审计结论（2026-10，Wave1 R11/R23）：
 * 该竞态由三层既有机制结构性排除——
 * 1. `useEntryDetail` 以 `['entry', entryRef]` 为 key 的 TanStack Query
 *    缓存：迟到的响应只会写回它自己的 key，物理上进不了当前文章的
 *    observer（api/queries.ts useEntryDetail）；
 * 2. Reader 成功分支与 ArticleContent / ReaderHeader / ReaderSummary
 *    全部按 `key=entryRef` 重挂载：旧文章的组件树（含本地异步 state）
 *    随 key 变化整体销毁，pending state 不跨文章泄漏；
 * 3. ArticleContent 的渲染管线 effect 带 `cancelled` 守卫，卸载后的
 *    异步 resolve 被丢弃（ArticleContent.tsx 渲染管线 effect）。
 *
 * 本套件把「旧响应不覆盖当前正文」固化为回归防线：不 mock 内部实现，
 * 从 fetch 层制造「先发慢、后发快」的真实时序，断言正文恒等于当前
 * 选中文章。若未来有人把 detail 写进共享 state / 单例 store，这里的
 * 断言会先红。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Reader from '../components/Reader'
import type { EntryDetail } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

function detailFixture(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: null,
    url: 'https://example.com/a',
    publishedAt: '2026-08-28T10:00:00Z',
    read: false,
    starred: false,
    contentText: '纯文本正文 A',
    contentHtml: '<p>富文本正文 A</p>',
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

type Release = (body: EntryDetail) => void

/** 手动放行的 detail 响应（制造「迟到」时序）。 */
function deferredDetail(): { promise: Promise<Response>; release: Release } {
  let release: Release = () => {}
  const promise = new Promise<Response>((resolve) => {
    release = (body) => resolve(jsonResponse(body))
  })
  return { promise, release }
}

function renderReader(): void {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={qc}>
      <Reader />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('切文竞态回归（R23 §5）：旧响应不覆盖当前正文', () => {
  it('A 慢 B 快：切到 B 后 A 的迟到响应到达，正文仍是 B', async () => {
    const a = deferredDetail()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/entries/e1.a') return a.promise
        if (url === '/api/v1/entries/e1.b') {
          return Promise.resolve(
            jsonResponse(detailFixture({ entryRef: 'e1.b', title: '文章 B', contentText: '纯文本正文 B', contentHtml: '<p>富文本正文 B</p>' })),
          )
        }
        if (url.includes('/api/v1/feeds')) {
          return Promise.resolve(jsonResponse([]))
        }
        return Promise.resolve(jsonResponse({ items: [] }))
      }),
    )

    renderReader()
    // 先选 A（响应挂起 → 骨架），立刻切到 B（快速返回）。
    // timeout 放宽：并行 worker 高负载下首帧渲染可能超过 findBy 默认 1s。
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    expect(await screen.findByLabelText('文章加载中', {}, { timeout: 3000 })).toBeInTheDocument()
    useReaderUi.setState({ selectedEntryRef: 'e1.b' })

    expect(await screen.findByText('文章 B', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(document.querySelector('.article-content')?.textContent).toContain('富文本正文 B')

    // A 的响应此刻才迟到：只落 A 自己的缓存（['entry','e1.a']），
    // 当前正文必须仍是 B
    a.release(detailFixture())
    await waitFor(() => {
      // 微任务排空：给任何潜在的「迟到写入」留出失败机会
      expect(screen.getByText('文章 B')).toBeInTheDocument()
    })
    expect(screen.queryByText('文章 A')).toBeNull()
    expect(document.querySelector('.article-content')?.textContent).toContain('富文本正文 B')
    expect(document.querySelector('.article-content')?.textContent).not.toContain('富文本正文 A')
  })

  it('B 慢 A 快（反向同构）：迟到的 B 不得把正文拉回 B', async () => {
    const b = deferredDetail()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/entries/e1.a') {
          return Promise.resolve(jsonResponse(detailFixture()))
        }
        if (url === '/api/v1/entries/e1.b') return b.promise
        if (url.includes('/api/v1/feeds')) {
          return Promise.resolve(jsonResponse([]))
        }
        return Promise.resolve(jsonResponse({ items: [] }))
      }),
    )

    renderReader()
    useReaderUi.setState({ selectedEntryRef: 'e1.b' })
    expect(await screen.findByLabelText('文章加载中', {}, { timeout: 3000 })).toBeInTheDocument()
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })

    expect(await screen.findByText('文章 A', {}, { timeout: 3000 })).toBeInTheDocument()

    b.release(detailFixture({ entryRef: 'e1.b', title: '文章 B' }))
    await waitFor(() => {
      expect(screen.getByText('文章 A')).toBeInTheDocument()
    })
    expect(screen.queryByText('文章 B')).toBeNull()
    expect(document.querySelector('.article-content')?.textContent).toContain('富文本正文 A')
  })

  it('来回切回已缓存文章：正文立即可用（缓存命中，不白屏）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/entries/e1.a') {
          return Promise.resolve(jsonResponse(detailFixture()))
        }
        if (url === '/api/v1/entries/e1.b') {
          return Promise.resolve(
            jsonResponse(detailFixture({ entryRef: 'e1.b', title: '文章 B', contentText: '纯文本正文 B', contentHtml: '<p>富文本正文 B</p>' })),
          )
        }
        if (url.includes('/api/v1/feeds')) {
          return Promise.resolve(jsonResponse([]))
        }
        return Promise.resolve(jsonResponse({ items: [] }))
      }),
    )

    renderReader()
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    expect(await screen.findByText('文章 A')).toBeInTheDocument()

    useReaderUi.setState({ selectedEntryRef: 'e1.b' })
    expect(await screen.findByText('文章 B')).toBeInTheDocument()

    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    expect(await screen.findByText('文章 A')).toBeInTheDocument()
    expect(document.querySelector('.article-content')?.textContent).toContain('富文本正文 A')
  })
})
