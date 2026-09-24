/** N021 测试 — RSSHub 路由收藏与最近使用（RssHubTab）。
 *
 * 覆盖：收藏/最近使用区块渲染（含脱敏 '***' 参数）、目录行 ★ 切换
 * （PUT/DELETE 服务端收藏）、点最近条目回填参数。fetch 全部 mock。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    {
      id: 'hackernews',
      title: 'Hacker News',
      description: 'Hacker News 首页热门。',
      pathTemplate: '/hackernews',
      parameters: [],
    },
  ],
}

const FAVORITES = [
  {
    routeKey: 'github-starred-repos',
    templateId: 'github-starred-repos',
    label: '置顶收藏',
    params: {},
    createdAt: '2026-09-20T10:00:00+00:00',
  },
]

const RECENT = [
  {
    routeKey: 'github-starred-repos|accessKey=***&user=DIYgod',
    templateId: 'github-starred-repos',
    params: { user: 'DIYgod', accessKey: '***' },
    lastUsedAt: new Date().toISOString(),
    lastSuccessAt: new Date().toISOString(),
  },
]

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

async function renderRssHubTab(
  map: Record<string, () => Response>,
): Promise<ReturnType<typeof makeFetchHandler>> {
  const fetchState = makeFetchHandler(map)
  vi.stubGlobal('fetch', fetchState.fn)
  render(withProviders(<AddSourceDialog open onClose={() => {}} />))
  fireEvent.click(screen.getByRole('tab', { name: 'RSSHub' }))
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

describe('RssHubTab — N021 收藏与最近使用', () => {
  it('收藏与最近使用区块渲染在目录上方；最近条目展示脱敏参数', async () => {
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/routes/favorites': () => jsonResponse(FAVORITES),
      'GET /api/v1/rsshub/routes/recent': () => jsonResponse(RECENT),
    })
    expect(await screen.findByRole('region', { name: '收藏' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '最近使用' })).toBeInTheDocument()
    // 目录级收藏（params 为空）条目回退展示路径模板 + 标签作元信息
    expect(screen.getByText('置顶收藏')).toBeInTheDocument()
    expect(screen.getAllByText('/github/starred_repos/{user}').length).toBeGreaterThan(0)
    // 敏感参数值只以 *** 哨兵出现
    expect(screen.getByText(/accessKey=\*\*\*/)).toBeInTheDocument()
    expect(screen.queryByText(/sekret/)).not.toBeInTheDocument()
    // 目录仍在下方渲染
    expect(screen.getByText('Hacker News')).toBeInTheDocument()
  })

  it('目录行 ★ 收藏：PUT 服务端收藏（params 为空 = 目录级）', async () => {
    const fetchState = await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/routes/favorites': () => jsonResponse([]),
      'GET /api/v1/rsshub/routes/recent': () => jsonResponse([]),
      'PUT /api/v1/rsshub/routes/favorites': () =>
        jsonResponse({
          routeKey: 'hackernews',
          templateId: 'hackernews',
          label: 'Hacker News',
          params: {},
          createdAt: '2026-09-20T10:00:00+00:00',
        }),
    })
    await screen.findByText('Hacker News')
    fireEvent.click(screen.getByRole('button', { name: '收藏 Hacker News' }))
    await waitFor(() => {
      const put = fetchState.calls.find((c) => c.method === 'PUT')
      expect(put).toBeDefined()
    })
    const put = fetchState.calls.find((c) => c.method === 'PUT')
    expect(put?.body).toEqual({ routeId: 'hackernews', params: {}, label: 'Hacker News' })
  })

  it('已收藏路由再点 ★：DELETE 对应 routeKey', async () => {
    const fetchState = await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/routes/favorites': () => jsonResponse(FAVORITES),
      'GET /api/v1/rsshub/routes/recent': () => jsonResponse([]),
      'DELETE /api/v1/rsshub/routes/favorites/github-starred-repos': () =>
        new Response(null, { status: 204 }),
    })
    await screen.findByRole('radio', { name: /GitHub 用户星标仓库/ })
    fireEvent.click(
      await screen.findByRole('button', { name: '取消收藏 GitHub 用户星标仓库' }),
    )
    await waitFor(() => {
      expect(
        fetchState.calls.some(
          (c) =>
            c.method === 'DELETE' &&
            c.url === '/api/v1/rsshub/routes/favorites/github-starred-repos',
        ),
      ).toBe(true)
    })
  })

  it('点最近使用条目：回填路由与参数（哨兵值原样回填，需重填敏感值）', async () => {
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/routes/favorites': () => jsonResponse([]),
      'GET /api/v1/rsshub/routes/recent': () => jsonResponse(RECENT),
    })
    const entry = await screen.findByRole('button', {
      name: /accessKey=\*\*\*/,
    })
    fireEvent.click(entry)
    const input = await screen.findByLabelText(/GitHub 用户名/)
    expect(input).toHaveValue('DIYgod')
    // 处于参数表单阶段（预览按钮出现）
    expect(screen.getByRole('button', { name: '预览' })).toBeInTheDocument()
  })
})
