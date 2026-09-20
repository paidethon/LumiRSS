/** F071 UI — 疑似重复对话框：扫描→队列渲染（双方标题/相似原因/三动作）、
 * confirm 调用 confirm 端点、空态诚实提示。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DuplicatesDialog } from '../components/DuplicatesDialog'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const PAIR = {
  id: 'pair-1',
  aRef: 'library:u-a',
  bRef: 'library:u-c',
  reason: 'same_content_url',
  status: 'pending',
  createdAt: '2026-09-19T00:00:00Z',
  aTitle: 'LumiRSS 阅读器上手指南',
  bTitle: 'shop item 42 剪藏',
  aUrl: 'https://shop.example/item/42',
  bUrl: 'https://shop.example/item/42',
}

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <DuplicatesDialog open onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F071 疑似重复对话框', () => {
  it('F071: 扫描→队列渲染双方标题与相似原因；确认重复调用 confirm', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (method === 'POST' && url.endsWith('/scan')) {
          return Promise.resolve(jsonResponse({ scanned: 5, created: 1, pending: 1 }))
        }
        if (method === 'POST' && url.endsWith('/confirm')) {
          return Promise.resolve(jsonResponse({ ...PAIR, status: 'confirmed' }))
        }
        return Promise.resolve(jsonResponse({ items: [PAIR] }))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    // 队列自动加载：双方标题 + 中文相似原因
    expect(await screen.findByText('甲：LumiRSS 阅读器上手指南')).toBeInTheDocument()
    expect(screen.getByText('乙：shop item 42 剪藏')).toBeInTheDocument()
    expect(screen.getByText(/同一内容地址（不同来源）/)).toBeInTheDocument()
    // 负向契约说明：不自动删除
    expect(screen.getByText(/绝不自动删除或合并/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '确认重复' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/library/duplicates/pair-1/confirm',
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })

  it('F071: 空队列诚实空态；扫描按钮触发扫描请求', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && String(input).endsWith('/scan')) {
          return Promise.resolve(jsonResponse({ scanned: 4, created: 0, pending: 0 }))
        }
        return Promise.resolve(jsonResponse({ items: [] }))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    expect(await screen.findByText(/没有待审核的疑似重复/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '扫描书签/剪藏' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/library/duplicates/scan',
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })
})
