/** N184 —— 设置差异恢复显式化（Web 层）。
 *
 * 冲突键 + 原因显式列出（不再静默跳过）；其余键明确「已回退」。
 * fetch 全部 stub。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SettingsHistorySection } from '../components/settings/SettingsHistorySection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const HISTORY = {
  items: [
    {
      id: 7,
      action: 'update',
      changedAt: '2026-09-24T10:00:00+00:00',
      diff: {
        readerFontSize: { before: 17, after: 21 },
        readerJustify: { before: false, after: true },
      },
    },
  ],
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('N184 冲突显式清单', () => {
  it('冲突键列出（键 + 原因），其余键显示为已回退', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (/\/settings\/history\/7\/revert$/.test(String(input)) && init?.method === 'POST') {
        return jsonResponse({
          applied: { readerJustify: false },
          skipped: { readerFontSize: 14 },
          restored: ['readerJustify'],
          conflicts: [{ key: 'readerFontSize', reason: '该键在记录之后又被修改，回退不覆盖新修改' }],
        })
      }
      return jsonResponse(HISTORY)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={qc}>
        <SettingsHistorySection />
      </QueryClientProvider>,
    )

    await screen.findByText('设置变更历史')
    fireEvent.click(screen.getAllByRole('button', { name: '撤销' })[0])
    fireEvent.click(screen.getByRole('button', { name: '确认撤销' }))

    await waitFor(() => {
      expect(document.querySelector('[data-revert-result]')?.textContent).toContain('已回退 1 个键')
    })
    expect(document.querySelector('[data-revert-result]')?.textContent).toContain('回退生效：readerJustify')
    const conflict = document.querySelector('[data-revert-conflict="readerFontSize"]')
    expect(conflict?.textContent).toContain('readerFontSize')
    expect(conflict?.textContent).toContain('该键在记录之后又被修改')
    // 冲突清单容器确实存在
    expect(document.querySelector('[data-revert-conflicts]')).not.toBeNull()
    const post = fetchMock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/revert') && init?.method === 'POST',
    )
    expect(String(post?.[0])).toContain('/settings/history/7/revert')
  })

  it('无冲突时不显示冲突清单', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (/\/revert$/.test(String(input)) && init?.method === 'POST') {
          return jsonResponse({
            applied: { readerFontSize: 17, readerJustify: false },
            skipped: {},
            restored: ['readerFontSize', 'readerJustify'],
            conflicts: [],
          })
        }
        return jsonResponse(HISTORY)
      }),
    )
    render(
      <QueryClientProvider client={qc}>
        <SettingsHistorySection />
      </QueryClientProvider>,
    )
    await screen.findByText('设置变更历史')
    fireEvent.click(screen.getAllByRole('button', { name: '撤销' })[0])
    fireEvent.click(screen.getByRole('button', { name: '确认撤销' }))
    await waitFor(() => {
      expect(document.querySelector('[data-revert-result]')?.textContent).toContain('已回退 2 个键')
    })
    expect(document.querySelector('[data-revert-conflicts]')).toBeNull()
  })
})
