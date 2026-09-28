/** FIX-129 回归 — RSS 更新检查失败必须诚实呈现，不得伪装成「成功但
 * 暂无新文章」。
 *
 * 缺陷：来源刷新状态面板的「立即检查」经 mutateAsync 发
 * POST /subscriptions/health-check；请求失败（网络断开/5xx）时异常被
 * runCheck 吞掉（unhandled rejection），界面停留在旧状态/空态——
 * 「检查失败」与「检查成功、没有更新」不可区分。
 *
 * 修复契约：
 * - 失败 → 面板内 role=alert 的「检查失败 + 原因 + 重试」错误行；
 * - 成功 → 无错误行，刷新状态按服务端结果刷新（含"本次 0 条新文章"）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SourceRefreshStatusPanel from '../components/SourceRefreshStatusPanel'
import { useReaderUi } from '../store/reader-ui'

const SUBSCRIPTIONS = [
  { subscriptionRef: 's1', feedUrl: 'https://a.example.com/feed.xml', title: '示例源 A', category: null },
]

const STATUS_EMPTY = {
  feeds: [],
  checkedAt: '2026-09-28T00:00:00Z',
}

const STATUS_AFTER_OK = {
  feeds: [
    {
      feedUrl: 'https://a.example.com/feed.xml',
      lastChecked: '2026-09-28T01:00:00Z',
      lastResult: 'ok',
      pending: false,
      recoveryAvailable: false,
      recent: [{ checkedAt: '2026-09-28T01:00:00Z', result: 'ok', entryCount: 0 }],
    },
  ],
  checkedAt: '2026-09-28T01:00:00Z',
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SourceRefreshStatusPanel />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-129 — 检查失败与「暂无新文章」诚实区分', () => {
  it('health-check 失败（5xx）→ 显示「检查失败」错误行 + 重试；绝不伪装成空态成功', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.startsWith('/api/v1/subscriptions') && method === 'GET') return Promise.resolve(jsonResponse(SUBSCRIPTIONS))
      if (url.startsWith('/api/v1/sources/refresh-status')) return Promise.resolve(jsonResponse(STATUS_EMPTY))
      if (url === '/api/v1/subscriptions/health-check' && method === 'POST') {
        return Promise.resolve(jsonResponse({ error: { type: 'upstream_error', message: '上游检查失败' } }, 502))
      }
      return Promise.resolve(jsonResponse({ items: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    // 初始空态（还没有检查记录）正常显示。
    expect(await screen.findByText('还没有检查记录')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /立即检查/ }))

    // 失败必须以错误行诚实呈现（role=alert），而不是停留在空态。
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('检查失败')
    expect(screen.getByRole('button', { name: /重试/ })).toBeInTheDocument()
  })

  it('health-check 成功 → 无错误行；刷新状态按服务端结果更新（0 条新文章 ≠ 失败）', async () => {
    let healthy = false
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.startsWith('/api/v1/subscriptions') && method === 'GET') return Promise.resolve(jsonResponse(SUBSCRIPTIONS))
      if (url.startsWith('/api/v1/sources/refresh-status')) {
        return Promise.resolve(jsonResponse(healthy ? STATUS_AFTER_OK : STATUS_EMPTY))
      }
      if (url === '/api/v1/subscriptions/health-check' && method === 'POST') {
        healthy = true
        return Promise.resolve(jsonResponse({ items: [{ ref: 's1', status: 'ok', checkedAt: '2026-09-28T01:00:00Z' }] }))
      }
      return Promise.resolve(jsonResponse({ items: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    expect(await screen.findByText('还没有检查记录')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /立即检查/ }))

    // 成功：状态刷新为服务端结果；无「检查失败」告警。
    await waitFor(() => expect(screen.getByText('https://a.example.com/feed.xml')).toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
