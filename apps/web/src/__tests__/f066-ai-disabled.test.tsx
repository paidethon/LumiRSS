/** F066 UI — 来源设置对话框的「AI 使用范围」开关：
 * - 开关反映服务端 aiDisabled 状态；保存 → PUT 载荷携带 aiDisabled；
 * - 说明文案列出禁用后的诚实后果（403 / 派生保留不再更新 / 索引移除）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SourcePolicyDialog } from '../components/subscription-w3-panels'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderDialog(feedUrl = 'https://a.example/rss') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <SourcePolicyDialog open onClose={() => {}} feedUrl={feedUrl} title="示例源" />
    </QueryClientProvider>,
  )
}

function stubOverrides(items: unknown[]) {
  return vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (method === 'GET' && url === '/api/v1/sources/overrides') {
      return Promise.resolve(jsonResponse({ items }))
    }
    if (method === 'PUT' && url === '/api/v1/sources/overrides') {
      return Promise.resolve(
        jsonResponse({
          feedUrl: 'https://a.example/rss',
          hiddenUntil: null,
          showFrom: null,
          staleAlertHours: null,
          extractPolicy: 'rss',
          readerStyle: null,
          aiDisabled: true,
          updatedAt: '2026-09-19T00:00:00Z',
        }),
      )
    }
    return Promise.resolve(jsonResponse({}))
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F066 来源 AI 使用范围开关', () => {
  it('F066: 默认允许 → 打开开关保存 → PUT 载荷携带 aiDisabled:true 与说明文案', async () => {
    const fetchMock = stubOverrides([
      {
        feedUrl: 'https://a.example/rss',
        hiddenUntil: null,
        showFrom: null,
        staleAlertHours: null,
        extractPolicy: 'rss',
        readerStyle: null,
        aiDisabled: false,
        updatedAt: '2026-09-01T00:00:00Z',
      },
    ])
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    // 说明文案（诚实后果）
    expect(await screen.findByText(/摘要\/译文\/对话返回 403/)).toBeInTheDocument()


    // 等服务端覆盖到达（effect 会以服务端值同步开关初始态）
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]) === '/api/v1/sources/overrides')).toBe(true)
    })
    // 打开开关并保存
    const toggle = screen.getByRole('switch', { name: '禁用该来源的 AI' })
    expect(toggle).not.toBeChecked()
    fireEvent.click(toggle)
    expect(screen.getByTestId('ai-scope-status').textContent).toBe('已禁用')
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/sources/overrides',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
    const call = fetchMock.mock.calls.find((c) => (c[1] as RequestInit)?.method === 'PUT')
    const body = JSON.parse((call?.[1] as RequestInit).body as string)
    expect(body.aiDisabled).toBe(true)
    expect(body.feedUrl).toBe('https://a.example/rss')
  })

  it('F066: 服务端已禁用 → 开关初始为开（诚实反映）', async () => {
    vi.stubGlobal(
      'fetch',
      stubOverrides([
        {
          feedUrl: 'https://a.example/rss',
          hiddenUntil: null,
          showFrom: null,
          staleAlertHours: null,
          extractPolicy: 'rss',
          readerStyle: null,
          aiDisabled: true,
          updatedAt: '2026-09-01T00:00:00Z',
        },
      ]),
    )
    renderDialog()
    await screen.findByText(/摘要\/译文\/对话返回 403/)
    await waitFor(() => {
      expect(screen.getByTestId('ai-scope-status').textContent).toBe('已禁用')
    })
    expect(screen.getByRole('switch', { name: '禁用该来源的 AI' })).toBeChecked()
  })
})
