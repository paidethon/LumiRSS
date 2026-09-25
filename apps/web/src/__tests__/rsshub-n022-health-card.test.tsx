/** N022 测试 — 路由健康一键自检卡（RssHubTab 内）。
 *
 * 覆盖：自检按钮并行调用预览 + 最近运行，聚合为判定卡
 * {预览: ok/失败类, 最近运行: x/y ok, 缓存: 年龄, 依赖: chips}；
 * 单面失败 → 该分区诚实失败、其余分区照常（honest partial）；
 * 纯函数：summarizeRouteRuns / formatCacheAge。fetch 全部 mock。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AddSourceDialog from '../components/AddSourceDialog'
import { formatCacheAge, summarizeRouteRuns } from '../lib/rsshub-health'
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
  cache: { ageS: 42, fresh: false },
  requires: { login: true, cookies: null, render: null, extraService: null },
}

const HISTORY = {
  items: [
    { id: 2, routeKey: 'hackernews', ranAt: '2026-09-25T00:00:00Z', status: 'ok', durationMs: 100, entryCount: 5, failureClass: null },
    { id: 1, routeKey: 'hackernews', ranAt: '2026-09-25T00:01:00Z', status: 'failed', durationMs: 300, entryCount: null, failureClass: 'rsshub_unreachable' },
  ],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function makeFetchHandler(map: Record<string, () => Response>) {
  const calls: { method: string; url: string }[] = []
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const route = `${method} ${url.split('?')[0]}`
    const handler = map[route]
    if (handler === undefined) {
      throw new Error(`unexpected fetch: ${route}`)
    }
    calls.push({ method, url })
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

async function renderAfterPreview(previewResponse: () => Response) {
  const fetchState = makeFetchHandler({
    'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
    'GET /api/v1/rsshub/routes/favorites': () => jsonResponse([]),
    'GET /api/v1/rsshub/routes/recent': () => jsonResponse([]),
    'GET /api/v1/rsshub/routes/history': () => jsonResponse(HISTORY),
    'POST /api/v1/rsshub/preview': previewResponse,
  })
  vi.stubGlobal('fetch', fetchState.fn)
  render(withProviders(<AddSourceDialog open onClose={() => {}} />))
  fireEvent.click(screen.getByRole('tab', { name: 'RSSHub' }))
  await screen.findByText('Hacker News')
  fireEvent.click(screen.getByRole('radio', { name: /Hacker News/ }))
  fireEvent.click(screen.getByRole('button', { name: '预览' }))
  await screen.findByText('Hacker News Feed')
  return fetchState
}

describe('RssHubTab — N022 一键自检卡', () => {
  it('单按钮并行聚合四面：预览 ok / 最近运行 x/y / 缓存年龄 / 依赖 chips', async () => {
    const fetchState = await renderAfterPreview(() => jsonResponse(PREVIEW))
    // 初始未检查：说明文案
    expect(screen.getByTestId('route-health-card')).toHaveTextContent('并行检查')

    fireEvent.click(screen.getByRole('button', { name: '开始自检' }))

    const card = await screen.findByTestId('route-health-card')
    expect(card).toHaveTextContent('ok')
    expect(card).toHaveTextContent('1/2 ok')
    expect(card).toHaveTextContent('42 秒前')
    // 依赖 chips（requires.login = true → 需要登录）
    expect(card).toHaveTextContent('需要登录')

    // 自检确实再次并行调用了预览与时间线
    const previewCalls = fetchState.calls.filter((c) => c.url.includes('/rsshub/preview'))
    expect(previewCalls.length).toBeGreaterThanOrEqual(2)
    const historyCall = fetchState.calls.find((c) => c.url.includes('/routes/history'))
    expect(historyCall?.url).toContain('routeKey=hackernews')
  })

  it('单面失败 → 该分区诚实失败，其余分区照常（honest partial）', async () => {
    let checkCount = 0
    await renderAfterPreview(() => {
      checkCount += 1
      if (checkCount === 1) return jsonResponse(PREVIEW) // 首次预览成功（进入卡所在阶段）
      return jsonResponse({ error: { type: 'rsshub_unreachable', message: 'RSSHub 不可达' } }, 502)
    })
    fireEvent.click(screen.getByRole('button', { name: '开始自检' }))
    const card = await screen.findByTestId('route-health-card')
    expect(card).toHaveTextContent('失败') // 预览分区诚实失败
    // 其余分区仍如实呈现（最近运行来自独立的时间线面）
    expect(card).toHaveTextContent('1/2 ok')
  })
})

describe('rsshub-health 纯函数', () => {
  it('summarizeRouteRuns 统计 ok/failed', () => {
    expect(
      summarizeRouteRuns([
        { id: 1, routeKey: 'k', ranAt: '2026-09-25T00:00:00Z', status: 'ok', durationMs: 1, entryCount: 1, failureClass: null },
        { id: 2, routeKey: 'k', ranAt: '2026-09-25T00:00:00Z', status: 'failed', durationMs: 2, entryCount: null, failureClass: 'x' },
        { id: 3, routeKey: 'k', ranAt: '2026-09-25T00:00:00Z', status: 'ok', durationMs: 3, entryCount: 2, failureClass: null },
      ]),
    ).toEqual({ total: 3, ok: 2, failed: 1 })
    expect(summarizeRouteRuns([])).toEqual({ total: 0, ok: 0, failed: 0 })
  })

  it('formatCacheAge 诚实呈现缓存年龄', () => {
    expect(formatCacheAge(undefined)).toBe('—')
    expect(formatCacheAge({ ageS: 0, fresh: true })).toBe('刚抓取')
    expect(formatCacheAge({ ageS: 42, fresh: false })).toBe('42 秒前')
    expect(formatCacheAge({ ageS: 90, fresh: false })).toBe('2 分钟前')
    expect(formatCacheAge({ ageS: 7200, fresh: false })).toBe('2 小时前')
    expect(formatCacheAge({ ageS: null, fresh: false })).toBe('—')
  })
})
