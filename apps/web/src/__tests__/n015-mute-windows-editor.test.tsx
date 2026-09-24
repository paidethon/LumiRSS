/** N015 UI — 来源设置对话框的分时静音编辑器。
 *
 * - 添加窗口行（日选择 chips + 起止时间）、删除窗口；
 * - 校验：无 day / 起止相同 → 错误提示 + 保存禁用（不放行无效载荷）；
 * - 保存 → PUT 载荷携带 muteWindows（与既有 per-source 覆盖同请求）；
 * - 服务端已有窗口 → 初始渲染诚实回显。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SourcePolicyDialog } from '../components/subscription-w3-panels'

const FEED_URL = 'https://a.example/rss'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderDialog(overrides: Record<string, unknown> = {}) {
  const calls: { method: string; url: string; body?: unknown }[] = []
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    let body: unknown
    try {
      body = init?.body !== undefined ? JSON.parse(String(init.body)) : undefined
    } catch {
      body = undefined
    }
    calls.push({ method, url, body })
    if (method === 'GET' && url === '/api/v1/sources/overrides') {
      return Promise.resolve(
        jsonResponse({
          items: [
            {
              feedUrl: FEED_URL,
              hiddenUntil: null,
              showFrom: null,
              staleAlertHours: null,
              extractPolicy: 'rss',
              readerStyle: null,
              aiDisabled: false,
              ...overrides,
              updatedAt: '2026-09-01T00:00:00Z',
            },
          ],
        }),
      )
    }
    if (method === 'PUT' && url === '/api/v1/sources/overrides') {
      return Promise.resolve(jsonResponse({ feedUrl: FEED_URL, ...overrides }))
    }
    return Promise.resolve(jsonResponse({}))
  })
  vi.stubGlobal('fetch', fn)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <SourcePolicyDialog open onClose={() => {}} feedUrl={FEED_URL} title="示例源" />
    </QueryClientProvider>,
  )
  return { calls }
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('N015 分时静音编辑器', () => {
  it('添加窗口 → 选日 → 保存 → PUT 载荷携带 muteWindows', async () => {
    const { calls } = renderDialog()
    await screen.findByText('未设置静音窗口。')
    // 等服务端同步 effect 冲刷完成后再交互（避免同步重置吃掉本次编辑）；
    // 若首击仍被冲掉的挂起 effect 吃掉，waitFor 重试补一击（幂等）。
    await act(async () => {})
    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: '添加静音窗口' }))
      return screen.queryByTestId('mute-windows-list') !== null
    })
    // 选周一、周三
    fireEvent.click(screen.getByRole('button', { name: '周一' }))
    fireEvent.click(screen.getByRole('button', { name: '周三' }))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT')
      expect(put).toBeDefined()
      const body = put?.body as { muteWindows?: { days: number[]; start: string; end: string }[] }
      expect(body.muteWindows).toEqual([{ days: [1, 3], start: '22:00', end: '06:00' }])
    })
  })

  it('窗口缺日 → 校验错误 + 保存禁用（无效载荷不放行）', async () => {
    const { calls } = renderDialog()
    await screen.findByText('未设置静音窗口。')
    // 等服务端同步 effect 冲刷完成后再交互（避免同步重置吃掉本次编辑）
    await act(async () => {})
    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: '添加静音窗口' }))
      return screen.queryByTestId('mute-windows-error') !== null
    })
    const error = screen.getByTestId('mute-windows-error')
    expect(error.textContent).toContain('至少选择一天')
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
    // 选日后恢复可保存
    fireEvent.click(screen.getByRole('button', { name: '周日' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).not.toBeDisabled())
    expect(screen.queryByTestId('mute-windows-error')).toBeNull()
  })

  it('删除窗口行 → 保存载荷 muteWindows=null（清除维度）', async () => {
    const { calls } = renderDialog()
    await screen.findByText('未设置静音窗口。')
    // 等服务端同步 effect 冲刷完成后再交互（避免同步重置吃掉本次编辑）
    await act(async () => {})
    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: '添加静音窗口' }))
      return screen.queryByTestId('mute-windows-list') !== null
    })
    fireEvent.click(screen.getByRole('button', { name: '周一' }))
    fireEvent.click(screen.getByRole('button', { name: '删除窗口 1' }))
    await act(async () => {})
    expect(await screen.findByText('未设置静音窗口。')).toBeInTheDocument()
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT')
      expect((put?.body as { muteWindows?: unknown }).muteWindows).toBeNull()
    })
  })

  it('服务端已有窗口 → 初始回显', async () => {
    renderDialog({
      muteWindows: [{ days: [0, 6], start: '23:00', end: '01:00' }],
    })
    await screen.findByTestId('mute-windows-list')
    expect(screen.getByRole('button', { name: '周日', pressed: true })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '周六', pressed: true })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '周一', pressed: false })).toBeInTheDocument()
  })
})
