/** F064 UI — AI 用量限制卡片：窗口/上限保存（PUT settings/ai 只带配额
 * 字段）、当前窗口已用/剩余诚实展示、未配置时不显示已用（不编造）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AiQuotaCard } from '../components/settings/AiQuotaCard'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const USAGE = {
  window: 'day',
  maxCalls: 50,
  used: 37,
  remaining: 13,
  windowStart: '2026-09-19T00:00:00+08:00',
  windowReset: '2026-09-20T00:00:00+08:00',
  retryAfter: 3600,
}

function renderCard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AiQuotaCard />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F064 用量限制卡片', () => {
  it('F064: 展示已用/剩余/重置时间；修改窗口+上限保存 → PUT 携带配额字段', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'PUT') {
          return Promise.resolve(jsonResponse({ quotaWindow: 'month', quotaMaxCalls: 200 }))
        }
        return Promise.resolve(jsonResponse(USAGE))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderCard()

    // 诚实展示当前窗口用量
    expect(await screen.findByText(/已用 37 \/ 上限 50/)).toBeInTheDocument()
    expect(screen.getByText(/剩余 13/)).toBeInTheDocument()

    // 修改为每月 200 → 保存
    fireEvent.change(screen.getByLabelText('计数窗口'), { target: { value: 'month' } })
    fireEvent.change(screen.getByLabelText('请求上限'), { target: { value: '200' } })
    fireEvent.click(screen.getByRole('button', { name: '保存用量限制' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/settings/ai',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
    const body = JSON.parse((fetchMock.mock.calls.find((c) => (c[1] as RequestInit)?.method === 'PUT')?.[1] as RequestInit).body as string)
    expect(body.quotaWindow).toBe('month')
    expect(body.quotaMaxCalls).toBe(200)
    expect(await screen.findByText('已保存，立即生效。')).toBeInTheDocument()
  })

  it('F064: 未配置（不限）→ 显示不拦截说明，不显示已用；上限输入禁用', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          jsonResponse({
            window: '',
            maxCalls: 0,
            used: 0,
            remaining: 0,
            windowStart: '',
            windowReset: '',
            retryAfter: 0,
          }),
        ),
      ),
    )
    renderCard()
    expect(await screen.findByText(/未配置限制，不拦截 AI 请求/)).toBeInTheDocument()
    expect(screen.queryByText(/已用/)).toBeNull()
    expect((screen.getByLabelText('请求上限') as HTMLInputElement).disabled).toBe(true)
  })
})
