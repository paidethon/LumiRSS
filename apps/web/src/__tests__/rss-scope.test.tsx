/** RSS Scope 交互测试 — 0011 阻断修复（§6–§9/§46–§48/§51）。
 *
 * - RSS 主区域 → scope=rss（query 含 sourceType=rss，§51）≠ 展开行为；
 * - chevron → 只展开 tree（scope 不变）；
 * - Category 主区域 → scope=rss-category；chevron → 只展开 feeds；
 * - Feed 点击 → scope=rss-feed（feedUrl 服务端过滤）；
 * - 分类合并：真实 category.id 为 key（§45）；
 * - Query key：不同 scope 不同 cache（§19/§48）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import Sidebar, { mergeFeedsByCategory } from '../components/Sidebar'
import type { Feed } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { buildEntryQuery, scopeKey } from '../lib/navigation'

const FEEDS: Feed[] = [
  {
    title: 'Feed A',
    feedUrl: 'https://a.example/feed',
    category: { id: 'user/-/label/技术', label: '技术' },
  },
  {
    title: 'Feed B',
    feedUrl: 'https://b.example/feed',
    category: { id: 'user/-/label/技术', label: '技术' },
  },
  {
    title: 'Feed C',
    feedUrl: 'https://c.example/feed',
    category: { id: 'user/-/label/AI', label: 'AI' },
  },
  { title: 'Feed D', feedUrl: 'https://d.example/feed', category: null },
]

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

function mockApi() {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
    if (url.startsWith('/api/v1/entries'))
      return jsonResponse({ items: [], nextCursor: null })
    throw new Error(`unexpected fetch: ${url}`)
  })
}

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function renderSidebar() {
  return render(withProviders(<Sidebar />))
}

beforeEach(() => {
  useReaderUi.setState({ section: 'home', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null, mobileSidebarOpen: false })
  vi.stubGlobal('fetch', mockApi())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/** 展开 RSS tree + 指定分类（feeds 数据到达后） */
async function expandRssTreeAndCategory(categoryLabel: string) {
  fireEvent.click(screen.getByRole('button', { name: '展开 RSS 分类' }))
  const chevron = await screen.findByRole('button', {
    name: new RegExp(`展开 ${categoryLabel} 的订阅源`),
  })
  fireEvent.click(chevron)
}

describe('§45 分类合并（真实 category.id 为 key）', () => {
  it('同分类 feeds 合并；无分类归入未分组；未分组排最后', () => {
    const nodes = mergeFeedsByCategory(FEEDS)
    const labels = nodes.map((n) => n.label)
    expect(labels.slice().sort()).toEqual(['AI', '技术', '未分组'])
    expect(labels[labels.length - 1]).toBe('未分组') // 排最后
    const tech = nodes.find((n) => n.label === '技术')!
    expect(tech.feeds.map((f) => f.title)).toEqual(['Feed A', 'Feed B'])
    const ungrouped = nodes.find((n) => n.label === '未分组')!
    expect(ungrouped.feeds.map((f) => f.title)).toEqual(['Feed D'])
  })

  it('形状异常的 category 归入未分组（防御，不崩溃）', () => {
    const bad = [{ title: 'X', feedUrl: 'https://x', category: {} }] as unknown as Feed[]
    expect(mergeFeedsByCategory(bad)[0]!.label).toBe('未分组')
  })
})

describe('§46 RSS 交互：主区域=scope，chevron=tree（完全分离）', () => {
  it('RSS 主区域点击 → scope=rss（不改 tree 状态）', async () => {
    renderSidebar()
    const rssMain = await screen.findByRole('button', { name: /RSS 订阅/ })
    fireEvent.click(rssMain)
    expect(useReaderUi.getState().scope).toEqual({ kind: 'rss' })
    // tree 仍收起（chevron aria-expanded 不变）
    expect(screen.getByRole('button', { name: '展开 RSS 分类' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })

  it('RSS chevron 点击 → 只展开 tree（scope 不变）', async () => {
    renderSidebar()
    const chevron = await screen.findByRole('button', { name: '展开 RSS 分类' })
    fireEvent.click(chevron)
    expect(chevron).toHaveAttribute('aria-expanded', 'true')
    expect(useReaderUi.getState().scope).toEqual({ kind: 'all' }) // scope 未被改动
  })

  it('Category 主区域 → scope=rss-category（categoryId 为真实 key）', async () => {
    renderSidebar()
    await expandRssTreeAndCategory('技术')
    // 主区域 accessible name 含分类名 + 计数（如「技术 2」）
    const catMain = screen.getByRole('button', { name: /^技术/ })
    fireEvent.click(catMain)
    expect(useReaderUi.getState().scope).toEqual({
      kind: 'rss-category',
      categoryId: 'user/-/label/技术',
      categoryLabel: '技术',
    })
  })

  it('Category chevron → 只展开 feeds（scope 不变）', async () => {
    renderSidebar()
    const before = useReaderUi.getState().scope
    await expandRssTreeAndCategory('AI')
    expect(screen.getByRole('button', { name: 'Feed C' })).toBeInTheDocument()
    expect(useReaderUi.getState().scope).toEqual(before)
  })

  it('Feed 点击 → scope=rss-feed（feedUrl）', async () => {
    renderSidebar()
    await expandRssTreeAndCategory('技术')
    fireEvent.click(screen.getByRole('button', { name: 'Feed A' }))
    expect(useReaderUi.getState().scope).toEqual({
      kind: 'rss-feed',
      feedUrl: 'https://a.example/feed',
    })
  })

  it('未分组节点主区域不可点击（无服务端分类契约）', async () => {
    renderSidebar()
    await expandRssTreeAndCategory('未分组')
    // 未分组主区域 disabled；feed 行正常可点
    const ungroupedMain = screen.getByRole('button', { name: /^未分组/ })
    expect(ungroupedMain).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Feed D' }))
    expect(useReaderUi.getState().scope).toEqual({
      kind: 'rss-feed',
      feedUrl: 'https://d.example/feed',
    })
  })
})

describe('§51 buildEntryQuery：RSS Scope 明确区别于全部', () => {
  it('all → 无 source 过滤；rss → sourceType=rss（未来 Email 不混入）', () => {
    expect(buildEntryQuery({ kind: 'all' }, 'all')).toEqual({
      view: 'all',
      feedUrl: null,
      sourceType: null,
      categoryId: null,
    })
    expect(buildEntryQuery({ kind: 'rss' }, 'all')).toEqual({
      view: 'all',
      feedUrl: null,
      sourceType: 'rss',
      categoryId: null,
    })
  })

  it('category → sourceType + categoryId；feed → feedUrl', () => {
    expect(
      buildEntryQuery(
        { kind: 'rss-category', categoryId: 'user/-/label/技术', categoryLabel: '技术' },
        'unread',
      ),
    ).toEqual({
      view: 'unread',
      feedUrl: null,
      sourceType: 'rss',
      categoryId: 'user/-/label/技术',
    })
    expect(
      buildEntryQuery({ kind: 'rss-feed', feedUrl: 'https://a' }, 'all'),
    ).toEqual({ view: 'all', feedUrl: 'https://a', sourceType: null, categoryId: null })
  })

  it('query key：不同 scope 必然不同（§19/§48 cache 隔离）', () => {
    const keys = [
      scopeKey({ kind: 'all' }),
      scopeKey({ kind: 'rss' }),
      scopeKey({ kind: 'rss-category', categoryId: 'c1', categoryLabel: 'x' }),
      scopeKey({ kind: 'rss-category', categoryId: 'c2', categoryLabel: 'x' }),
      scopeKey({ kind: 'rss-feed', feedUrl: 'https://a' }),
      scopeKey({ kind: 'rss-feed', feedUrl: 'https://b' }),
    ]
    expect(new Set(keys.map((k) => JSON.stringify(k))).size).toBe(keys.length)
  })
})

describe('§51 端到端：点 RSS 订阅发出带 sourceType=rss 的请求', () => {
  it('App 渲染下点 RSS 主区域 → fetch 含 sourceType=rss', async () => {
    const fetchMock = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <App />
      </QueryClientProvider>,
    )
    const rssMain = await screen.findByRole('button', { name: /RSS 订阅/ })
    fireEvent.click(rssMain)
    await waitFor(() => {
      const rssCall = fetchMock.mock.calls
        .map((c) => String(c[0]))
        .find((u) => u.includes('sourceType=rss'))
      expect(rssCall).toBeDefined()
    })
  })
})
