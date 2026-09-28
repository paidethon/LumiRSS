/** FIX-281 — AI 用量上限输入：编辑态与提交态分离。
 *
 * 症状：value 直接绑定数字 state、onChange 立即 Math.max(0, Number(v))
 * ——输入暂态「-」（或「-5」）被当场强制置 0，清空被当场置 0；用户永远
 * 无法以「-」开头的中间态编辑。修复：输入框持有字符串草稿（编辑态），
 * 保存时才解析并夹紧（提交态），既有 0..10000 提交语义不变。
 */

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

describe('FIX-281 用量上限输入：编辑态与提交态分离', () => {
  it('编辑态：清空与暂态负号不被当场置 0；提交态：保存时才夹紧到 0..10000', async () => {
    const putBodies: unknown[] = []
    const fetchMock = vi
      .fn()
      .mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'PUT') {
          putBodies.push(JSON.parse(String(init?.body)))
          return Promise.resolve(jsonResponse({ quotaWindow: 'day', quotaMaxCalls: 0 }))
        }
        return Promise.resolve(jsonResponse(USAGE))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderCard()

    const input = await screen.findByLabelText('请求上限')
    await waitFor(() => expect(input).toHaveValue(50))

    // 编辑态：清空 → 保持空（不被当场置 0）
    fireEvent.change(input, { target: { value: '' } })
    expect(input).toHaveValue(null)

    // 编辑态：以负号开头的输入 → 原样显示，不被当场置 0。
    //（jsdom 会把纯「-」清洗为 ''（真实浏览器是 badInput 暂态），
    // 因此这里断言完整「-5」路径——旧实现会把 -5 当场 Math.max 成 0。）
    fireEvent.change(input, { target: { value: '-5' } })
    expect((input as HTMLInputElement).value).toBe('-5')

    // 提交态：保存时才夹紧（-5 → 0 = 不限），提交语义与既有 0..10000 一致
    fireEvent.click(screen.getByRole('button', { name: '保存用量限制' }))
    await waitFor(() =>
      expect(
        putBodies.some((b) => (b as { quotaMaxCalls: number }).quotaMaxCalls === 0),
      ).toBe(true),
    )
  })

  it('提交态：超上限 10001 → 夹紧 10000；非法空串 → 0（= 不限）', async () => {
    const putBodies: unknown[] = []
    const fetchMock = vi
      .fn()
      .mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'PUT') {
          putBodies.push(JSON.parse(String(init?.body)))
          return Promise.resolve(jsonResponse({ quotaWindow: 'day', quotaMaxCalls: 10000 }))
        }
        return Promise.resolve(jsonResponse(USAGE))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderCard()

    const input = await screen.findByLabelText('请求上限')
    await waitFor(() => expect(input).toHaveValue(50))

    fireEvent.change(input, { target: { value: '10001' } })
    expect((input as HTMLInputElement).value).toBe('10001')
    fireEvent.click(screen.getByRole('button', { name: '保存用量限制' }))
    await waitFor(() =>
      expect(
        putBodies.some((b) => (b as { quotaMaxCalls: number }).quotaMaxCalls === 10000),
      ).toBe(true),
    )

    fireEvent.change(screen.getByLabelText('请求上限'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: '保存用量限制' }))
    await waitFor(() =>
      expect(
        putBodies.some((b) => (b as { quotaMaxCalls: number }).quotaMaxCalls === 0),
      ).toBe(true),
    )
  })
})
