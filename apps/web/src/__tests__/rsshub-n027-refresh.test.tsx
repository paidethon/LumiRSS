/** N027 测试 — RSSHub 路由刷新（预览缓存控制）。
 *
 * 覆盖：刷新按钮调用 POST /api/v1/rsshub/refresh（带服务端派生
 * routeKey）、成功显示本次条目数、429 限速的诚实文案（含等待秒数）。
 * fetch 全部 mock。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AddSourceDialog from '../components/AddSourceDialog'
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
  cache: { ageS: 0, fresh: true },
}

const HISTORY = {
  items: [
    {
      id: 1,
      routeKey: 'hackernews',
      ranAt: new Date().toISOString(),
      status: 'ok',
      durationMs: 90,
      entryCount: 4,
      failureClass: null,
    },
  ],
}

const REFRESHED = {
  routeKey: 'hackernews',
  title: 'Hacker News Feed',
  entryCount: 9,
  ranAt: new Date().toISOString(),
  durationMs: 210,
  cache: { ageS: 0, fresh: true },
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

async function renderAndPreview(
  map: Record<string, () => Response>,
): Promise<ReturnType<typeof makeFetchHandler>> {
  const fetchState = makeFetchHandler({
    'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
    'GET /api/v1/rsshub/routes/favorites': () => jsonResponse([]),
    'GET /api/v1/rsshub/routes/recent': () => jsonResponse([]),
    'GET /api/v1/rsshub/routes/history': () => jsonResponse(HISTORY),
    'POST /api/v1/rsshub/preview': () => jsonResponse(PREVIEW),
    ...map,
  })
  vi.stubGlobal('fetch', fetchState.fn)
  render(withProviders(<AddSourceDialog open onClose={() => {}} />))
  fireEvent.click(screen.getByRole('tab', { name: 'RSSHub' }))
  await screen.findByText('Hacker News')
  fireEvent.click(screen.getByRole('radio', { name: /Hacker News/ }))
  fireEvent.click(screen.getByRole('button', { name: '预览' }))
  await screen.findByRole('region', { name: '最近运行' })
  return fetchState
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({ section: 'subscriptions', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('RssHubTab — N027 路由刷新', () => {
  it('刷新按钮调用 refresh（带 routeKey）并显示本次条目数', async () => {
    const fetchState = await renderAndPreview({
      'POST /api/v1/rsshub/refresh': () => jsonResponse(REFRESHED),
    })
    fireEvent.click(
      await screen.findByRole('button', { name: '强制刷新该路由' }),
    )
    expect(
      await screen.findByText(/已刷新，本次获取 9 条内容/),
    ).toBeInTheDocument()
    const refreshCall = fetchState.calls.find(
      (c) => c.url === '/api/v1/rsshub/refresh',
    )
    expect(refreshCall?.method).toBe('POST')
    expect(refreshCall?.body).toEqual({ routeKey: 'hackernews' })
  })

  it('429 限速：诚实文案 + Retry-After 等待秒数', async () => {
    await renderAndPreview({
      'POST /api/v1/rsshub/refresh': () =>
        new Response(
          JSON.stringify({
            error: {
              type: 'rsshub_refresh_rate_limited',
              message: 'Too many refreshes; retry after 42 seconds.',
              retryAfterSeconds: 42,
            },
          }),
          {
            status: 429,
            headers: { 'content-type': 'application/json', 'Retry-After': '42' },
          },
        ),
    })
    fireEvent.click(
      await screen.findByRole('button', { name: '强制刷新该路由' }),
    )
    expect(await screen.findByText('刷新过于频繁，请稍后再试。')).toBeInTheDocument()
    expect(screen.getByText(/约 42 秒后可再次刷新/)).toBeInTheDocument()
  })
})
