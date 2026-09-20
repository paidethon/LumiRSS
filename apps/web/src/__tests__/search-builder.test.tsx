/** F017 搜索条件构建器 —— 来源/未读/收藏/仅摘要维度 + 查询语义预览。 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  buildAdvancedSearchUrl,
  describeAdvancedQuery,
  hasBuilderFilters,
} from '../lib/search-advanced'

describe('F017 构建器纯函数', () => {
  it('F017: hasSummary 进入请求 URL；布尔序列化', () => {
    const url = buildAdvancedSearchUrl({
      q: 'k8s',
      feedUrl: 'https://a.example/rss',
      state: 'unread',
      favorite: true,
      hasSummary: true,
    })
    expect(url).toContain('hasSummary=true')
    expect(url).toContain('feedUrl=')
    expect(url).toContain('state=unread')
    expect(buildAdvancedSearchUrl({ q: 'x', hasSummary: false })).toContain('hasSummary=false')
  })

  it('F017: hasBuilderFilters 空态判定', () => {
    expect(
      hasBuilderFilters({ sourceFeedUrl: null, unread: null, favorite: null, hasSummary: null }),
    ).toBe(false)
    expect(
      hasBuilderFilters({ sourceFeedUrl: 'https://x', unread: null, favorite: null, hasSummary: null }),
    ).toBe(true)
  })

  it('F017: describeAdvancedQuery 生成 AND 语义', () => {
    const text = describeAdvancedQuery({
      q: 'k8s',
      sourceLabel: '源A',
      unread: true,
      intitle: '运维',
      hasSummary: true,
    })
    expect(text).toContain('来源=源A')
    expect(text).toContain('未读')
    expect(text).toContain('标题含「运维」')
    expect(text).toContain('有摘要')
    expect(text.split(' AND ').length).toBeGreaterThanOrEqual(4)
  })
})

// ---- SearchPage 面板集成 ----

const SUBSCRIPTIONS = [
  { subscriptionRef: 's1.a', title: '源甲', feedUrl: 'https://a.example/rss', category: null },
]

const SEARCH_PAGE = {
  items: [],
  hasMore: false,
  nextCursor: null,
  index: null,
  library: [],
}

function mockSearchApiFetch(onUrl: (url: string) => void) {
  return vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST') {
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
    }
    const url = String(input)
    if (url.startsWith('/api/v1/search')) {
      onUrl(url)
      return Promise.resolve(new Response(JSON.stringify(SEARCH_PAGE), { status: 200 }))
    }
    if (url.startsWith('/api/v1/feeds')) {
      return Promise.resolve(
        new Response(
          JSON.stringify([{ id: 'user/-/label/默认', title: '默认', feedUrl: 'https://a.example/rss' }]),
          { status: 200 },
        ),
      )
    }
    if (url.startsWith('/api/v1/subscriptions')) {
      return Promise.resolve(new Response(JSON.stringify(SUBSCRIPTIONS), { status: 200 }))
    }
    if (url.startsWith('/api/v1/entries')) {
      return Promise.resolve(new Response(JSON.stringify({ items: [], nextCursor: null }), { status: 200 }))
    }
    if (url.startsWith('/api/v1/search/views')) {
      return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
    }
    return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
  })
}

describe('F017 SearchPage 构建器面板', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('F017: 面板选来源/勾未读/仅摘要 → 应用后请求携带维度参数；语义预览展示', async () => {
    const urls: string[] = []
    vi.stubGlobal('fetch', mockSearchApiFetch((u) => urls.push(u)))
    const { default: SearchPage } = await import('../components/pages/SearchPage')
    const { useReaderUi } = await import('../store/reader-ui')
    useReaderUi.setState({ section: 'search', view: 'all' })
    const qc = new (await import('@tanstack/react-query')).QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const { QueryClientProvider } = await import('@tanstack/react-query')
    render(
      <QueryClientProvider client={qc}>
        <SearchPage />
      </QueryClientProvider>,
    )

    const input = await screen.findByRole('searchbox')
    fireEvent.change(input, { target: { value: 'k8s' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    fireEvent.click(screen.getByTestId('advanced-panel-toggle'))
    fireEvent.change(screen.getByLabelText('来源筛选'), { target: { value: 'https://a.example/rss' } })
    fireEvent.click(screen.getByRole('checkbox', { name: '仅未读' }))
    fireEvent.click(screen.getByRole('checkbox', { name: '仅摘要有内容' }))

    const semantic = screen.getByTestId('query-semantic')
    expect(semantic.textContent).toContain('来源=源甲')
    expect(semantic.textContent).toContain('未读')
    expect(semantic.textContent).toContain('有摘要')

    fireEvent.click(within(screen.getByTestId('advanced-panel')).getByRole('button', { name: '应用' }))
    await waitFor(() => {
      const advanced = urls.find((u) => u.includes('hasSummary=true'))
      expect(advanced).toBeDefined()
      expect(advanced).toContain('feedUrl=')
      expect(advanced).toContain('state=unread')
    })
  })
})

