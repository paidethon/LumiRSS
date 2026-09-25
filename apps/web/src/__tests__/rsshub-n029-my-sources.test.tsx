/** N029 测试 — 路由与来源关系图（RssHubTab 预览后「我的来源」区块）。
 *
 * 覆盖：预览成功（有 routeKey）后请求 my-sources、条目渲染（标题 /
 * 未读数 / 最近条目 ≤5）、空态诚实文案、错误态、跳转（选中 feed
 * 作用域 + 关闭对话框）。fetch 全部 mock，无真实网络。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AddSourceDialog from '../components/AddSourceDialog'
import { useReaderUi } from '../store/reader-ui'

const ROUTES = {
  configured: true,
  routes: [
    {
      id: 'github-starred-repos',
      title: 'GitHub 用户星标仓库',
      description: '某位 GitHub 用户 star 过的仓库动态。',
      pathTemplate: '/github/starred_repos/{user}',
      parameters: [
        {
          key: 'user',
          label: 'GitHub 用户名',
          required: true,
          pattern: '^[a-zA-Z0-9-]{1,39}$',
          example: 'DIYgod',
          help: 'GitHub 用户名（字母 / 数字 / 连字符）。',
        },
      ],
    },
  ],
}

const ROUTE_KEY = 'github-starred-repos|user=DIYgod'

const PREVIEW = {
  title: 'Starred repositories of DIYgod',
  feedUrl: 'http://rsshub:1200/github/starred_repos/DIYgod',
  siteUrl: 'https://github.com/DIYgod',
  description: null,
  format: 'rss' as const,
  alreadySubscribed: false,
  routeKey: ROUTE_KEY,
}

const MY_SOURCES = {
  routeKey: ROUTE_KEY,
  templateId: 'github-starred-repos',
  items: [
    {
      feedUrl: 'http://rsshub:1200/github/starred_repos/DIYgod',
      title: 'DIYgod 的星标仓库',
      unreadCount: 3,
      recentEntries: [
        { ref: 'ref-1', title: '最新星标仓库条目', published: new Date().toISOString() },
      ],
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

const MY_SOURCES_PATH = `/api/v1/rsshub/routes/${encodeURIComponent(ROUTE_KEY)}/my-sources`

async function renderSourcesFlow(
  map: Record<string, () => Response>,
  onClose: () => void = () => {},
): Promise<ReturnType<typeof makeFetchHandler>> {
  const fetchState = makeFetchHandler({
    'GET /api/v1/rsshub/routes/favorites': () => jsonResponse([]),
    'GET /api/v1/rsshub/routes/recent': () => jsonResponse([]),
    'GET /api/v1/rsshub/routes/history': () => jsonResponse({ items: [] }),
    ...map,
  })
  vi.stubGlobal('fetch', fetchState.fn)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <AddSourceDialog open onClose={onClose} />
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('tab', { name: 'RSSHub' }))
  await screen.findByText('GitHub 用户星标仓库')
  fireEvent.click(screen.getByRole('radio', { name: /GitHub 用户星标仓库/ }))
  fireEvent.change(await screen.findByLabelText(/GitHub 用户名/), {
    target: { value: 'DIYgod' },
  })
  fireEvent.click(screen.getByRole('button', { name: '预览' }))
  await screen.findByText('Starred repositories of DIYgod')
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

describe('RssHubTab — N029 我的来源', () => {
  it('预览成功后请求 my-sources 并渲染本人来源（未读数 + 最近条目）', async () => {
    const fetchState = await renderSourcesFlow({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'POST /api/v1/rsshub/preview': () => jsonResponse(PREVIEW),
      [`GET ${MY_SOURCES_PATH}`]: () => jsonResponse(MY_SOURCES),
    })
    expect(
      fetchState.calls.some(
        (call) => call.method === 'GET' && call.url.startsWith(MY_SOURCES_PATH),
      ),
    ).toBe(true)
    const section = await screen.findByRole('region', { name: '我的来源' })
    expect(section).toBeInTheDocument()
    expect(screen.getByText('DIYgod 的星标仓库')).toBeInTheDocument()
    expect(screen.getByText(/未读 3/)).toBeInTheDocument()
    expect(screen.getByText('最新星标仓库条目')).toBeInTheDocument()
  })

  it('空态：诚实文案（该路由还没有你的订阅）', async () => {
    await renderSourcesFlow({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'POST /api/v1/rsshub/preview': () => jsonResponse(PREVIEW),
      [`GET ${MY_SOURCES_PATH}`]: () =>
        jsonResponse({ routeKey: ROUTE_KEY, templateId: 'github-starred-repos', items: [] }),
    })
    expect(await screen.findByText(/该路由还没有你的订阅/)).toBeInTheDocument()
  })

  it('错误态：提示加载失败', async () => {
    await renderSourcesFlow({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'POST /api/v1/rsshub/preview': () => jsonResponse(PREVIEW),
      [`GET ${MY_SOURCES_PATH}`]: () => jsonResponse({ error: { type: 'network_error', message: 'x' } }, 500),
    })
    expect(await screen.findByText('来源列表加载失败，请稍后重试。')).toBeInTheDocument()
  })

  it('跳转：前往查看 → 选中该 feed 作用域 + 关闭对话框', async () => {
    const onClose = vi.fn()
    await renderSourcesFlow(
      {
        'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
        'POST /api/v1/rsshub/preview': () => jsonResponse(PREVIEW),
        [`GET ${MY_SOURCES_PATH}`]: () => jsonResponse(MY_SOURCES),
      },
      onClose,
    )
    fireEvent.click(await screen.findByRole('button', { name: '前往查看' }))
    const state = useReaderUi.getState()
    expect(state.section).toBe('home')
    expect(state.scope).toEqual({
      kind: 'rss-feed',
      feedUrl: 'http://rsshub:1200/github/starred_repos/DIYgod',
    })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('无 routeKey（预览未返回）时不发 my-sources 请求', async () => {
    const fetchState = await renderSourcesFlow({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'POST /api/v1/rsshub/preview': () =>
        jsonResponse({ ...PREVIEW, routeKey: undefined }),
      [`GET ${MY_SOURCES_PATH}`]: () => jsonResponse(MY_SOURCES),
    })
    expect(screen.queryByRole('region', { name: '我的来源' })).not.toBeInTheDocument()
    expect(
      fetchState.calls.some((call) => call.url.includes('my-sources')),
    ).toBe(false)
  })
})
