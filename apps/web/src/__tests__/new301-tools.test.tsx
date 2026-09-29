/** NEW-301..310 Web 工具台测试 — 情境展开零请求/来源选择器驱动来源
 * 级子面板/收件箱审阅主路径。fetch 按 URL 匹配 mock（服务真源在
 * BFF：services/bff/tests/test_new30*.py、test_new310*.py）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { New301IntakeTools } from '../components/new301/New301IntakeTools'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderTools(): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}><New301IntakeTools /></QueryClientProvider>)
}

const fetchCalls: { url: string; init?: RequestInit }[] = []
let routes: {
  match: (url: string) => boolean
  respond: () => Response
}[] = []

function mockRoute(match: (url: string) => boolean, body: unknown, status = 200): void {
  routes.push({ match, respond: () => jsonResponse(body, status) })
}

function expand(subsectionId: string): void {
  const toggles = screen
    .getAllByRole('button')
    .filter((button) => {
      const host = button.closest('[data-new271-subsection]')
      return (
        host !== null &&
        host.getAttribute('data-new271-subsection') === subsectionId
      )
    })
  expect(toggles.length).toBeGreaterThan(0)
  fireEvent.click(toggles[0])
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    fetchCalls.push({ url, init })
    for (const route of routes) {
      if (route.match(url)) return route.respond()
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch
  mockRoute(
    (url) => url.endsWith('/api-sources') && fetchCalls.length <= 2,
    { items: [{ uuid: 'src-1', name: '样例来源' }] },
  )
})

afterEach(() => {
  cleanup()
  routes = []
})

describe('NEW-301..310 接入工具台（New301IntakeTools）', () => {
  it('挂载即拉来源清单；子区折叠态不产生子面板请求', async () => {
    renderTools()
    await waitFor(() => {
      expect(
        fetchCalls.some((call) => call.url.endsWith('/api-sources')),
      ).toBe(true)
    })
    // 未展开任何子区：不应有子面板请求
    expect(
      fetchCalls.filter((call) => call.url.includes('mapping-samples')),
    ).toHaveLength(0)
  })

  it('NEW-301：展开映射编辑器 → 拉样本清单（GET mapping-samples）', async () => {
    routes.length = 0
    mockRoute(
      (url) => url.endsWith('/api-sources'),
      { items: [{ uuid: 'src-1', name: '样例来源' }] },
    )
    mockRoute(
      (url) => url.includes('/mapping-samples'),
      {
        items: [
          {
            id: 7,
            label: '已有样本',
            sampleJson: { items: [] },
            createdAt: 'now',
          },
        ],
      },
    )
    renderTools()
    expand('new301-mapping')
    await waitFor(() => {
      const pulled = fetchCalls.some(
        (call) => call.url.includes('/mapping-samples'),
      )
      expect(pulled).toBe(true)
    })
  })

  it('NEW-303：收件箱显示待确认条目并可拒绝', async () => {
    routes.length = 0
    mockRoute((url) => url.endsWith('/webhooks/endpoints'), { items: [] })
    mockRoute(
      (url) => url.includes('/webhooks/inbox'),
      {
        items: [
          {
            id: 5,
            endpointUuid: 'ep-1',
            eventId: 'evt-1:i1',
            title: '待审条目',
            summary: '摘要文本',
            status: 'pending',
            receivedAt: 'now',
            decidedAt: null,
          },
        ],
      },
    )
    renderTools()
    expand('new303-inbox')
    const rejectButton = await screen.findByRole('button', { name: '拒绝' })
    fireEvent.click(rejectButton)
    await waitFor(() => {
      expect(
        fetchCalls.some((call) => call.url.endsWith('/webhooks/inbox/5/reject')),
      ).toBe(true)
    })
  })
})
