/** F021 手工关联内容面板 —— 列表/解除/创建（搜索选择 + 备注）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ItemRelationsPanel from '../components/ItemRelationsPanel'

const SELF_REF = 'rss:e1.aWVtLTE'

function relationResponse() {
  return {
    items: [
      {
        id: 7,
        srcRef: SELF_REF,
        dstRef: 'library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f',
        note: '同一事件',
        createdAt: '2026-09-19T00:00:00Z',
        src: { ref: SELF_REF, domain: 'rss', kind: 'rss', title: '本文', source: 'rss', stale: false },
        dst: {
          ref: 'library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f',
          domain: 'library',
          kind: 'bookmark',
          title: '收藏页',
          source: 'library',
          stale: true,
          staleReason: 'not_found',
        },
        stale: true,
      },
    ],
  }
}

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/api/v1/relations?')) {
    return Promise.resolve(
      new Response(JSON.stringify(relationResponse()), { status: 200 }),
    )
  }
  if (method === 'DELETE' && url.includes('/api/v1/relations/')) {
    return Promise.resolve(new Response('', { status: 204 }))
  }
  if (method === 'GET' && url.includes('/api/v1/search?')) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          items: [
            { entryRef: 'e1.aWVtLTk', title: '搜索到的条目', feedTitle: '源', read: false, starred: false },
          ],
          hasMore: false,
          nextCursor: null,
          library: null,
        }),
        { status: 200 },
      ),
    )
  }
  if (method === 'POST' && url.endsWith('/api/v1/relations')) {
    return Promise.resolve(new Response('', { status: 201 }))
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ItemRelationsPanel itemRef={SELF_REF} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

describe('F021 手工关联内容', () => {
  it('F021: 列出双向关联；失效端不渲染标题而是「已失效」徽标', async () => {
    renderPanel()
    expect(await screen.findByText(/关联内容（1）/)).toBeInTheDocument()
    // 失效端：不显示对方标题，显示已失效提示（图谱跳转前校验的 UI 面）
    expect(screen.queryByText('收藏页')).not.toBeInTheDocument()
    expect(screen.getByText(/已失效 · library:/)).toBeInTheDocument()
    expect(screen.getByText('同一事件')).toBeInTheDocument()
  })

  it('F021: 解除关联发出 DELETE', async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole('button', { name: /解除关联/ }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/relations/7'),
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
  })

  it('F021: 创建对话框搜索选择后 POST，带备注与目标 ref', async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole('button', { name: '关联内容' }))
    const input = await screen.findByLabelText('搜索要关联的条目')
    fireEvent.change(input, { target: { value: '搜索' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    fireEvent.click(await screen.findByText('搜索到的条目'))
    fireEvent.change(screen.getByLabelText('关联备注'), {
      target: { value: '手工备注' },
    })
    fireEvent.click(screen.getByRole('button', { name: '创建关联' }))
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith('/api/v1/relations') &&
          (init as RequestInit | undefined)?.method === 'POST',
      )
      expect(post).toBeTruthy()
      const body = JSON.parse(String((post as unknown as [string, RequestInit])[1].body))
      expect(body.srcRef).toBe(SELF_REF)
      expect(body.dstRef).toBe('rss:e1.aWVtLTk')
      expect(body.note).toBe('手工备注')
    })
  })
})
