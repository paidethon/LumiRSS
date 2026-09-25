/** N141/N144/N149 — SearchPage 接线（黑盒 fetch stub）。
 *
 * - N141 搜索快照：保存快照 → POST /search/snapshots（同参）；面板列出
 *   快照（引用计数）；比较 → POST compare → 差分 counts 渲染；
 * - N144 按检索范围收藏：保存对话框暴露 工作区/内容类型 → POST body
 *   携带 scope；重新打开 → 范围还原（chips + 内容类型过滤库腿）；
 *   scopeBroken → 「范围已失效」横幅 + 解除关联 POST；
 * - N149 主题演变：时间线同参 GET；月份柱状 + 批注卡片渲染；
 *   隐藏批注 → localStorage 排除 + 卡片消失 + refetch。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SearchPage from '../components/pages/SearchPage'
import { useSearchState } from '../store/search-state'
import { useReaderUi } from '../store/reader-ui'
import { useSearchBasket } from '../store/search-basket'
import type { SearchResponse } from '../api/types'

function searchResponse(items: Partial<SearchResponse['items'][number]>[] = [], library: Partial<NonNullable<SearchResponse['library']>[number]>[] = []): SearchResponse {
  return {
    items: items.map((item) => ({
      entryRef: 'e1',
      title: '默认标题',
      feedTitle: '源A',
      feedUrl: 'https://a.example/rss',
      matchedFields: ['title'],
      publishedAt: '2026-09-23T08:00:00Z',
      read: false,
      snippet: '',
      starred: false,
      ...item,
    })),
    nextCursor: null,
    hasMore: false,
    elapsedMs: 1,
    index: { entryCount: 1, lastSyncedAt: null, partial: false },
    library: library.map((item) => ({
      ref: 'l1',
      kind: 'bookmark',
      title: '库条目',
      url: null,
      snippet: '',
      updatedAt: '2026-09-23T08:00:00Z',
      ...item,
    })) as SearchResponse['library'],
    libraryHasMore: false,
    libraryNextCursor: null,
    libraryError: null,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function withProviders(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

async function submitQuery(query: string) {
  const input = screen.getByLabelText('搜索')
  fireEvent.change(input, { target: { value: query } })
  fireEvent.keyDown(input, { key: 'Enter' })
  await waitFor(() => expect(useSearchState.getState().submitted).toBe(query))
}

interface RecordedRequest {
  url: string
  method: string
  body: unknown
}

function stubFetch(routes: { prefix: string; respond: (req: RecordedRequest) => Response }[]) {
  const requests: RecordedRequest[] = []
  const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const request: RecordedRequest = {
      url,
      method: (init?.method ?? 'GET').toUpperCase(),
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : null,
    }
    requests.push(request)
    for (const route of routes) {
      if (url.startsWith(route.prefix)) {
        return Promise.resolve(route.respond(request))
      }
    }
    return Promise.resolve(jsonResponse({}))
  })
  vi.stubGlobal('fetch', mock)
  return requests
}

/** 顺序敏感：特殊前缀（scope/unlink、views/{id}/…）必须排在
 * '/api/v1/search/views' 之前。 */
const baseRoutes = (): { prefix: string; respond: (req: RecordedRequest) => Response }[] => [
  { prefix: '/api/v1/search/views', respond: () => jsonResponse({ items: [] }) },
  { prefix: '/api/v1/workspaces', respond: () => jsonResponse({ items: [] }) },
  { prefix: '/api/v1/feeds', respond: () => jsonResponse([]) },
  { prefix: '/api/v1/subscriptions', respond: () => jsonResponse([]) },
]

afterEach(() => {
  useSearchState.getState().clear()
  useReaderUi.setState({ selectedEntryRef: null })
  useSearchBasket.getState().reset()
  localStorage.clear()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

// ---- N141 搜索快照比较 -------------------------------------------------------

describe('N141 搜索快照（SearchPage）', () => {
  it('保存快照 → POST 同参快照；面板列出快照并可比较差分', async () => {
    const snapshot = {
      id: 'snap-1',
      query: 'rust',
      filters: {},
      refCount: 3,
      truncated: false,
      createdAt: '2026-09-23T08:00:00Z',
    }
    const requests = stubFetch([
      {
        prefix: '/api/v1/search/snapshots/snap-1/compare',
        respond: () =>
          jsonResponse({
            added: ['e-new'],
            removed: [],
            rankChanges: [],
            permissionLost: [],
            counts: {
              snapshot: 3,
              current: 4,
              added: 1,
              removed: 0,
              rankChanges: 0,
              permissionLost: 0,
            },
            complete: true,
          }),
      },
      {
        prefix: '/api/v1/search/snapshots',
        respond: (req) => {
          if (req.method === 'GET') return jsonResponse({ items: [snapshot] })
          return jsonResponse(snapshot, 201)
        },
      },
      ...baseRoutes(),
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse([{ entryRef: 'e1', title: 'Rust 发布' }])) },
    ])

    render(withProviders(<SearchPage />))
    await submitQuery('rust')
    await waitFor(() =>
      expect(requests.some((r) => r.url.startsWith('/api/v1/search?'))).toBe(true),
    )

    fireEvent.click(screen.getByTestId('snapshot-save'))
    await waitFor(() => {
      const post = requests.find(
        (r) => r.method === 'POST' && r.url === '/api/v1/search/snapshots',
      )
      expect(post).toBeDefined()
      expect((post?.body as { q: string }).q).toBe('rust')
    })

    // 面板自动打开并列出快照（引用计数而非清单）。
    expect(await screen.findByTestId('snapshot-panel')).toBeInTheDocument()
    expect(await screen.findByTestId('snapshot-row')).toBeInTheDocument()
    expect(screen.getByText(/3 条/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '比较快照「rust」' }))
    await waitFor(() => expect(screen.getByTestId('snapshot-compare')).toBeInTheDocument())
    expect(screen.getByText(/新增 1/)).toBeInTheDocument()
    const comparePost = requests.find((r) =>
      r.url.startsWith('/api/v1/search/snapshots/snap-1/compare'),
    )
    expect(comparePost?.method).toBe('POST')
  })

  it('快照面板：无快照 → 诚实空态', async () => {
    stubFetch([
      { prefix: '/api/v1/search/snapshots', respond: () => jsonResponse({ items: [] }) },
      ...baseRoutes(),
    ])
    render(withProviders(<SearchPage />))
    fireEvent.click(screen.getByTestId('snapshot-toggle'))
    expect(await screen.findByTestId('snapshot-panel')).toBeInTheDocument()
    expect(await screen.findByText(/还没有快照/)).toBeInTheDocument()
  })
})

// ---- N144 按检索范围收藏 -----------------------------------------------------

const SCOPED_VIEW = {
  id: 'view-scope',
  name: '范围视图',
  query: 'rust',
  view: 'all',
  categoryKey: '',
  workspaceId: 'ws-1',
  contentTypes: ['bookmark'],
  scopeBroken: false,
  createdAt: '2026-09-23T08:00:00Z',
  updatedAt: '2026-09-23T08:00:00Z',
}

describe('N144 按检索范围收藏（SearchPage）', () => {
  it('保存对话框暴露工作区/内容类型 → POST body 携带范围', async () => {
    const requests = stubFetch([
      {
        prefix: '/api/v1/workspaces',
        respond: () =>
          jsonResponse({
            items: [{ id: 'ws-1', name: '深度阅读', archived: false }],
          }),
      },
      {
        prefix: '/api/v1/search/views',
        respond: (req) =>
          req.method === 'POST' ? jsonResponse(SCOPED_VIEW, 201) : jsonResponse({ items: [] }),
      },
      { prefix: '/api/v1/feeds', respond: () => jsonResponse([]) },
      { prefix: '/api/v1/subscriptions', respond: () => jsonResponse([]) },
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse()) },
    ])

    render(withProviders(<SearchPage />))
    await submitQuery('rust')

    fireEvent.click(screen.getByTestId('save-view-open'))
    const workspaceSelect = await screen.findByLabelText('工作区范围')
    fireEvent.change(workspaceSelect, { target: { value: 'ws-1' } })
    fireEvent.click(screen.getByRole('checkbox', { name: '书签' }))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      const post = requests.find(
        (r) => r.method === 'POST' && r.url === '/api/v1/search/views',
      )
      expect(post).toBeDefined()
      expect(post?.body).toMatchObject({
        query: 'rust',
        workspaceId: 'ws-1',
        contentTypes: ['bookmark'],
      })
    })
  })

  it('重新打开视图 → 范围还原：内容类型过滤库腿并显示范围 chips', async () => {
    stubFetch([
      {
        prefix: '/api/v1/search/views',
        respond: () => jsonResponse({ items: [SCOPED_VIEW] }),
      },
      { prefix: '/api/v1/workspaces', respond: () => jsonResponse({ items: [{ id: 'ws-1', name: '深度阅读', archived: false }] }) },
      ...baseRoutes().filter((r) => r.prefix !== '/api/v1/workspaces'),
      {
        prefix: '/api/v1/search?',
        respond: () =>
          jsonResponse(
            searchResponse([{ entryRef: 'e1', title: 'Rust 发布' }], [
              { ref: 'lib-bookmark', kind: 'bookmark', title: '书签条目' },
              { ref: 'lib-clip', kind: 'clip', title: '剪藏条目' },
            ]),
          ),
      },
    ])

    render(withProviders(<SearchPage />))
    await submitQuery('rust')
    // 应用视图（点击视图名）。
    await screen.findByText('范围视图')
    fireEvent.click(screen.getByText('范围视图'))

    // 范围 chips 还原 + 内容类型过滤（bookmark 保留、clip 隐藏、RSS 行隐藏）。
    expect(await screen.findByTestId('active-scope')).toBeInTheDocument()
    expect(screen.getByText(/范围：工作区 深度阅读/)).toBeInTheDocument()
    expect(screen.getByText(/范围：内容类型/)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Rust 发布')).toBeNull())
    expect(await screen.findByText('书签条目')).toBeInTheDocument()
    expect(screen.queryByText('剪藏条目')).toBeNull()
    expect(await screen.findByTestId('scope-filter-note')).toBeInTheDocument()
  })

  it('工作区已删除 → 范围已失效横幅 + 解除关联 POST', async () => {
    const broken = { ...SCOPED_VIEW, scopeBroken: true }
    const requests = stubFetch([
      {
        prefix: '/api/v1/search/views/view-scope/scope/unlink',
        respond: () => jsonResponse({ view: { ...broken, workspaceId: null, scopeBroken: false } }),
      },
      {
        prefix: '/api/v1/search/views',
        respond: () => jsonResponse({ items: [broken] }),
      },
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse()) },
      ...baseRoutes(),
    ])

    render(withProviders(<SearchPage />))
    expect(await screen.findByTestId('scope-broken-banner')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('scope-unlink'))
    await waitFor(() => {
      const post = requests.find((r) => r.url.includes('/scope/unlink'))
      expect(post?.method).toBe('POST')
    })
  })
})

// ---- N149 主题演变时间线 -----------------------------------------------------

const TIMELINE_BODY = {
  months: [
    { month: '2026-09', count: 2 },
    ...Array.from({ length: 23 }, (_, i) => ({ month: `2024-${String(i + 10).padStart(2, '0')}`, count: 0 })),
  ],
  monthFrom: '2024-10',
  monthTo: '2026-10',
  total: 2,
  annotations: [
    {
      id: 'ann-1',
      entryRef: 'rss:1',
      excerpt: 'Rust 所有权笔记',
      note: '',
      color: 'yellow',
      createdAt: '2026-09-23T08:00:00Z',
      updatedAt: '2026-09-23T08:00:00Z',
    },
    {
      id: 'ann-2',
      entryRef: 'rss:2',
      excerpt: '另一条',
      note: '关注性能',
      color: 'green',
      createdAt: '2026-09-23T07:00:00Z',
      updatedAt: '2026-09-23T07:00:00Z',
    },
  ],
  annotationsComplete: true,
}

describe('N149 主题演变时间线（SearchPage）', () => {
  it('同参 GET timeline；月份柱状与批注卡片渲染', async () => {
    const requests = stubFetch([
      { prefix: '/api/v1/search/timeline', respond: () => jsonResponse(TIMELINE_BODY) },
      ...baseRoutes(),
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse([{ entryRef: 'e1', title: 'Rust 发布' }])) },
    ])

    render(withProviders(<SearchPage />))
    await submitQuery('rust')
    await waitFor(() =>
      expect(requests.some((r) => r.url.startsWith('/api/v1/search?'))).toBe(true),
    )
    fireEvent.click(screen.getByTestId('timeline-toggle'))

    expect(await screen.findByTestId('timeline-panel')).toBeInTheDocument()
    await waitFor(() => {
      const get = requests.find((r) => r.url.startsWith('/api/v1/search/timeline'))
      expect(get).toBeDefined()
      expect(get?.url).toContain('q=rust')
    })
    expect(screen.getByTestId('timeline-months')).toBeInTheDocument()
    // 24 个月柱状。
    expect(screen.getByTitle('2026-09：2 条')).toBeInTheDocument()
    // 批注卡片（excerpt + note 均展示）。
    expect(screen.getByText('Rust 所有权笔记')).toBeInTheDocument()
    expect(screen.getByText('关注性能')).toBeInTheDocument()
  })

  it('隐藏批注 → 设备本地排除 + 卡片消失 + refetch', async () => {
    const requests = stubFetch([
      { prefix: '/api/v1/search/timeline', respond: () => jsonResponse(TIMELINE_BODY) },
      ...baseRoutes(),
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse([{ entryRef: 'e1', title: 'Rust 发布' }])) },
    ])

    render(withProviders(<SearchPage />))
    await submitQuery('rust')
    fireEvent.click(screen.getByTestId('timeline-toggle'))
    expect(await screen.findByTestId('timeline-panel')).toBeInTheDocument()
    expect(await screen.findByText('Rust 所有权笔记')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /隐藏批注「Rust 所有权笔记」/ }))
    // 排除即时生效（卡片消失）+ localStorage 持久化。
    expect(screen.queryByText('Rust 所有权笔记')).toBeNull()
    expect(screen.getByText('关注性能')).toBeInTheDocument()
    const stored = JSON.parse(localStorage.getItem('lumirss-timeline-excluded-annotations') ?? '[]')
    expect(stored).toEqual(['ann-1'])
    // 触发了 timeline refetch（invalidate）。
    await waitFor(() => {
      const timelineGets = requests.filter((r) =>
        r.url.startsWith('/api/v1/search/timeline'),
      )
      expect(timelineGets.length).toBeGreaterThanOrEqual(2)
    })
  })
})
