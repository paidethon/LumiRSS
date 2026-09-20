/** F088 UI — 研究包 ZIP 导出：预览（estBytes/missing/快照清单）→ 勾选
 * 快照 → 下载（POST format=zip）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ResearchPackExportDialog } from '../components/WorkspaceExtras'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const WS = 'ws-9'

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ResearchPackExportDialog workspaceId={WS} onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:x'),
    revokeObjectURL: vi.fn(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F088 资料包导出（ZIP）', () => {
  it('F088: 预览→勾选快照→下载带 includeSnapshots；missing 诚实提示', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'POST' && url.endsWith('/research-pack/preview')) {
        return Promise.resolve(
          jsonResponse({
            entryCount: 4,
            missingCount: 1,
            estBytes: 40960,
            snapshots: [
              { uuid: 'snap-1', title: '页面存档 A', bytes: 20480 },
              { uuid: 'snap-2', title: '页面存档 B', bytes: 10240 },
            ],
          }),
        )
      }
      if (method === 'POST' && url.endsWith('/research-pack')) {
        return Promise.resolve(new Response(new Blob(['zip']), { status: 200 }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    fireEvent.click(screen.getByRole('button', { name: '生成预览' }))
    expect(await screen.findByText(/缺失资产 1 项/)).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('纳入快照：页面存档 A'))
    fireEvent.click(screen.getByRole('button', { name: '下载 ZIP' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/research-pack') && c[1]?.method === 'POST',
      )
      expect(call).toBeDefined()
      const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as { format: string; includeSnapshots: string[] }
      expect(body.format).toBe('zip')
      expect(body.includeSnapshots).toEqual(['snap-1'])
    })
  })

  it('F088: 超限 413 诚实报错', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'POST' && url.endsWith('/research-pack/preview')) {
        return Promise.resolve(jsonResponse({ entryCount: 1, missingCount: 0, estBytes: 10, snapshots: [] }))
      }
      if (method === 'POST' && url.endsWith('/research-pack')) {
        return Promise.resolve(
          jsonResponse({ error: { type: 'pack_too_large', message: '资料包超过 20MB 上限。' } }, 413),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    fireEvent.click(screen.getByRole('button', { name: '生成预览' }))
    await screen.findByText(/条目 1 条/)
    fireEvent.click(screen.getByRole('button', { name: '下载 ZIP' }))
    await waitFor(() => {
      expect(screen.getByText(/20MB 上限/)).toBeInTheDocument()
    })
  })
})
