/** E3-final 批注两特性 Web 测试 — N072 精选篮 / N078 跨版本迁移。
 *
 * fetch 以 URL 匹配 mock：N072 验证多选加入篮 + 篮导出走既有 export
 * 路径（basketId 参数）；N078 验证迁移预览勾选后逐项应用（apply 只含
 * 勾选项，走既有 migrate/apply 端点）。服务端口径见 BFF 测试。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AnnotationsManager } from '../components/AnnotationsManager'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderWithQuery(ui: React.ReactElement): QueryClient {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
  return queryClient
}

const ANNOTATION = {
  id: 'a1',
  entryRef: 'e1.abc',
  anchor: { paraId: 'block-1', prefix: '', exact: '精选摘录一句', suffix: '' },
  anchorHash: 'h1',
  excerpt: '精选摘录一句',
  note: '我的备注',
  color: 'yellow',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-02T00:00:00Z',
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('N072 批注精选篮', () => {
  it('创建篮 → 勾选批注 → 加入所选（POST annotation-ids）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/annotation-baskets')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              { id: 'b1', name: '研究精选', createdAt: '2026-01-01T00:00:00Z', itemCount: 0 },
            ],
          }),
        )
      }
      if (url.includes('/annotation-baskets/b1/items') && !url.includes('export')) {
        return Promise.resolve(jsonResponse({ added: ['a1'], skipped: [] }))
      }
      return Promise.resolve(jsonResponse({ items: [ANNOTATION], nextCursor: null }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderWithQuery(<AnnotationsManager />)
    expect(await screen.findByText('精选摘录一句')).toBeInTheDocument()

    // 先选中篮（加入所选按钮仅在选中篮后出现）
    fireEvent.click(await screen.findByRole('button', { name: /研究精选/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: '选择此批注（加入精选篮）' }))
    const addButtons = await screen.findAllByRole('button', { name: '加入所选（1）' })
    fireEvent.click(addButtons[0])

    await waitFor(() => {
      const addCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes('/annotation-baskets/b1/items') &&
          init?.method === 'POST',
      )
      expect(addCall).toBeDefined()
      expect(JSON.parse(String(addCall![1]?.body))).toEqual({ annotationIds: ['a1'] })
    })
  })

  it('篮内导出带 basketId 参数（走既有 export 路径）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/annotation-baskets')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              { id: 'b1', name: '导出篮', createdAt: '2026-01-01T00:00:00Z', itemCount: 2 },
            ],
          }),
        )
      }
      if (url.includes('/annotations/export')) {
        return new Response('# 批注汇编\n', {
          headers: { 'content-type': 'text/markdown; charset=utf-8' },
        })
      }
      return Promise.resolve(jsonResponse({ items: [ANNOTATION], nextCursor: null }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderWithQuery(<AnnotationsManager />)
    fireEvent.click(await screen.findByRole('button', { name: /导出篮/ }))
    const exportBtn = await screen.findByRole('button', { name: '导出此篮' })
    fireEvent.click(exportBtn)

    await waitFor(() => {
      const exportCall = fetchMock.mock.calls.find(([url]) =>
        String(url).includes('/annotations/export'),
      )
      expect(exportCall).toBeDefined()
      expect(JSON.parse(String(exportCall![1]?.body))).toEqual({ basketId: 'b1' })
    })
  })
})

describe('N078 批注跨版本迁移', () => {
  it('预览 → 勾选候选 → 应用只含勾选项', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/annotations/migrate/preview')) {
        return Promise.resolve(
          jsonResponse({
            entryRef: 'e1.abc',
            fromVersion: 'current',
            toVersion: 'last_known_full',
            matched: [
              {
                annotationId: 'a1',
                candidateBlockIndex: 1,
                score: 1,
                excerpt: '精选摘录一句',
              },
            ],
            unmatched: [{ annotationId: 'a2', reason: 'no_match' }],
          }),
        )
      }
      if (url.endsWith('/annotations/migrate/apply')) {
        return Promise.resolve(
          jsonResponse({
            applied: [{ annotationId: 'a1', ok: true }],
            failed: [],
          }),
        )
      }
      return Promise.resolve(jsonResponse({ items: [ANNOTATION], nextCursor: null }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderWithQuery(<AnnotationsManager />)
    // 等列表就绪（按钮 disabled={items.length===0}）
    expect(await screen.findByText('精选摘录一句')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '跨版本迁移' }))

    const checkbox = await screen.findByRole('checkbox', {
      name: /确认迁移批注 a1/,
    })
    fireEvent.click(checkbox)

    const applyBtn = screen.getByRole('button', { name: '迁移所选（1）' })
    fireEvent.click(applyBtn)

    await waitFor(() => {
      expect(screen.getByText(/已迁移 1 条/)).toBeInTheDocument()
    })
    const applyCall = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith('/annotations/migrate/apply'),
    )
    expect(applyCall).toBeDefined()
    const body = JSON.parse(String(applyCall![1]?.body))
    expect(body.fromVersion).toBe('current')
    expect(body.toVersion).toBe('last_known_full')
    expect(body.items).toEqual([{ annotationId: 'a1', blockIndex: 1 }])
  })
})
