/** FIX-130 — 文章来源标签：列表行与详情头都能追溯来源。
 *
 * 实现统一在 lib/source-meta（SourceLabel / SourceGlyph / useGoToFeed），
 * EntryRow（列表行）与 ReaderHeader（详情元信息行）共用：
 * - 来源名缺失/空白 → 「来源未知」（绝不渲染 undefined/空串）；
 * - 截断由 truncate 类消费，完整名可经 title 属性获取（悬停可读全名）；
 * - 有 feedUrl 点击 → 进入该订阅范围（section home + scope rss-feed），
 *   不误开文章；无 feedUrl 诚实为纯文本。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EntryRow from '../components/EntryRow'
import Reader from '../components/Reader'
import type { EntryDetail, EntryListItem } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

const FEED_URL = 'https://feed.example.com/long-source.xml'
const FEED_NAME = '一个非常长的来源名称需要截断但完整名必须可获取'

function listItem(overrides: Partial<EntryListItem> = {}): EntryListItem {
  return {
    entryRef: 'e1.a',
    title: '文章标题',
    feedTitle: FEED_NAME,
    feedUrl: FEED_URL,
    author: null,
    url: null,
    publishedAt: '2026-09-18T08:00:00Z',
    read: false,
    starred: false,
    ...overrides,
  } as EntryListItem
}

function withProviders(node: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

function sourceButton(): HTMLElement {
  // 可访问名 = 按钮文本（来源显示名）；title 是全名提示
  return screen.getByRole('button', { name: FEED_NAME })
}

beforeEach(() => {
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, selectedEntryRef: null })
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('FIX-130 列表行（EntryRow）来源可追溯', () => {
  it('来源名完整渲染 + title 属性携带全名（截断由 CSS 消费）', () => {
    render(withProviders(<EntryRow item={listItem()} selected={false} />))
    const button = sourceButton()
    expect(button).toBeInTheDocument()
    expect(button.textContent).toBe(FEED_NAME)
    expect(button.getAttribute('title')).toBe(`只看来自「${FEED_NAME}」的文章`)
    expect(button.className).toContain('truncate')
  })

  it('点击来源 → 进入该订阅范围（home + rss-feed），不打开文章', () => {
    render(withProviders(<EntryRow item={listItem()} selected={false} />))
    fireEvent.click(sourceButton())
    const state = useReaderUi.getState()
    expect(state.section).toBe('home')
    expect(state.scope).toEqual({ kind: 'rss-feed', feedUrl: FEED_URL })
    expect(state.selectedEntryRef).toBeNull()
  })

  it('来源缺失 → 「来源未知」纯文本（非按钮，不伪造入口）', () => {
    // 契约里 feedTitle 是非空 string（BFF Pydantic 保证）；「缺失」在
    // 合同内的形态是空串/空白
    render(
      withProviders(
        <EntryRow item={listItem({ feedTitle: '   ', feedUrl: null })} selected={false} />,
      ),
    )
    expect(screen.getByText('来源未知')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /来源/ })).toBeNull()
  })
})

describe('FIX-130 详情头（ReaderHeader 元信息行）来源可追溯', () => {
  const detail: EntryDetail = {
    entryRef: 'e1.a',
    title: '详情文章',
    feedTitle: FEED_NAME,
    feedUrl: FEED_URL,
    author: null,
    url: 'https://example.com/a',
    publishedAt: '2026-09-18T08:00:00Z',
    read: false,
    starred: false,
    contentText: '纯文本正文',
    contentHtml: '<p>富文本正文</p>',
  } as unknown as EntryDetail

  function stubFetch() {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === `/api/v1/entries/${detail.entryRef}`) {
          return Promise.resolve(
            new Response(JSON.stringify(detail), {
              status: 200,
              headers: { 'content-type': 'application/json' },
            }),
          )
        }
        // 其余面板查询（别名/摘要/AI 状态等）统一空载荷——本套件只关心
        // 元信息行的来源展示与导航。
        return Promise.resolve(
          new Response(JSON.stringify({ items: [] }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        )
      }),
    )
  }

  it('详情头渲染来源 + title 全名；点击进入同一订阅范围', async () => {
    stubFetch()
    render(
      withProviders(<Reader />),
    )
    useReaderUi.setState({ selectedEntryRef: detail.entryRef })
    const button = await screen.findByRole('button', { name: FEED_NAME })
    expect(button.textContent).toBe(FEED_NAME)
    expect(button.getAttribute('title')).toBe(`只看来自「${FEED_NAME}」的文章`)
    fireEvent.click(button)
    await waitFor(() => {
      const state = useReaderUi.getState()
      expect(state.scope).toEqual({ kind: 'rss-feed', feedUrl: FEED_URL })
      expect(state.section).toBe('home')
    })
  })
})
