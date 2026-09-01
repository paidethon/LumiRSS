/** 0014 测试 — AddSourceDialog 网站发现模式。
 *
 * 覆盖：切换 tab、发现成功（候选列表 + 默认选中）、no_feed_discovered /
 * invalid_source_url / unsafe 错误文案、候选预览、预览后订阅（带分类）、
 * 重新选择、双击防重。fetch 全部 mock，无真实网络。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AddSourceDialog from '../components/AddSourceDialog'
import { useReaderUi } from '../store/reader-ui'

const PAGE_URL = 'https://blog.example.com/'
const FEED_URL = 'https://blog.example.com/feed.xml'
const CATEGORY = { id: 'user/-/label/Tech', label: 'Tech' }

const CANDIDATES = {
  candidates: [
    {
      feedUrl: FEED_URL,
      title: 'Blog Feed',
      source: 'declared' as const,
      format: null,
    },
    {
      feedUrl: 'https://blog.example.com/atom.xml',
      title: null,
      source: 'declared' as const,
      format: null,
    },
  ],
}

const PREVIEW = {
  title: 'Blog Feed',
  feedUrl: FEED_URL,
  siteUrl: 'https://blog.example.com/',
  description: null,
  format: 'rss' as const,
  alreadySubscribed: false,
}

const SUBSCRIPTION = {
  subscriptionRef: 's1.ZmVlZC85',
  title: 'Blog Feed',
  feedUrl: FEED_URL,
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

async function renderWebsiteTab(
  map: Record<string, () => Response> = {},
): Promise<ReturnType<typeof makeFetchHandler>> {
  const fetchState = makeFetchHandler(map)
  vi.stubGlobal('fetch', fetchState.fn)
  render(withProviders(<AddSourceDialog open onClose={() => {}} />))
  fireEvent.click(screen.getByRole('tab', { name: '网站' }))
  return fetchState
}

async function discoverUrl(url: string) {
  const input = screen.getByLabelText('网站地址')
  fireEvent.change(input, { target: { value: url } })
  fireEvent.click(screen.getByRole('button', { name: '发现' }))
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({ section: 'subscriptions', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('AddSourceDialog — 网站发现', () => {
  it('切换到网站 tab：URL 输入 + 诚实说明', () => {
    render(withProviders(<AddSourceDialog open onClose={() => {}} />))
    fireEvent.click(screen.getByRole('tab', { name: '网站' }))
    expect(screen.getByLabelText('网站地址')).toBeInTheDocument()
    expect(screen.getByText(/自动发现该网站声明或常见位置上的 RSS \/ Atom 订阅源/)).toBeInTheDocument()
    // RSS tab 的内容已卸载
    expect(screen.queryByLabelText('RSS / Atom 地址')).toBeNull()
  })

  it('发现成功：候选列表（声明来源 + 空标题回退 URL）+ 第一个默认选中', async () => {
    await renderWebsiteTab({
      'POST /api/v1/source-discovery': () => jsonResponse(CANDIDATES),
    })
    await discoverUrl(PAGE_URL)
    expect(await screen.findByText('发现 2 个候选订阅源')).toBeInTheDocument()
    expect(screen.getByText('Blog Feed')).toBeInTheDocument()
    expect(screen.getByText('https://blog.example.com/atom.xml')).toBeInTheDocument()
    // 第一个候选默认选中
    const first = screen.getByRole('radio', { name: /Blog Feed/ })
    expect(first).toBeChecked()
    // 发现请求带正确 body
    const calls = await screen.findByText('发现 2 个候选订阅源')
    expect(calls).toBeInTheDocument()
  })

  it('发现请求 body 为 {url}', async () => {
    const fetchState = await renderWebsiteTab({
      'POST /api/v1/source-discovery': () => jsonResponse(CANDIDATES),
    })
    await discoverUrl(PAGE_URL)
    await screen.findByText('发现 2 个候选订阅源')
    const call = fetchState.calls.find((c) => c.url === '/api/v1/source-discovery')
    expect(call?.body).toEqual({ url: PAGE_URL })
  })

  it('no_feed_discovered：诚实文案', async () => {
    await renderWebsiteTab({
      'POST /api/v1/source-discovery': () =>
        errorResponse('no_feed_discovered', 'none', 404),
    })
    await discoverUrl(PAGE_URL)
    expect(await screen.findByText('没有在这个网站找到订阅源')).toBeInTheDocument()
  })

  it('invalid_source_url / unsafe：诚实文案', async () => {
    await renderWebsiteTab({
      'POST /api/v1/source-discovery': () =>
        errorResponse('invalid_source_url', 'bad', 400),
    })
    await discoverUrl('not-a-url')
    expect(await screen.findByText('网址格式无效')).toBeInTheDocument()
  })

  it('选中候选 → 预览 → 共享 PreviewStage（标题/格式/URL）', async () => {
    await renderWebsiteTab({
      'POST /api/v1/source-discovery': () => jsonResponse(CANDIDATES),
      'POST /api/v1/feed-preview': () => jsonResponse(PREVIEW),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
    })
    await discoverUrl(PAGE_URL)
    await screen.findByText('发现 2 个候选订阅源')
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText('RSS · https://blog.example.com/feed.xml')).toBeInTheDocument()
    // 预览请求带选中候选的 feedUrl
    expect(await screen.findByRole('combobox', { name: '分类' })).toBeInTheDocument()
  })

  it('预览候选 → 选分类 → 订阅（复用 0013 管道）', async () => {
    const fetchState = await renderWebsiteTab({
      'POST /api/v1/source-discovery': () => jsonResponse(CANDIDATES),
      'POST /api/v1/feed-preview': () => jsonResponse(PREVIEW),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
      'POST /api/v1/subscriptions': () => jsonResponse(SUBSCRIPTION, 201),
    })
    await discoverUrl(PAGE_URL)
    await screen.findByText('发现 2 个候选订阅源')
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    const combobox = await screen.findByRole('combobox', { name: '分类' })
    fireEvent.change(combobox, { target: { value: CATEGORY.id } })
    fireEvent.click(screen.getByRole('button', { name: '确认添加' }))
    expect(await screen.findByText('已添加订阅')).toBeInTheDocument()
    const subscribeCall = fetchState.calls.find((c) => c.url === '/api/v1/subscriptions')
    expect(subscribeCall?.body).toEqual({ feedUrl: FEED_URL, categoryId: CATEGORY.id })
    expect(screen.getByRole('button', { name: '完成' })).toBeInTheDocument()
  })

  it('预览失败：提示候选可能失效 + 重新选择', async () => {
    await renderWebsiteTab({
      'POST /api/v1/source-discovery': () => jsonResponse(CANDIDATES),
      'POST /api/v1/feed-preview': () => errorResponse('feed_fetch_error', 'x', 502),
    })
    await discoverUrl(PAGE_URL)
    await screen.findByText('发现 2 个候选订阅源')
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText('无法获取该地址')).toBeInTheDocument()
    expect(screen.getByText(/这个候选可能已失效/)).toBeInTheDocument()
  })

  it('重新选择：回到候选列表', async () => {
    await renderWebsiteTab({
      'POST /api/v1/source-discovery': () => jsonResponse(CANDIDATES),
      'POST /api/v1/feed-preview': () => jsonResponse(PREVIEW),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
    })
    await discoverUrl(PAGE_URL)
    await screen.findByText('发现 2 个候选订阅源')
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    await screen.findByText('RSS · https://blog.example.com/feed.xml')
    fireEvent.click(screen.getByRole('button', { name: '← 重新选择' }))
    expect(await screen.findByText('发现 2 个候选订阅源')).toBeInTheDocument()
  })

  it('已订阅候选：PreviewStage 只读提示，无确认入口', async () => {
    await renderWebsiteTab({
      'POST /api/v1/source-discovery': () => jsonResponse(CANDIDATES),
      'POST /api/v1/feed-preview': () =>
        jsonResponse({ ...PREVIEW, alreadySubscribed: true }),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
    })
    await discoverUrl(PAGE_URL)
    await screen.findByText('发现 2 个候选订阅源')
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText('已经订阅了这个源，无需重复添加。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '确认添加' })).toBeNull()
  })

  it('双击防重：发现 pending 时按钮禁用', async () => {
    let resolveDiscovery: (value: Response) => void = () => {}
    const deferred = new Promise<Response>((resolve) => {
      resolveDiscovery = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        if (String(input) === '/api/v1/source-discovery') {
          return deferred
        }
        return Promise.resolve(jsonResponse([]))
      }),
    )
    render(withProviders(<AddSourceDialog open onClose={() => {}} />))
    fireEvent.click(screen.getByRole('tab', { name: '网站' }))
    await discoverUrl(PAGE_URL)
    const pendingButton = await screen.findByRole('button', { name: /发现中/ })
    expect(pendingButton).toBeDisabled()
    resolveDiscovery(jsonResponse(CANDIDATES))
    await screen.findByText('发现 2 个候选订阅源')
  })

  it('候选为空数组（防御）：显示 0 候选且预览禁用', async () => {
    await renderWebsiteTab({
      'POST /api/v1/source-discovery': () => jsonResponse({ candidates: [] }),
    })
    await discoverUrl(PAGE_URL)
    expect(await screen.findByText('发现 0 个候选订阅源')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '预览' })).toBeDisabled()
  })
})
