/** N025 测试 — RSSHub 路由最近运行时间线（RssHubTab）。
 *
 * 覆盖：预览成功后以服务端派生 routeKey 拉取时间线；时间线行渲染
 * （状态点、条目数、时延、失败分类标签、相对时间）；失败分类中文
 * 标签映射。fetch 全部 mock。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AddSourceDialog from '../components/AddSourceDialog'
import { rsshubFailureClassLabel } from '../lib/rsshub-params'
import { useReaderUi } from '../store/reader-ui'

const ROUTES = {
  configured: true,
  routes: [
    {
      id: 'hackernews',
      title: 'Hacker News',
      description: 'Hacker News 首页热门。',
      pathTemplate: '/hackernews',
      parameters: [],
    },
  ],
}

const PREVIEW = {
  title: 'Hacker News Feed',
  feedUrl: 'http://rsshub:1200/hackernews',
  siteUrl: 'https://news.ycombinator.com/',
  description: null,
  format: 'rss' as const,
  alreadySubscribed: false,
  routeKey: 'hackernews',
}

const HISTORY = {
  items: [
    {
      id: 2,
      routeKey: 'hackernews',
      ranAt: new Date(Date.now() - 30_000).toISOString(),
      status: 'ok',
      durationMs: 120,
      entryCount: 7,
      failureClass: null,
    },
    {
      id: 1,
      routeKey: 'hackernews',
      ranAt: new Date(Date.now() - 120_000).toISOString(),
      status: 'failed',
      durationMs: 400,
      entryCount: null,
      failureClass: 'rsshub_unreachable',
    },
  ],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function makeFetchHandler(map: Record<string, () => Response>) {
  const calls: { method: string; url: string; body?: unknown }[] = []
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    let body: unknown
    try {
      body = init?.body !== undefined ? JSON.parse(String(init.body)) : undefined
    } catch {
      body = undefined
    }
    const route = `${method} ${url.split('?')[0]}`
    const handler = map[route]
    if (handler === undefined) {
      throw new Error(`unexpected fetch: ${route}`)
    }
    calls.push({ method, url, body })
    return handler()
  })
  return { fn, calls }
}

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({ section: 'subscriptions', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('RssHubTab — N025 最近运行时间线', () => {
  it('预览成功后按服务端 routeKey 拉取时间线并渲染状态/条目/时延/分类', async () => {
    const fetchState = makeFetchHandler({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/routes/favorites': () => jsonResponse([]),
      'GET /api/v1/rsshub/routes/recent': () => jsonResponse([]),
      'GET /api/v1/rsshub/routes/history': () => jsonResponse(HISTORY),
      'POST /api/v1/rsshub/preview': () => jsonResponse(PREVIEW),
    })
    vi.stubGlobal('fetch', fetchState.fn)
    render(withProviders(<AddSourceDialog open onClose={() => {}} />))
    fireEvent.click(screen.getByRole('tab', { name: 'RSSHub' }))

    await screen.findByText('Hacker News')
    fireEvent.click(screen.getByRole('radio', { name: /Hacker News/ }))
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByRole('region', { name: '最近运行' })).toBeInTheDocument()

    // 请求带服务端派生的 routeKey
    const historyCall = fetchState.calls.find(
      (c) => c.url.startsWith('/api/v1/rsshub/routes/history'),
    )
    expect(historyCall?.url).toContain('routeKey=hackernews')

    // 成功行：7 条 + 120 ms；失败行：RSSHub 不可达
    expect(await screen.findByText(/7 条/)).toBeInTheDocument()
    expect(screen.getByText(/120 ms/)).toBeInTheDocument()
    expect(screen.getByText('RSSHub 不可达')).toBeInTheDocument()
  })

  it('时间线为空：诚实空态', async () => {
    await renderWithMap({
      'GET /api/v1/rsshub/routes/history': () => jsonResponse({ items: [] }),
    })
    expect(await screen.findByText('该路由暂无运行记录。')).toBeInTheDocument()
  })

  it('失败分类 → 中文标签（未知分类诚实回显）', () => {
    expect(rsshubFailureClassLabel('rsshub_unreachable')).toBe('RSSHub 不可达')
    expect(rsshubFailureClassLabel('upstream_reject')).toBe('上游拒绝')
    expect(rsshubFailureClassLabel('auth_failure')).toBe('鉴权失败')
    expect(rsshubFailureClassLabel('no_new_content')).toBe('无新内容')
    expect(rsshubFailureClassLabel('mystery_class')).toBe('mystery_class')
  })
})

async function renderWithMap(map: Record<string, () => Response>) {
  const fetchState = makeFetchHandler({
    'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
    'GET /api/v1/rsshub/routes/favorites': () => jsonResponse([]),
    'GET /api/v1/rsshub/routes/recent': () => jsonResponse([]),
    'POST /api/v1/rsshub/preview': () => jsonResponse(PREVIEW),
    ...map,
  })
  vi.stubGlobal('fetch', fetchState.fn)
  render(withProviders(<AddSourceDialog open onClose={() => {}} />))
  fireEvent.click(screen.getByRole('tab', { name: 'RSSHub' }))
  await screen.findByText('Hacker News')
  fireEvent.click(screen.getByRole('radio', { name: /Hacker News/ }))
  fireEvent.click(screen.getByRole('button', { name: '预览' }))
  await screen.findByText(/Hacker News Feed/)
  return fetchState
}
