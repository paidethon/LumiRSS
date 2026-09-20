/** F093 UI — 索引暂停与断点续建按钮：暂停请求（当前批完成后停）、
 * 续建请求（游标继续，报告 chunks）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RagSettingsSection from '../components/settings/RagSettingsSection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const STATUS = {
  enabled: true,
  chunks: 10,
  model: 'bge-small',
  vecTable: false,
  lastRebuildAt: null,
  lastError: null,
  fastembedAvailable: true,
}

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <RagSettingsSection />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F093 索引暂停与断点续建', () => {
  it('F093: 暂停 → POST /rag/rebuild/pause（jobId 返回时提示批后暂停）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/rag/status')) return Promise.resolve(jsonResponse(STATUS))
      if (method === 'POST' && url.endsWith('/rag/rebuild/pause')) {
        return Promise.resolve(jsonResponse({ paused: true, jobId: 'job-1', status: 'pausing' }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderSection()

    fireEvent.click(await screen.findByRole('button', { name: '暂停' }))
    await waitFor(() => {
      expect(screen.getByText(/当前批完成后暂停/)).toBeInTheDocument()
    })
  })

  it('F093: 续建 → POST /rag/rebuild/resume（报告 chunks）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/rag/status')) return Promise.resolve(jsonResponse(STATUS))
      if (method === 'POST' && url.endsWith('/rag/rebuild/resume')) {
        return Promise.resolve(jsonResponse({ chunks: 7, elapsedMs: 1200, jobId: 'job-1', status: 'done' }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderSection()

    fireEvent.click(await screen.findByRole('button', { name: '续建' }))
    await waitFor(() => {
      expect(screen.getByText(/续建完成：7 块/)).toBeInTheDocument()
    })
  })
})
