/** FIX-134 — 文章切换后目录/章节锚点/进度属于当前篇，不属于上一篇。
 *
 * Reader 的快速切换路径（B 的 detail 已在 query cache，staleTime 30s 内
 * 命中）不走 pending skeleton：success 分支同步渲染。此时 ArticleContent
 * 若不按 entryRef 重挂载，其 `html` state 仍是上一篇的正文——目录
 * （由 html 派生）、章节锚点与滚动/进度口径都还停留在上一篇，直到异步
 * 管线完成才自愈（滚动恢复甚至不会重跑）。
 *
 * 本测试锁住同步断言：切到 B 的同一次提交内，目录与正文必须已经是
 * B 的（A 的标题立即消失），不允许出现「上一篇」的中间态。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import Reader from '../components/Reader'
import type { EntryDetail } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章甲',
    feedTitle: '示例源',
    author: null,
    url: 'https://example.com/a',
    publishedAt: '2026-08-28T10:00:00Z',
    read: false,
    starred: false,
    contentText: '甲的纯文本正文',
    contentHtml: '<p>甲的富文本正文</p>',
    ...overrides,
  } as unknown as EntryDetail
}

const DETAIL_A = detail({
  entryRef: 'e1.a',
  title: '文章甲',
  contentText: '甲的正文 甲章标题 甲章结尾',
  contentHtml:
    '<h2>甲章标题</h2><p>甲的第一段正文，足够长以产生可滚动的正文高度。</p>' +
    '<h2>甲章结尾</h2><p>甲的第二段正文。</p>',
})

const DETAIL_B = detail({
  entryRef: 'e2.b',
  title: '文章乙',
  contentText: '乙的正文 丙章标题 丙章结尾',
  contentHtml:
    '<h2>丙章标题</h2><p>乙的第一段正文，与甲的标题完全不同。</p>' +
    '<h2>丙章结尾</h2><p>乙的第二段正文。</p>',
})

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('FIX-134 文章切换后目录/正文属于当前篇', () => {
  it('缓存的 B（无 pending 骨架）同步接管：A 的目录标题立即消失', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    // B 的 detail 预置进 cache —— 切换时 useEntryDetail 同步命中
    // （staleTime 30s 内 fresh，不触发骨架屏），这正是快速来回切换的
    // 真实路径。
    queryClient.setQueryData(['entry', 'e2.b'], DETAIL_B)

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/v1/entries/e1.a')) {
          return Promise.resolve(jsonResponse(DETAIL_A))
        }
        return Promise.resolve(jsonResponse({ items: [] }))
      }),
    )

    useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: 'e1.a' })
    render(
      <QueryClientProvider client={queryClient}>
        <Reader />
      </QueryClientProvider>,
    )

    // A 就绪：正文与目录（≥2 个标题才渲染目录面板）都出现。
    expect(await screen.findByText('文章甲', {}, { timeout: 5000 })).toBeInTheDocument()
    await waitFor(
      () => {
        expect(screen.getAllByText('甲章标题').length).toBeGreaterThan(0)
      },
      { timeout: 5000 },
    )

    // 切到 B —— 同步提交，不允许任何「上一篇」中间态进入 DOM。
    act(() => {
      useReaderUi.setState({ selectedEntryRef: 'e2.b' })
    })
    expect(screen.getByText('文章乙')).toBeInTheDocument()
    // 目录/章节锚点必须已经是 B 的：A 的标题不在 DOM 的任何角落。
    expect(screen.queryByText('甲章标题')).toBeNull()
    expect(screen.queryByText('甲章结尾')).toBeNull()
    expect(screen.getAllByText('丙章标题').length).toBeGreaterThan(0)
    expect(screen.getAllByText('丙章结尾').length).toBeGreaterThan(0)

    // 管线稳定后仍然是 B（不允许异步管线的迟到产物把 A 带回来）。
    await waitFor(
      () => {
        expect(screen.queryByText('甲章标题')).toBeNull()
      },
      { timeout: 5000 },
    )
    expect(screen.getAllByText('丙章标题').length).toBeGreaterThan(0)
  })
})
