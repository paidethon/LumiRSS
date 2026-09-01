/** Gate 2 测试 — 0013 AddSubscriptionDialog（直接 RSS/Atom 预览 + 添加订阅）。
 *
 * 覆盖：预览成功展示真实 metadata、not_a_feed 诚实提示（不做自动发现）、
 * invalid URL 本地提示、已订阅提示、订阅成功 + feeds/categories invalidate、
 * 重复订阅 409、网络错误、双击防重（isPending 禁用）、Escape 关闭、
 * 还焦、direct-feed-url 纯函数。fetch 全部 mock，无真实网络。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import AddSubscriptionDialog from '../components/AddSubscriptionDialog'
import SubscriptionsPage from '../components/pages/SubscriptionsPage'
import { isDirectFeedUrl } from '../lib/direct-feed-url'
import { useReaderUi } from '../store/reader-ui'

const FEED_URL = 'https://example.com/feed.xml'
const CATEGORY = { id: 'user/-/label/Tech', label: 'Tech' }

const PREVIEW = {
  title: 'Example Feed',
  feedUrl: FEED_URL,
  siteUrl: 'https://example.com/',
  description: 'A feed about examples',
  format: 'rss' as const,
  alreadySubscribed: false,
}

const SUBSCRIPTION = {
  subscriptionRef: 's1.ZmVlZC85',
  title: 'Example Feed',
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

function renderDialog(
  map: Record<string, () => Response> = {
    'POST /api/v1/feed-preview': () => jsonResponse(PREVIEW),
    'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
  },
) {
  const fetchState = makeFetchHandler(map)
  vi.stubGlobal('fetch', fetchState.fn)
  render(withProviders(<AddSubscriptionDialog open onClose={() => {}} />))
  return fetchState
}

async function previewUrl(url: string) {
  const input = screen.getByLabelText('RSS / Atom 地址')
  fireEvent.change(input, { target: { value: url } })
  fireEvent.click(screen.getByRole('button', { name: '预览' }))
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({ section: 'subscriptions', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('direct-feed-url 纯函数', () => {
  it('接受绝对 http/https URL', () => {
    expect(isDirectFeedUrl('https://example.com/feed.xml')).toBe(true)
    expect(isDirectFeedUrl('http://example.com/rss')).toBe(true)
  })

  it('拒绝非 http(s) / 相对地址 / 空值 / 超长', () => {
    for (const value of [
      'javascript:alert(1)',
      'ftp://example.com/feed',
      'example.com/feed.xml',
      '/feed.xml',
      '   ',
      `https://example.com/${'x'.repeat(3000)}`,
    ]) {
      expect(isDirectFeedUrl(value)).toBe(false)
    }
  })
})

describe('AddSubscriptionDialog — 预览', () => {
  it('预览成功：展示真实 metadata（标题 / 格式 / URL / 描述 / 分类下拉）', async () => {
    renderDialog()
    await previewUrl(FEED_URL)
    expect(await screen.findByText('Example Feed')).toBeInTheDocument()
    expect(screen.getByText(/RSS · https:\/\/example\.com\/feed\.xml/)).toBeInTheDocument()
    expect(screen.getByText('A feed about examples')).toBeInTheDocument()
    // 真实分类出现在下拉中
    expect(screen.getByRole('combobox', { name: '分类' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Tech' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '默认分类（不指定）' })).toBeInTheDocument()
  })

  it('普通网页 URL：本地诚实提示（不发预览请求，不做自动发现）', () => {
    const fetchState = makeFetchHandler({
      'GET /api/v1/categories': () => jsonResponse([]),
    })
    vi.stubGlobal('fetch', fetchState.fn)
    render(withProviders(<AddSubscriptionDialog open onClose={() => {}} />))
    const input = screen.getByLabelText('RSS / Atom 地址')
    fireEvent.change(input, { target: { value: 'example.com' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(
      screen.getByText('当前请填写直接 RSS / Atom 地址；网站来源发现属于后续 Source Discovery。'),
    ).toBeInTheDocument()
    // 无任何预览请求（本地拦截，不发 feed-preview）
    expect(
      fetchState.calls.filter((c) => c.url === '/api/v1/feed-preview'),
    ).toEqual([])
  })

  it('not_a_feed：诚实提示不冒充发现能力', async () => {
    renderDialog({
      'POST /api/v1/feed-preview': () =>
        errorResponse('not_a_feed', 'not a feed', 400),
    })
    await previewUrl(FEED_URL)
    expect(await screen.findByText('这不是有效的 RSS / Atom 地址')).toBeInTheDocument()
    expect(
      screen.getByText('当前请填写直接 RSS / Atom 地址；网站来源发现属于后续 Source Discovery。'),
    ).toBeInTheDocument()
  })

  it('timeout / 网络错误：错误状态 + 可重试', async () => {
    let failed = true
    renderDialog({
      'POST /api/v1/feed-preview': () =>
        failed
          ? errorResponse('feed_fetch_error', 'timeout', 502)
          : jsonResponse(PREVIEW),
    })
    await previewUrl(FEED_URL)
    expect(await screen.findByText('无法获取该地址')).toBeInTheDocument()
    failed = false
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText('Example Feed')).toBeInTheDocument()
  })

  it('unsafe URL：BFF 拒绝后展示提示', async () => {
    renderDialog({
      'POST /api/v1/feed-preview': () =>
        errorResponse('unsafe_feed_url', 'private', 400),
    })
    await previewUrl('http://127.0.0.1/feed.xml')
    expect(await screen.findByText('该地址不允许访问')).toBeInTheDocument()
  })
})

describe('AddSubscriptionDialog — 订阅', () => {
  it('成功闭环：确认 → subscribe(带分类) → 成功提示；重复提交被禁用', async () => {
    const fetchState = renderDialog({
      'POST /api/v1/feed-preview': () => jsonResponse(PREVIEW),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
      'POST /api/v1/subscriptions': () => jsonResponse(SUBSCRIPTION, 201),
    })
    await previewUrl(FEED_URL)
    await screen.findByText('Example Feed')
    // 选择真实分类
    fireEvent.change(screen.getByRole('combobox', { name: '分类' }), {
      target: { value: CATEGORY.id },
    })
    const confirm = screen.getByRole('button', { name: '确认添加' })
    fireEvent.click(confirm)
    expect(await screen.findByText('已添加订阅')).toBeInTheDocument()
    // subscribe 收到 preview 的 feedUrl + 所选分类
    const subscribeCall = fetchState.calls.find((c) => c.url === '/api/v1/subscriptions')
    expect(subscribeCall).toBeDefined()
    expect(subscribeCall?.body).toEqual({ feedUrl: FEED_URL, categoryId: CATEGORY.id })
    // 成功后只提供「完成」；不存在再次提交入口
    expect(screen.queryByRole('button', { name: '确认添加' })).toBeNull()
  })

  it('预览已订阅：提示重复且禁用确认', async () => {
    renderDialog({
      'POST /api/v1/feed-preview': () =>
        jsonResponse({ ...PREVIEW, alreadySubscribed: true }),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
    })
    await previewUrl(FEED_URL)
    expect(await screen.findByText('已经订阅了这个源，无需重复添加。')).toBeInTheDocument()
    const confirm = screen.getByRole('button', { name: '确认添加' })
    expect(confirm).toBeDisabled()
  })

  it('订阅 409（重复订阅）：显示冲突错误', async () => {
    renderDialog({
      'POST /api/v1/feed-preview': () => jsonResponse(PREVIEW),
      'GET /api/v1/categories': () => jsonResponse([CATEGORY]),
      'POST /api/v1/subscriptions': () =>
        errorResponse('subscription_conflict', 'Already subscribed.', 409),
    })
    await previewUrl(FEED_URL)
    await screen.findByText('Example Feed')
    fireEvent.click(screen.getByRole('button', { name: '确认添加' }))
    expect(await screen.findByText('已经订阅了这个源，无需重复添加。')).toBeInTheDocument()
  })

  it('订阅成功后 invalidate subscriptions：新 feed 出现在订阅页', async () => {
    const existing = [
      {
        subscriptionRef: 's1.ZmVlZC9s',
        title: 'Existing',
        feedUrl: 'https://old.example/rss',
        category: null,
      },
    ]
    const newSubscription = {
      subscriptionRef: 's1.ZmVlZDky',
      title: 'Example Feed',
      feedUrl: FEED_URL,
      category: null,
    }
    let subscribedNow = false
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (url === '/api/v1/feed-preview') return jsonResponse(PREVIEW)
        if (url === '/api/v1/categories') return jsonResponse([CATEGORY])
        if (method === 'POST' && url === '/api/v1/subscriptions') {
          subscribedNow = true
          return jsonResponse(SUBSCRIPTION, 201)
        }
        if (method === 'GET' && url === '/api/v1/subscriptions') {
          return jsonResponse(
            subscribedNow ? [...existing, newSubscription] : existing,
          )
        }
        throw new Error(`unexpected fetch: ${method} ${url}`)
      }),
    )
    render(
      withProviders(
        <>
          <SubscriptionsPage />
          <AddSubscriptionDialog open onClose={() => {}} />
        </>,
      ),
    )
    expect(await screen.findByText('Existing')).toBeInTheDocument()
    await previewUrl(FEED_URL)
    await screen.findByText('Example Feed')
    fireEvent.click(screen.getByRole('button', { name: '确认添加' }))
    // invalidate → refetch → 新 feed 出现在订阅页列表
    await waitFor(() => {
      const rows = screen.getAllByText('Example Feed')
      expect(rows.length).toBeGreaterThanOrEqual(2) // 预览卡片 + 列表行
    })
  })
})

describe('AddSubscriptionDialog — a11y / 交互', () => {
  it('Escape 关闭 + 焦点还回 trigger', async () => {
    const onClose = vi.fn()
    const fetchState = makeFetchHandler({
      'GET /api/v1/categories': () => jsonResponse([]),
    })
    vi.stubGlobal('fetch', fetchState.fn)
    function Harness() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button type="button" data-testid="trigger" onClick={() => setOpen(true)}>
            trigger
          </button>
          <AddSubscriptionDialog
            open={open}
            onClose={() => {
              onClose()
              setOpen(false)
            }}
          />
        </>
      )
    }
    render(withProviders(<Harness />))
    // 打开前焦点在 trigger（真实用户路径：点击入口按钮）
    const trigger = screen.getByTestId('trigger')
    trigger.focus()
    fireEvent.click(trigger)
    // Dialog 初始焦点：第一个可聚焦元素（输入框）
    const input = await screen.findByLabelText('RSS / Atom 地址')
    await waitFor(() => {
      expect(document.activeElement).toBe(input)
    })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    // dialog 卸载后还焦回打开前焦点（trigger）
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger)
    })
  })

  it('空 URL：预览按钮禁用（不空发请求）', () => {
    renderDialog()
    expect(screen.getByRole('button', { name: '预览' })).toBeDisabled()
  })

  it('双击防重：预览 pending 时按钮禁用', async () => {
    let resolvePreview: (value: Response) => void = () => {}
    const deferred = new Promise<Response>((resolve) => {
      resolvePreview = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        // 只挂起预览请求；categories 用独立响应（Response body 只能读一次）
        if (String(input) === '/api/v1/feed-preview') {
          return deferred
        }
        return Promise.resolve(jsonResponse([]))
      }),
    )
    render(withProviders(<AddSubscriptionDialog open onClose={() => {}} />))
    fireEvent.change(screen.getByLabelText('RSS / Atom 地址'), {
      target: { value: FEED_URL },
    })
    const previewButton = screen.getByRole('button', { name: '预览' })
    fireEvent.click(previewButton)
    const pendingButton = await screen.findByRole('button', { name: /预览中/ })
    expect(pendingButton).toBeDisabled()
    resolvePreview(jsonResponse(PREVIEW))
    await screen.findByText('Example Feed')
  })
})
