/** F111 —— 设置撤销（Web 层）。
 *
 * diff 值渲染（对象值 JSON.stringify，修 [object Object]；秘密键
 * before/after 已是 ***）→ 撤销确认对话框（列键与目标值）→ 执行后
 * applied/skipped 结果展示（skipped = 键已被后续修改，不静默）。
 * fetch 全部 stub。 */

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
      id: 1,
      action: 'update',
      changedAt: '2026-09-18T10:00:00+00:00',
      diff: {
        themeMode: { before: 'light', after: 'dark' },
        // 对象值：修 [object Object] 的关键场景
        paneRatios: { before: { timeline: 0.4, reader: 0.6 }, after: { timeline: 0.5, reader: 0.5 } },
        aiApiKey: { before: '***', after: '***' },
      },
    },
    {
      id: 2,
      action: 'update',
      changedAt: '2026-09-18T09:00:00+00:00',
      diff: {
        readerFontSize: { before: 16, after: 18 },
      },
    },
  ],
}

function renderSection(handler?: (url: string, init?: RequestInit) => Response) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
    (handler ?? (() => jsonResponse(HISTORY)))(String(input), init),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <SettingsHistorySection />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F111 设置撤销', () => {
  it('F111: diff 值渲染（对象 JSON.stringify、秘密 ***），确认对话框列目标值后执行', async () => {
    const fetchMock = renderSection((url, init) => {
      if (/\/settings\/history\/1\/revert$/.test(url) && init?.method === 'POST') {
        // N184：响应新增 restored/conflicts（显式清单）
        return jsonResponse({
          applied: { themeMode: 'light' },
          skipped: {},
          restored: ['themeMode'],
          conflicts: [],
        })
      }
      return jsonResponse(HISTORY)
    })
    await screen.findByText('设置变更历史')
    // 对象值 JSON.stringify（非 [object Object]）；秘密键只显示 ***
    expect(document.querySelector('[data-history-key="paneRatios"]')?.textContent).toContain(
      '{"timeline":0.4,"reader":0.6}',
    )
    expect(document.querySelector('[data-history-key="aiApiKey"]')?.textContent).toContain('*** → ***')

    // 撤销 → 确认对话框列出将影响的键与目标值
    fireEvent.click(screen.getAllByRole('button', { name: '撤销' })[0])
    const confirm = document.querySelector('[data-revert-confirm]')
    expect(confirm?.textContent).toContain('themeMode → light')
    expect(confirm?.textContent).toContain('paneRatios → {"timeline":0.4,"reader":0.6}')
    fireEvent.click(screen.getByRole('button', { name: '确认撤销' }))

    await waitFor(() => {
      expect(document.querySelector('[data-revert-result]')?.textContent).toContain('已回退 1 个键')
    })
    const post = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/revert') && init?.method === 'POST')
    expect(String(post?.[0])).toContain('/settings/history/1/revert')
  })

  it('F111: 部分键被后续修改 → skipped 列表如实展示', async () => {
    renderSection((url, init) => {
      if (/\/settings\/history\/2\/revert$/.test(url) && init?.method === 'POST') {
        return jsonResponse({
          applied: { readerFontSize: 16 },
          skipped: { readerLineHeight: 1.8 },
          restored: ['readerFontSize'],
          conflicts: [
            { key: 'readerLineHeight', reason: '该键在记录之后又被修改，回退不覆盖新修改' },
          ],
        })
      }
      return jsonResponse(HISTORY)
    })
    await screen.findByText('设置变更历史')
    const buttons = screen.getAllByRole('button', { name: '撤销' })
    fireEvent.click(buttons[1])
    fireEvent.click(screen.getByRole('button', { name: '确认撤销' }))
    await waitFor(() => {
      const result = document.querySelector('[data-revert-result]')
      expect(result?.textContent).toContain('已回退 1 个键')
      // N184：冲突显式清单（键 + 原因），不再静默跳过
      expect(result?.textContent).toContain('冲突 1 个键')
      expect(result?.textContent).toContain('readerLineHeight')
      expect(result?.textContent).toContain('该键在记录之后又被修改')
    })
  })

  it('F111: 全部键被后续修改 → applied 0 + skipped 仍如实', async () => {
    renderSection((url, init) => {
      if (/\/settings\/history\/1\/revert$/.test(url) && init?.method === 'POST') {
        return jsonResponse({
          applied: {},
          skipped: { themeMode: 'solarized' },
          restored: [],
          conflicts: [{ key: 'themeMode', reason: '该键在记录之后又被修改，回退不覆盖新修改' }],
        })
      }
      return jsonResponse(HISTORY)
    })
    await screen.findByText('设置变更历史')
    fireEvent.click(screen.getAllByRole('button', { name: '撤销' })[0])
    fireEvent.click(screen.getByRole('button', { name: '确认撤销' }))
    await waitFor(() => {
      expect(document.querySelector('[data-revert-result]')?.textContent).toContain('已回退 0 个键')
    })
  })
})
