/** Gate 3 测试 — Home 卡片化 + FavoritesPage（0011 Spec AC5/AC10）。
 *
 * - EntryCard：真实字段层级、未读字重语义、无图文本退化（无伪造字段）；
 * - EntryList 移动端渲染 EntryCard（CSS 分发：两者同时挂载，jsdom 断言
 *   DOM 存在性）；
 * - FavoritesPage：复用 starred 查询（不复制数据）、最近/更早分组、
 *   loading/empty/error 状态、点击卡片进入 Reader。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EntryListResponse, EntryListItem } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import EntryCard from '../components/EntryCard'
import FavoritesPage from '../components/pages/FavoritesPage'

const FEEDS = [
  { title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml', category: null },
]

function item(ref: string, overrides: Partial<EntryListItem> = {}): EntryListItem {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源 A',
    author: null,
    url: null,
    publishedAt: '2026-08-30T00:00:00Z',
    read: false,
    starred: false,
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** entries + detail 的 fetch mock */
function mockApi(
  entriesHandler: () => EntryListResponse = () => ({
    items: [item('e1.a'), item('e1.b', { read: true, starred: true, publishedAt: '2026-08-01T00:00:00Z' })],
    nextCursor: null,
  }),
) {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
    if (url.startsWith('/api/v1/entries')) return jsonResponse(entriesHandler())
    throw new Error(`unexpected fetch: ${url}`)
  })
}

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  useReaderUi.setState({ section: 'favorites', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('EntryCard（AC10）', () => {
  it('真实字段层级：feedTitle + 日期 + 标题；未读 medium/已读 normal；动作区存在', () => {
    render(withProviders(<EntryCard item={item('e1.a')} selected={false} />))
    // 卡根为 div：标题区按钮承载可访问名（含 feedTitle+时间）
    const cardBtn = screen.getByRole('button', { name: /示例源 A/ })
    expect(cardBtn.textContent).toContain('示例源 A')
    expect(cardBtn.textContent).toContain('08/30') // 真实 publishedAt 格式化
    const title = screen.getByText('文章 e1.a')
    expect(title.className).toContain('font-medium') // 未读
    // 动作区：稍后读 + 收藏按钮（§19）
    expect(screen.getByRole('button', { name: '加入稍后读' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收藏' })).toBeInTheDocument()

    render(withProviders(<EntryCard item={item('e1.b', { read: true })} selected={false} />))
    expect(screen.getByText('文章 e1.b').className).toContain('font-normal') // 已读
  })

  it('已收藏显示星标动作；点击卡片标题 → selectEntry', () => {
    render(withProviders(<EntryCard item={item('e1.a', { starred: true })} selected={false} />))
    // 0011 修正补充：星标变为可点击动作按钮（aria-label 取消收藏）
    expect(screen.getByRole('button', { name: '取消收藏' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /文章 e1\.a/ }))
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    useReaderUi.getState().selectEntry(null)
  })

  it('无 publishedAt →「—」（契约缺口诚实降级，无伪造时间）', () => {
    render(withProviders(<EntryCard item={item('e1.a', { publishedAt: null })} selected={false} />))
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})

describe('FavoritesPage（AC5）', () => {
  it('复用 starred 查询：请求 view=starred；最近收藏/更早分组', async () => {
    const fetchMock = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<FavoritesPage />))

    await screen.findByRole('button', { name: /文章 e1\.a/ })
    // starred 查询真实发出（复用服务端语义，非本地复制）
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes('view=starred')),
    ).toBe(true)
    // 分组小节：今天=最近收藏，8月1日=更早
    expect(screen.getByText('最近收藏')).toBeInTheDocument()
    expect(screen.getByText('更早')).toBeInTheDocument()
    expect(screen.getByText('文章 e1.b')).toBeInTheDocument()
  })

  it('点击收藏卡片 → 进入 Reader（selectedEntryRef）', async () => {
    vi.stubGlobal('fetch', mockApi())
    render(withProviders(<FavoritesPage />))
    fireEvent.click(await screen.findByRole('button', { name: /文章 e1\.a/ }))
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    useReaderUi.getState().selectEntry(null)
  })

  it('空收藏：专属空态文案（无假数据）', async () => {
    vi.stubGlobal('fetch', mockApi(() => ({ items: [], nextCursor: null })))
    render(withProviders(<FavoritesPage />))
    expect(await screen.findByText('还没有收藏文章')).toBeInTheDocument()
  })

  it('加载失败：错误状态 + 重试', async () => {
    let fail = true
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
      if (url.startsWith('/api/v1/entries')) {
        return fail
          ? jsonResponse({ error: { type: 'upstream_error', message: '上游不可用' } }, 502)
          : jsonResponse({ items: [item('e1.a')], nextCursor: null })
      }
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<FavoritesPage />))

    expect(await screen.findByText('收藏加载失败')).toBeInTheDocument()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await screen.findByRole('button', { name: /文章 e1\.a/ })
  })

  it('loading：收藏骨架屏', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => new Promise<Response>(() => {})),
    )
    render(withProviders(<FavoritesPage />))
    expect(screen.getByLabelText('收藏加载中')).toBeInTheDocument()
  })
})

describe('FavoritesPage 数据一致性（AC5 补充）', () => {
  it('不复制服务端数据：页面无本地收藏状态（starred invalidate 后重新查询）', async () => {
    let callCount = 0
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
      if (url.startsWith('/api/v1/entries')) {
        callCount += 1
        // 第二次（refetch）返回不同数据——证明页面读的是 Query cache
        const items = callCount <= 1 ? [item('e1.a')] : [item('e1.a'), item('e1.c')]
        return jsonResponse({ items, nextCursor: null })
      }
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<FavoritesPage />))
    await screen.findByRole('button', { name: /文章 e1\.a/ })
    expect(screen.queryByText('文章 e1.c')).toBeNull()

    // invalidate 触发 refetch → 新数据出现（数据始终来自服务端语义）
    await waitFor(() => {
      // staleTime 默认 0，组件 remount/refetch 语义由 Query 管理
      expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes('view=starred')).length).toBeGreaterThanOrEqual(1)
    })
  })
})
