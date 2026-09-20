/** F023 作者聚合面板 —— 计数列表/合并（显式别名）/取消合并。 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AuthorAggregatesPanel from '../components/AuthorAggregatesPanel'

const AUTHORS = {
  items: [
    { author: '张三', count: 2 },
    { author: 'Zhang San', count: 1 },
  ],
}

const ALIASES = { items: [] as Array<{ alias: string; canonical: string; createdAt: string }> }

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/api/v1/authors?')) {
    return Promise.resolve(new Response(JSON.stringify(AUTHORS), { status: 200 }))
  }
  if (method === 'GET' && url.includes('/api/v1/authors/aliases')) {
    return Promise.resolve(new Response(JSON.stringify(ALIASES), { status: 200 }))
  }
  if (method === 'GET' && url.includes('/api/v1/authors/items')) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          author: '张三',
          items: [
            { entryRef: 'e1.a', title: '张三的文章', feedTitle: '源', publishedAt: '2026-09-01T00:00:00Z', read: false, starred: false },
          ],
          hasMore: false,
        }),
        { status: 200 },
      ),
    )
  }
  if (method === 'POST' && url.endsWith('/api/v1/authors/aliases')) {
    return Promise.resolve(
      new Response(JSON.stringify({ alias: 'Zhang San', canonical: '张三', createdAt: '2026-09-19T00:00:00Z' }), { status: 201 }),
    )
  }
  if (method === 'DELETE' && url.includes('/api/v1/authors/aliases/')) {
    return Promise.resolve(new Response('', { status: 204 }))
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <AuthorAggregatesPanel />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

describe('F023 作者聚合', () => {
  it('F023: 展开作者显示条目列表', async () => {
    renderPanel()
    fireEvent.click(await screen.findByText(/作者（2）/))
    expect(await screen.findByText('Zhang San')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /展开作者 张三/ }))
    expect(await screen.findByText('张三的文章')).toBeInTheDocument()
  })

  it('F023: 合并到另一作者 → POST 显式别名（alias/canonical）', async () => {
    renderPanel()
    fireEvent.click(await screen.findByText(/作者（2）/))
    const row = screen.getByText('Zhang San').closest('li') as HTMLElement
    fireEvent.click(within(row).getByRole('button', { name: '合并到…' }))
    fireEvent.change(screen.getByLabelText('把 Zhang San 合并到'), {
      target: { value: '张三' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认合并' }))
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith('/api/v1/authors/aliases') && (init as RequestInit).method === 'POST',
      )
      expect(post).toBeTruthy()
      const body = JSON.parse(String((post as unknown as [string, RequestInit])[1].body))
      expect(body).toEqual({ alias: 'Zhang San', canonical: '张三' })
    })
  })
})


