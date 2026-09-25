/** F023/F024/F025/F026/F035/F037/F038 — 来源统计与工具抽屉。
 *
 * 订阅行菜单「统计与工具」→ 抽屉：
 * - 最近同步时间（投影口径，null → 诚实「未覆盖」）
 * - 近 30 天柱状图 + 日均/周均摘要
 * - 30 天热力格
 * - 复制 Feed 地址（剪贴板反馈）、来源主页外链、扫码二维码显隐
 * - 投影未覆盖的订阅 → 诚实空态（不冒充零）
 * fetch 全部 mock，无真实网络。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SubscriptionsPage from '../components/pages/SubscriptionsPage'
import { useReaderUi } from '../store/reader-ui'

const REF = 's1.ZmVlZC83'
const SUBSCRIPTION = {
  subscriptionRef: REF,
  title: 'Tech Feed',
  feedUrl: 'https://tech.example/rss',
  category: null,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const TODAY = new Date().toISOString().slice(0, 10)

function volumePayload(covered: boolean) {
  return {
    days: 30,
    since: '2026-08-26T00:00:00Z',
    basis: 'published_at（search_entries 派生投影，可重建）',
    generatedAt: '2026-09-25T00:00:00Z',
    items: [
      {
        feedUrl: 'https://tech.example/rss',
        title: 'Tech Feed',
        publishedCount: covered ? 5 : null,
        lastPublishedAt: covered ? `${TODAY}T08:00:00Z` : null,
        lastSyncedAt: covered ? `${TODAY}T09:00:00Z` : null,
        collectionTiming: null,
        daily: covered
          ? [
              { date: TODAY, count: 3 },
              { date: '2026-09-20', count: 2 },
            ]
          : null,
      },
    ],
  }
}

function renderPage(routes: Record<string, () => Response>) {
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const handler = routes[`${method} ${String(input)}`]
    if (handler === undefined) {
      // 未知路由：200 空对象，宁可宽松不误伤——断言仍锚定可见 UI。
      // eslint-disable-next-line no-console
      console.log('UNEXPECTED_FETCH', String(input))
      return jsonResponse({})
    }
    return handler()
  })
  vi.stubGlobal('fetch', fn)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <SubscriptionsPage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useReaderUi.setState({ scope: { kind: 'all' }, view: 'all' })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function openStats(volume: ReturnType<typeof volumePayload>) {
  renderPage({
    'GET /api/v1/subscriptions': () => jsonResponse([SUBSCRIPTION]),
    'GET /api/v1/categories': () => jsonResponse([]),
    'GET /api/v1/sources/aliases': () => jsonResponse({ items: [] }),
    'GET /api/v1/feeds': () => jsonResponse([]),
    'GET /api/v1/sources/volume?days=30&daily=true': () => jsonResponse(volume),
  })
  fireEvent.click(await screen.findByRole('button', { name: '「Tech Feed」的操作' }))
  fireEvent.click(await screen.findByRole('menuitem', { name: '统计与工具' }))
}

describe('SourceStatsDrawer', () => {
  it('投影覆盖：显示最近同步、30 天摘要与热力格、复制/主页/二维码', async () => {
    await openStats(volumePayload(true))

    expect(await screen.findByRole('dialog', { name: '「Tech Feed」统计与工具' })).toBeInTheDocument()
    // volume 查询异步解析——等图表出现再断言摘要
    expect(await screen.findByTestId('source-volume-chart')).toBeInTheDocument()
    expect(screen.getByTestId('source-volume-heatmap')).toBeInTheDocument()
    // F025 摘要：共 5 条（3+2），日均/周均保留 1 位
    expect(screen.getByText(/共 5 条/)).toBeInTheDocument()
    expect(screen.getByText(/日均 0\.2 条/)).toBeInTheDocument()
    // F023 最近同步为相对时间（今天 → 刚刚/分钟级文案不固定，断言存在 time 元素）
    expect(screen.getByText(/投影入库/)).toBeInTheDocument()

    // F037 复制（jsdom 无剪贴板——stub 后断言调用）
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    fireEvent.click(screen.getByRole('button', { name: /复制 Feed 地址/ }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('https://tech.example/rss'))
    expect(screen.getByText('已复制')).toBeInTheDocument()

    // F026 主页外链存在（jsdom 不真开窗口）
    expect(screen.getByRole('button', { name: /来源主页/ })).toBeInTheDocument()

    // F038 二维码显隐
    expect(screen.queryByTestId('source-feed-qr')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /扫码订阅/ }))
    expect(screen.getByTestId('source-feed-qr')).toBeInTheDocument()
  })

  it('投影未覆盖：诚实空态，不冒充零', async () => {
    await openStats(volumePayload(false))

    expect(await screen.findByText('暂无投影数据')).toBeInTheDocument()
    expect(screen.queryByTestId('source-volume-chart')).not.toBeInTheDocument()
  })

  it('统计加载失败：错误态 + 重试提示', async () => {
    renderPage({
      'GET /api/v1/subscriptions': () => jsonResponse([SUBSCRIPTION]),
      'GET /api/v1/categories': () => jsonResponse([]),
      'GET /api/v1/sources/aliases': () => jsonResponse({ items: [] }),
      'GET /api/v1/feeds': () => jsonResponse([]),
      'GET /api/v1/sources/volume?days=30&daily=true': () =>
        new Response(null, { status: 500 }),
    })
    fireEvent.click(await screen.findByRole('button', { name: '「Tech Feed」的操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '统计与工具' }))

    expect(await screen.findByText('统计加载失败')).toBeInTheDocument()
  })
})
