/** F024 积压整理面板 —— 预览（真实 count）→ 确认执行 → 结果/重试。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BacklogPanel } from '../components/BacklogPanel'

let previewCount = 2
let applyResponses: Array<{ status: number; body: unknown }> = []

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'POST' && url.includes('/entries/backlog-preview')) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          count: previewCount,
          sample: [
            { ref: 'rss:e1.a', title: '旧文甲', publishedAt: '2026-01-01T00:00:00Z' },
            { ref: 'rss:e1.b', title: '旧文乙', publishedAt: '2026-01-02T00:00:00Z' },
          ],
          effectiveExclusions: ['starred', 'read-later'],
          confirmPreviewToken: 'token-' + 'x'.repeat(20),
        }),
        { status: 200 },
      ),
    )
  }
  if (method === 'POST' && url.includes('/entries/backlog-apply')) {
    const spec = applyResponses.shift() ?? { status: 200, body: { applied: 0, failed: [], effectiveExclusions: [] } }
    return Promise.resolve(new Response(JSON.stringify(spec.body), { status: spec.status }))
  }
  return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
})

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <BacklogPanel onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockClear()
  previewCount = 2
  applyResponses = []
  vi.stubGlobal('fetch', fetchMock)
})

describe('F024 积压整理助手', () => {
  it('F024: 预览显示真实 count 与排除项，确认执行成功后展示结果', async () => {
    applyResponses.push({ status: 200, body: { applied: 2, failed: [], effectiveExclusions: ['starred', 'read-later'] } })
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText((_, el) => el?.tagName === 'P' && /共 2 条未读积压/.test(el.textContent ?? ''))).toBeInTheDocument()
    expect(screen.getByText(/starred、read-later/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /确认全部标为已读（2）/ }))
    expect(await screen.findByText((_, el) => el?.tagName === 'P' && /已标记 2 条为已读/.test(el.textContent ?? ''))).toBeInTheDocument()
    const applyCall = fetchMock.mock.calls.find(([, init]) =>
      String(init?.body ?? '').includes('confirmPreviewToken'),
    )
    expect(applyCall).toBeTruthy()
  })

  it('F024: token 过期 409 → 提示重新预览；部分失败可重试', async () => {
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    await screen.findByText((_, el) => el?.tagName === 'P' && /共 2 条未读积压/.test(el.textContent ?? ''))
    applyResponses.push({
      status: 409,
      body: { error: { type: 'backlog_conflict', message: '预览令牌已过期（30 秒），请重新预览。' } },
    })
    fireEvent.click(screen.getByRole('button', { name: /确认全部标为已读/ }))
    expect(await screen.findByText(/预览令牌已过期/)).toBeInTheDocument()

    // 重新预览 + 部分失败
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    await screen.findByText((_, el) => el?.tagName === 'P' && /共 2 条未读积压/.test(el.textContent ?? ''))
    applyResponses.push({
      status: 200,
      body: {
        applied: 1,
        failed: [{ ref: 'rss:e1.b', title: '旧文乙', publishedAt: null }],
        effectiveExclusions: ['starred', 'read-later'],
      },
    })
    fireEvent.click(screen.getByRole('button', { name: /确认全部标为已读/ }))
    expect(await screen.findByText((_, el) => el?.tagName === 'P' && /已标记 1 条为已读，1 条失败/.test(el.textContent ?? ''))).toBeInTheDocument()
    expect(screen.getByText('旧文乙')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试失败项' })).toBeInTheDocument()
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([, init]) => String(init?.body ?? '').includes('confirmPreviewToken'))).toHaveLength(2)
    })
  })
})
