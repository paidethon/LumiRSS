/** F019 回收站面板 —— 列表/恢复/永久删除（二次确认）交互。 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LibraryTrashPanel } from '../components/LibraryTrashPanel'

const ITEMS = {
  items: [
    {
      uuid: 'u-bookmark',
      kind: 'bookmark',
      title: '书签甲',
      url: null,
      deletedAt: '2026-09-19T00:00:00Z',
    },
    {
      uuid: 'u-clip',
      kind: 'clip',
      title: '剪辑乙',
      url: 'https://x.example/a',
      deletedAt: '2026-09-18T00:00:00Z',
    },
  ],
}

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.startsWith('/api/v1/library/trash')) {
    return Promise.resolve(new Response(JSON.stringify(ITEMS), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/restore')) {
    return Promise.resolve(new Response('', { status: 204 }))
  }
  if (method === 'DELETE' && url.includes('permanent=true')) {
    return Promise.resolve(new Response('', { status: 204 }))
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LibraryTrashPanel />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

describe('F019 回收站面板', () => {
  it('F019: 列出回收站条目（书签/剪辑 + 删除日期）', async () => {
    renderPanel()
    expect(await screen.findByText('书签甲')).toBeInTheDocument()
    expect(screen.getByText('剪辑乙')).toBeInTheDocument()
    expect(screen.getByText(/书签 · 删除于 2026-09-19/)).toBeInTheDocument()
    expect(screen.getAllByTestId('trash-item').length).toBe(2)
  })

  it('F019: 恢复 → 204 后刷新回收站', async () => {
    renderPanel()
    await screen.findByText('书签甲')
    const row = screen.getAllByTestId('trash-item')[0]!
    fireEvent.click(within(row).getByRole('button', { name: '恢复' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/library/trash/u-bookmark/restore'),
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })

  it('F019: 永久删除必须二次确认；确认后带 permanent=true', async () => {
    renderPanel()
    const firstPurge = await screen.findAllByRole('button', { name: '永久删除' })
    fireEvent.click(firstPurge[0]!)
    // 确认态出现（尚未发请求）
    expect(screen.getByRole('button', { name: '确认永久删除' })).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some(([u]) => String(u).includes('permanent=true')),
    ).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '确认永久删除' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([u, init]) => String(u).includes('permanent=true') && init?.method === 'DELETE',
        ),
      ).toBe(true)
    })
    // 可取消确认态
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
  })
})
