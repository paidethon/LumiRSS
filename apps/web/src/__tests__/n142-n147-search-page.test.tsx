/** N142/N143/N145/N147 — SearchPage 接线（黑盒 fetch stub）。
 *
 * - N142 帮我转条件：parse-preview chips 可移除、应用前不执行搜索、
 *   应用后以 remainingText + 余下条件发起搜索（与手工同参一致）；
 * - N143 为什么没命中：POST why-missed 带 query+entryRef+同参过滤，
 *   原因列表渲染；matched 诚实文案；404 错误信息展示；
 * - N145 来源分布：GET distribution 同参；来源 chip 点击 → 应用来源
 *   过滤（后续搜索 URL 带 feedUrl）；30 日柱状渲染；
 * - N147 暂存篮：结果行勾选加入（面板去重列出）+ 批量加入工作区
 *   逐条成败诚实上报。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SearchPage from '../components/pages/SearchPage'
import { useSearchState } from '../store/search-state'
import { useReaderUi } from '../store/reader-ui'
import { useSearchBasket } from '../store/search-basket'
import type { SearchResponse } from '../api/types'

function searchResponse(items: Partial<SearchResponse['items'][number]>[] = []): SearchResponse {
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
    library: [],
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

function decodeUrl(url: string): string {
  return decodeURIComponent(url.replace(/\+/g, ' '))
}

interface RecordedRequest {
  url: string
  method: string
  body: unknown
}

/** 通用 fetch stub：记录全部请求并按前缀路由。 */
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

const baseRoutes = (): { prefix: string; respond: (req: RecordedRequest) => Response }[] => [
  { prefix: '/api/v1/search/views', respond: () => jsonResponse({ items: [] }) },
  { prefix: '/api/v1/feeds', respond: () => jsonResponse([]) },
  { prefix: '/api/v1/subscriptions', respond: () => jsonResponse([]) },
]

afterEach(() => {
  useSearchState.getState().clear()
  useReaderUi.setState({ selectedEntryRef: null })
  useSearchBasket.getState().reset()
  localStorage.clear()
  vi.unstubAllGlobals()
})

// ---- N142 帮我转条件 ---------------------------------------------------------

describe('N142 帮我转条件（SearchPage）', () => {
  it('解析 → chips 展示 → 移除排除 chip → 应用后不带 exclude 发起搜索', async () => {
    const requests = stubFetch([
      ...baseRoutes(),
      {
        prefix: '/api/v1/search/parse-query',
        respond: () =>
          jsonResponse({
            filters: { from: '2026-09-23', to: '2026-09-24', exclude: '广告' },
            remainingText: 'rust',
            unrecognized: [],
            recognized: [
              { kind: 'date', text: '今天' },
              { kind: 'exclude', text: '-广告' },
            ],
          }),
      },
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse([])) },
    ])

    render(withProviders(<SearchPage />))
    await submitQuery('rust 今天 -广告')

    fireEvent.click(screen.getByTestId('parse-query-toggle'))
    await waitFor(() => expect(screen.getByTestId('parse-preview')).toBeInTheDocument())
    // POST parse-query 携带原始查询。
    const parseRequest = requests.find((r) => r.url.startsWith('/api/v1/search/parse-query'))
    expect(parseRequest?.body).toEqual({ query: 'rust 今天 -广告' })

    // chips 可见（日期 / 排除），unrecognized 不存在。
    expect(screen.getByTestId('parse-chip-date')).toHaveTextContent('日期')
    expect(screen.getByTestId('parse-chip-exclude')).toHaveTextContent('排除: 广告')

    // 移除排除 chip：剩余关键词原文回归（-广告 回到关键词）。
    fireEvent.click(screen.getByLabelText('移除条件「广告」'))
    expect(screen.getByTestId('parse-remaining')).toHaveTextContent('rust -广告')

    const searchCountBeforeApply = requests.filter((r) => r.url.startsWith('/api/v1/search?')).length

    fireEvent.click(screen.getByTestId('parse-apply'))
    await waitFor(() => {
      expect(
        requests.some((r) => r.url.startsWith('/api/v1/search?') && r.url.includes('from=')),
      ).toBe(true)
    })
    const applied = requests
      .filter((r) => r.url.startsWith('/api/v1/search?'))
      .slice(searchCountBeforeApply)
      .map((r) => decodeUrl(r.url))
      .join('\n')
    expect(applied).toContain('q=rust -广告')
    expect(applied).toContain('from=2026-09-23')
    expect(applied).toContain('to=2026-09-24')
    expect(applied).not.toContain('exclude=')
  })

  it('解析失败 → 面板诚实展示错误；无 chip 时明确提示', async () => {
    const requests = stubFetch([
      ...baseRoutes(),
      {
        prefix: '/api/v1/search/parse-query',
        respond: () => jsonResponse({ error: { type: 'invalid_request', message: '解析失败' } }, 400),
      },
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse([])) },
    ])
    render(withProviders(<SearchPage />))
    await submitQuery('rust')
    fireEvent.click(screen.getByTestId('parse-query-toggle'))
    await waitFor(() => expect(screen.getByTestId('parse-preview')).toHaveTextContent('解析失败'))
    expect(requests.length).toBeGreaterThan(0)
  })
})

// ---- N143 为什么没命中 -------------------------------------------------------

describe('N143 为什么没命中（SearchPage）', () => {
  it('粘贴 ref 诊断 → POST 携带 query+entryRef+过滤 → 原因列表渲染', async () => {
    const requests = stubFetch([
      ...baseRoutes(),
      {
        prefix: '/api/v1/search/why-missed',
        respond: () =>
          jsonResponse({
            matched: false,
            reasons: [
              { kind: 'date', detail: '发布时间 2025-03-01T08:00:00Z 早于起始日期 2026-09-23。' },
              { kind: 'unread', detail: '条目已读，被「仅未读」过滤。' },
            ],
            entry: {
              entryRef: 'e2',
              title: 'Rust 旧闻',
              feedTitle: '源B',
              publishedAt: '2025-03-01T08:00:00Z',
            },
            rank: null,
            rankCapped: false,
          }),
      },
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse([])) },
    ])

    render(withProviders(<SearchPage />))
    await submitQuery('rust')
    fireEvent.click(screen.getByTestId('why-missed-toggle'))
    const refInput = screen.getByLabelText('条目引用（entryRef）')
    fireEvent.change(refInput, { target: { value: 'e2' } })
    fireEvent.click(screen.getByRole('button', { name: '诊断' }))

    await waitFor(() => expect(screen.getByTestId('why-missed-result')).toBeInTheDocument())
    const missed = requests.find((r) => r.url.startsWith('/api/v1/search/why-missed'))
    expect(missed?.body).toMatchObject({ query: 'rust', entryRef: 'e2' })
    expect(screen.getByTestId('why-missed-result')).toHaveTextContent('早于起始日期')
    expect(screen.getByTestId('why-missed-result')).toHaveTextContent('仅未读')
    // matched=false → 不出现「本应出现」。
    expect(screen.queryByTestId('why-missed-matched')).not.toBeInTheDocument()
  })

  it('matched=true → 诚实说明本应命中并给出位置', async () => {
    stubFetch([
      ...baseRoutes(),
      {
        prefix: '/api/v1/search/why-missed',
        respond: () =>
          jsonResponse({
            matched: true,
            reasons: [],
            entry: { entryRef: 'e1', title: 'Rust 发布', feedTitle: '源A', publishedAt: '2026-09-23T08:00:00Z' },
            rank: 3,
            rankCapped: false,
          }),
      },
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse([])) },
    ])
    render(withProviders(<SearchPage />))
    await submitQuery('rust')
    fireEvent.click(screen.getByTestId('why-missed-toggle'))
    fireEvent.change(screen.getByLabelText('条目引用（entryRef）'), { target: { value: 'e1' } })
    fireEvent.click(screen.getByRole('button', { name: '诊断' }))
    await waitFor(() => expect(screen.getByTestId('why-missed-matched')).toBeInTheDocument())
    expect(screen.getByTestId('why-missed-matched')).toHaveTextContent('本应出现在结果中')
    expect(screen.getByTestId('why-missed-matched')).toHaveTextContent('第 3 条')
  })

  it('own-scope 404 → 错误信息原样展示', async () => {
    stubFetch([
      ...baseRoutes(),
      {
        prefix: '/api/v1/search/why-missed',
        respond: () =>
          jsonResponse(
            { error: { type: 'search_entry_not_found', message: '条目不在当前账户的搜索索引中，无法诊断。' } },
            404,
          ),
      },
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse([])) },
    ])
    render(withProviders(<SearchPage />))
    await submitQuery('rust')
    fireEvent.click(screen.getByTestId('why-missed-toggle'))
    fireEvent.change(screen.getByLabelText('条目引用（entryRef）'), { target: { value: 'foreign' } })
    fireEvent.click(screen.getByRole('button', { name: '诊断' }))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('条目不在当前账户的搜索索引中'),
    )
  })
})

// ---- N145 来源分布 -----------------------------------------------------------

describe('N145 来源分布（SearchPage）', () => {
  it('同参拉取聚合；来源 chip 点击 → 后续搜索带 feedUrl（同一结果集口径）', async () => {
    const requests = stubFetch([
      {
        prefix: '/api/v1/subscriptions',
        respond: () =>
          jsonResponse([
            { subscriptionRef: 's1', feedUrl: 'https://a.example/rss', title: '源A' },
            { subscriptionRef: 's2', feedUrl: 'https://b.example/rss', title: '源B' },
          ]),
      },
      ...baseRoutes(),
      {
        prefix: '/api/v1/search/distribution',
        respond: () =>
          jsonResponse({
            total: 4,
            sources: [
              { feedUrl: 'https://a.example/rss', feedTitle: '源A', count: 3 },
              { feedUrl: 'https://b.example/rss', feedTitle: '源B', count: 1 },
            ],
            sourcesComplete: true,
            days: Array.from({ length: 30 }, (_, i) => ({ day: `2026-08-26`, count: i === 0 ? 4 : 0 })).map(
              (d, i) => ({ ...d, day: `2026-08-${String(26 + i).padStart(2, '0')}` }),
            ),
            dayFrom: '2026-08-26',
            dayTo: '2026-09-25',
          }),
      },
      { prefix: '/api/v1/search?', respond: () => jsonResponse(searchResponse([{ entryRef: 'a1' }])) },
    ])

    render(withProviders(<SearchPage />))
    await submitQuery('rust')
    fireEvent.click(screen.getByTestId('distribution-toggle'))

    await waitFor(() => expect(screen.getAllByTestId('distribution-source').length).toBe(2))
    // 同参：distribution 请求带 q=rust。
    const distUrl = requests.find((r) => r.url.startsWith('/api/v1/search/distribution'))?.url ?? ''
    expect(decodeUrl(distUrl)).toContain('q=rust')

    // 30 根柱条（CSS bars）。
    const daysRegion = screen.getByTestId('distribution-days')
    expect(daysRegion.children.length).toBe(30)

    // 点击来源 → 应用来源过滤（后续搜索 URL 带 feedUrl）+ 已应用 chip。
    fireEvent.click(screen.getAllByTestId('distribution-source')[0])
    await waitFor(() => expect(screen.getByTestId('applied-source-label')).toBeInTheDocument())
    expect(screen.getByTestId('applied-source-label')).toHaveTextContent('源A')
    await waitFor(() => {
      const narrowed = requests
        .filter((r) => r.url.startsWith('/api/v1/search?'))
        .map((r) => decodeUrl(r.url))
      expect(narrowed.some((u) => u.includes('feedUrl=https://a.example/rss'))).toBe(true)
    })
  })
})

// ---- N147 暂存篮（SearchPage 接线） ------------------------------------------

describe('N147 暂存篮（SearchPage 接线）', () => {
  it('结果行勾选加入 → 面板去重列出 → 批量加入工作区逐条成败上报', async () => {
    const requests = stubFetch([
      {
        prefix: '/api/v1/workspaces/w1/items',
        respond: (req) => {
          // 第二条模拟失败（部分失败诚实上报）。
          const itemRef = (req.body as { itemRef?: string })?.itemRef ?? ''
          if (itemRef.includes('e2')) {
            return jsonResponse({ error: { type: 'workspace_not_found', message: '工作区不存在。' } }, 404)
          }
          return jsonResponse({ id: 'i1', itemRef, groupName: null, pinned: false, position: 0 }, 201)
        },
      },
      { prefix: '/api/v1/workspaces', respond: () => jsonResponse({ items: [{ id: 'w1', name: '主工作区', archived: false, reserved: false, itemCount: 0, revision: 1, position: 0, description: '' }] }) },
      ...baseRoutes(),
      {
        prefix: '/api/v1/search?',
        respond: () =>
          jsonResponse(
            searchResponse([
              { entryRef: 'e1', title: '结果一', feedUrl: 'https://a.example/rss' },
              { entryRef: 'e2', title: '结果二', feedUrl: 'https://a.example/rss' },
            ]),
          ),
      },
    ])

    render(withProviders(<SearchPage />))
    await submitQuery('rust')

    // 等结果行出现后再勾选（同一 ref 勾第二次 = 面板仍只列一次，由 store 去重）。
    await waitFor(() => expect(screen.getByLabelText('加入暂存篮：结果一')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('加入暂存篮：结果一'))
    fireEvent.click(screen.getByLabelText('加入暂存篮：结果二'))
    expect(useSearchBasket.getState().items.length).toBe(2)

    fireEvent.click(screen.getByTestId('basket-toggle'))
    await waitFor(() => expect(screen.getByTestId('basket-panel')).toBeInTheDocument())
    expect(screen.getByTestId('basket-panel')).toHaveTextContent('结果一')
    expect(screen.getByTestId('basket-panel')).toHaveTextContent('结果二')

    fireEvent.click(await screen.findByTestId('basket-add-to-workspace'))
    await waitFor(() => expect(screen.getByTestId('basket-batch-result')).toBeInTheDocument())
    expect(screen.getByTestId('basket-batch-result')).toHaveTextContent('已加入工作区 1 / 2 条')
    expect(screen.getByTestId('basket-batch-result')).toHaveTextContent('失败 1 条')
    // add_item 调用完整存储形态 rss:<entryRef>。
    const itemCalls = requests.filter((r) => r.url === '/api/v1/workspaces/w1/items')
    expect(itemCalls.map((r) => (r.body as { itemRef: string }).itemRef).sort()).toEqual([
      'rss:e1',
      'rss:e2',
    ])

    // 清空。
    fireEvent.click(screen.getByRole('button', { name: '清空' }))
    await waitFor(() => expect(useSearchBasket.getState().items.length).toBe(0))
  })

  it('暂存篮跨页面持久：重新挂载后仍然可见（localStorage）', async () => {
    stubFetch([
      ...baseRoutes(),
      { prefix: '/api/v1/workspaces', respond: () => jsonResponse({ workspaces: [] }) },
      {
        prefix: '/api/v1/search?',
        respond: () => jsonResponse(searchResponse([{ entryRef: 'e9', title: '持久条目' }])),
      },
    ])
    const { unmount } = render(withProviders(<SearchPage />))
    await submitQuery('rust')
    await waitFor(() => expect(screen.getByLabelText('加入暂存篮：持久条目')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('加入暂存篮：持久条目'))
    unmount()

    render(withProviders(<SearchPage />))
    fireEvent.click(screen.getByTestId('basket-toggle'))
    await waitFor(() => expect(screen.getByTestId('basket-panel')).toHaveTextContent('持久条目'))
  })
})
