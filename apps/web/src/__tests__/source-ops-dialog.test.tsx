/** NEW-201..210 来源运维工作台 —— 入口渲染 + 停机计划/阅读日历真流程。

 * 共享装配纪律下 SubscriptionsPage 只挂入口按钮；本套件直接渲染
 * SourceOpsDialog（QueryProvider + stub fetch），验证：
 * - 10 个页签可达（入口渲染契约）；
 * - 停机计划面板：列表行渲染 + 取消计划走真实 DELETE 语义（POST cancel）；
 * - 阅读日历面板：月份查询 → 按日分桶 + 条目可点击（onOpenEntry 契约）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SourceOpsDialog } from '../components/new201/SourceOpsDialog'

let cancelRequested = false
const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (url.includes('/new210/pauses') && method === 'GET') {
    const cancelled = cancelRequested // 取消后的重取：状态已翻转
    return Promise.resolve(
      new Response(
        JSON.stringify({
          items: [
            {
              id: 'p1',
              feedUrl: 'https://example.com/feed.xml',
              reason: '站点维护',
              startAt: '2026-09-28T00:00:00Z',
              endAt: '2026-10-01T00:00:00Z',
              status: cancelled ? 'cancelled' : 'active',
              activeNow: !cancelled,
            },
          ],
          note: '诚实边界说明',
        }),
        { status: 200 },
      ),
    )
  }
  if (url.includes('/new210/pauses/p1/cancel') && method === 'POST') {
    cancelRequested = true
    return Promise.resolve(
      new Response(
        JSON.stringify({
          id: 'p1',
          feedUrl: 'https://example.com/feed.xml',
          reason: null,
          startAt: '2026-09-28T00:00:00Z',
          endAt: '2026-10-01T00:00:00Z',
          status: 'cancelled',
          cancelledAt: '2026-09-28T01:00:00Z',
          createdAt: '2026-09-28T00:00:00Z',
          activeNow: false,
        }),
        { status: 200 },
      ),
    )
  }
  if (url.includes('/new206/calendar')) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          feedUrl: 'https://cal.example/rss',
          month: '2026-09',
          days: [
            {
              date: '2026-09-03',
              count: 2,
              sample: [
                { entryRef: 'rss:e1.a', title: '九月文章甲', publishedAt: '2026-09-03T08:00:00Z' },
                { entryRef: 'rss:e1.b', title: '九月文章乙', publishedAt: '2026-09-03T12:00:00Z' },
              ],
            },
          ],
          totalEntries: 2,
          coverage: 'projection',
          outOfWindowRows: 0,
          fetchPaused: false,
          basis: 'projection',
          note: '日历口径说明',
        }),
        { status: 200 },
      ),
    )
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderDialog() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <SourceOpsDialog open onClose={() => {}} initialTab="pause" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockClear()
  cancelRequested = false
  vi.stubGlobal('fetch', fetchMock)
})

describe('NEW-201..210 来源运维工作台', () => {
  it('入口渲染：10 个能力页签可达（含默认停机计划面板）', async () => {
    renderDialog()
    expect(screen.getByRole('dialog', { name: '来源运维工作台' })).toBeInTheDocument()
    for (const label of ['停机计划', '停更观察', '回收箱', '分流视图', '阅读日历', '保留策略', '接管向导', '镜像比对', 'RSSHub 表单', '认证到期']) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument()
    }
    expect(await screen.findByText('https://example.com/feed.xml')).toBeInTheDocument()
    expect(screen.getByText('暂停中')).toBeInTheDocument()
  })

  it('停机计划：取消计划走真实取消端点并刷新列表状态', async () => {
    renderDialog()
    const cancel = await screen.findByRole('button', { name: '取消计划' })
    fireEvent.click(cancel)
    await waitFor(() => expect(screen.getByText('已取消')).toBeInTheDocument())
    const cancelCall = fetchMock.mock.calls.find(
      ([input, init]) => String(input).includes('/new210/pauses/p1/cancel') && (init as RequestInit | undefined)?.method === 'POST',
    )
    expect(cancelCall).toBeTruthy()
  })

  it('阅读日历：月份查询按日分桶，条目点击经 reader-ui 打开当日文章', async () => {
    const { useReaderUi } = await import('../store/reader-ui')
    const selectEntry = vi.fn()
    const selectScope = vi.fn()
    useReaderUi.setState({ selectEntry, selectScope })
    renderDialog()
    fireEvent.click(screen.getByRole('tab', { name: '阅读日历' }))
    fireEvent.change(screen.getByLabelText('来源 feed URL'), { target: { value: 'https://cal.example/rss' } })
    fireEvent.click(screen.getByRole('button', { name: '查看月历' }))
    expect(await screen.findByText('2026-09-03（2 条）')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '九月文章甲' }))
    expect(selectEntry).toHaveBeenCalledWith('rss:e1.a')
    const calCall = fetchMock.mock.calls.find(([input]) => String(input).includes('/new206/calendar'))
    expect(String(calCall?.[0])).toContain('month=2026-09')
  })
})
