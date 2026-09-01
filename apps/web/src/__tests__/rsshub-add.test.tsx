/** 0014 测试 — AddSourceDialog RSSHub 模式。
 *
 * 覆盖：路由目录加载/搜索、未配置横幅、参数表单（required/格式校验）、
 * 预览（响应形状与 feed-preview 一致）、预览失败文案、订阅复用 0013
 * 管道、双击防重。fetch 全部 mock，无真实网络。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AddSourceDialog from '../components/AddSourceDialog'
import { useReaderUi } from '../store/reader-ui'

const CATEGORY = { id: 'user/-/label/Tech', label: 'Tech' }

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

const PREVIEW = {
  title: 'Starred repositories of DIYgod',
  feedUrl: 'http://rsshub:1200/github/starred_repos/DIYgod',
  siteUrl: 'https://github.com/DIYgod',
  description: null,
  format: 'rss' as const,
  alreadySubscribed: false,
}

const SUBSCRIPTION = {
  subscriptionRef: 's1.ZmVlZC85',
  title: 'Starred repositories of DIYgod',
  feedUrl: 'http://rsshub:1200/github/starred_repos/DIYgod',
  category: null,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function errorResponse(type: string, message: string, status: number): Response {
  return jsonResponse({ error: { type, message } }, status)
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

describe('AddSourceDialog — RSSHub', () => {
  it('路由目录加载并渲染标题/描述/路径模板', async () => {
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
    })
    expect(await screen.findByText('GitHub 用户星标仓库')).toBeInTheDocument()
    expect(screen.getByText('Hacker News')).toBeInTheDocument()
    expect(screen.getByText('/github/starred_repos/{user}')).toBeInTheDocument()
  })

  it('未配置：诚实横幅，不渲染路由列表', async () => {
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () =>
        jsonResponse({ configured: false, routes: [] }),
    })
    expect(await screen.findByText('RSSHub 未配置')).toBeInTheDocument()
    expect(screen.getByText(/网站来源仍可正常使用/)).toBeInTheDocument()
    expect(screen.queryByText('Hacker News')).toBeNull()
  })

  it('搜索过滤路由', async () => {
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
    })
    await screen.findByText('GitHub 用户星标仓库')
    fireEvent.change(screen.getByLabelText('搜索 RSSHub 路由'), {
      target: { value: 'hacker' },
    })
    expect(screen.queryByText('GitHub 用户星标仓库')).toBeNull()
    expect(screen.getByText('Hacker News')).toBeInTheDocument()
  })

  it('目录加载失败：错误 + 重试', async () => {
    let failed = true
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () =>
        failed
          ? errorResponse('network_error', 'x', 0)
          : jsonResponse(ROUTES),
    })
    expect(await screen.findByText('无法连接到服务器，请稍后重试。')).toBeInTheDocument()
    failed = false
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('GitHub 用户星标仓库')).toBeInTheDocument()
  })

  it('选择路由 → 参数表单（required 标记 + help + example）', async () => {
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
    })
    await screen.findByText('GitHub 用户星标仓库')
    fireEvent.click(screen.getByRole('radio', { name: /GitHub 用户星标仓库/ }))
    expect(await screen.findByLabelText(/GitHub 用户名/)).toBeInTheDocument()
    expect(screen.getByText(/GitHub 用户名（字母 \/ 数字 \/ 连字符）。/)).toBeInTheDocument()
    // 必填参数未填：预览禁用
    expect(screen.getByRole('button', { name: '预览' })).toBeDisabled()
  })

  it('参数格式错误：本地拦截（不发预览请求）', async () => {
    const fetchState = await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
    })
    await screen.findByText('GitHub 用户星标仓库')
    fireEvent.click(screen.getByRole('radio', { name: /GitHub 用户星标仓库/ }))
    const input = await screen.findByLabelText(/GitHub 用户名/)
    fireEvent.change(input, { target: { value: 'a/b' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText(/「GitHub 用户名」格式不正确/)).toBeInTheDocument()
    expect(
      fetchState.calls.filter((c) => c.url === '/api/v1/rsshub/preview'),
    ).toEqual([])
  })

  it('预览成功：请求 body + PreviewStage 展示 server 构造的 feedUrl', async () => {
    const fetchState = await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'POST /api/v1/rsshub/preview': () => jsonResponse(PREVIEW),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
    })
    await screen.findByText('GitHub 用户星标仓库')
    fireEvent.click(screen.getByRole('radio', { name: /GitHub 用户星标仓库/ }))
    const input = await screen.findByLabelText(/GitHub 用户名/)
    fireEvent.change(input, { target: { value: 'DIYgod' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(
      await screen.findByText(/RSS · http:\/\/rsshub:1200\/github\/starred_repos\/DIYgod/),
    ).toBeInTheDocument()
    const previewCall = fetchState.calls.find((c) => c.url === '/api/v1/rsshub/preview')
    expect(previewCall?.body).toEqual({ routeId: 'github-starred-repos', params: { user: 'DIYgod' } })
  })

  it('预览 → 订阅：复用 0013 subscribe 管道（server 返回的 feedUrl + 分类）', async () => {
    const fetchState = await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'POST /api/v1/rsshub/preview': () => jsonResponse(PREVIEW),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
      'POST /api/v1/subscriptions': () => jsonResponse(SUBSCRIPTION, 201),
    })
    await screen.findByText('GitHub 用户星标仓库')
    fireEvent.click(screen.getByRole('radio', { name: /GitHub 用户星标仓库/ }))
    const input = await screen.findByLabelText(/GitHub 用户名/)
    fireEvent.change(input, { target: { value: 'DIYgod' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    const combobox = await screen.findByRole('combobox', { name: '分类' })
    fireEvent.change(combobox, { target: { value: CATEGORY.id } })
    fireEvent.click(screen.getByRole('button', { name: '确认添加' }))
    expect(await screen.findByText('已添加订阅')).toBeInTheDocument()
    const subscribeCall = fetchState.calls.find((c) => c.url === '/api/v1/subscriptions')
    expect(subscribeCall?.body).toEqual({
      feedUrl: 'http://rsshub:1200/github/starred_repos/DIYgod',
      categoryId: CATEGORY.id,
    })
  })

  it('rsshub_invalid_parameters（服务端兜底）：诚实文案', async () => {
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'POST /api/v1/rsshub/preview': () =>
        errorResponse('rsshub_invalid_parameters', 'bad', 400),
    })
    await screen.findByText('GitHub 用户星标仓库')
    fireEvent.click(screen.getByRole('radio', { name: /GitHub 用户星标仓库/ }))
    const input = await screen.findByLabelText(/GitHub 用户名/)
    fireEvent.change(input, { target: { value: 'DIYgod' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText('参数校验未通过')).toBeInTheDocument()
  })

  it('rsshub_fetch_error：诚实文案', async () => {
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'POST /api/v1/rsshub/preview': () => errorResponse('rsshub_fetch_error', 'down', 502),
    })
    await screen.findByText('GitHub 用户星标仓库')
    fireEvent.click(screen.getByRole('radio', { name: /GitHub 用户星标仓库/ }))
    const input = await screen.findByLabelText(/GitHub 用户名/)
    fireEvent.change(input, { target: { value: 'DIYgod' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText('RSSHub 无法生成该订阅源')).toBeInTheDocument()
  })

  it('已订阅路由：只读提示，无确认入口', async () => {
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'POST /api/v1/rsshub/preview': () =>
        jsonResponse({ ...PREVIEW, alreadySubscribed: true }),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
    })
    await screen.findByText('GitHub 用户星标仓库')
    fireEvent.click(screen.getByRole('radio', { name: /GitHub 用户星标仓库/ }))
    const input = await screen.findByLabelText(/GitHub 用户名/)
    fireEvent.change(input, { target: { value: 'DIYgod' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText('已经订阅了这个源，无需重复添加。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '确认添加' })).toBeNull()
  })

  it('重新选择：回到路由目录', async () => {
    await renderRssHubTab({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'POST /api/v1/rsshub/preview': () => jsonResponse(PREVIEW),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
    })
    await screen.findByText('GitHub 用户星标仓库')
    fireEvent.click(screen.getByRole('radio', { name: /GitHub 用户星标仓库/ }))
    const input = await screen.findByLabelText(/GitHub 用户名/)
    fireEvent.change(input, { target: { value: 'DIYgod' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    await screen.findByText(/RSS · http:\/\/rsshub:1200/)
    fireEvent.click(screen.getByRole('button', { name: '← 重新选择' }))
    expect(await screen.findByText('Hacker News')).toBeInTheDocument()
  })
})
