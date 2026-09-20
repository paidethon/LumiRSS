/** F089 UI — 剪藏手工修订：块勾选保存（PATCH revision）、全移除显式
 * force、已修订徽标 + 查看原始。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ClipRevisionDialog } from '../components/ClipRevisionDialog'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const CLIP_REF = 'library:33333333-3333-4333-8333-333333333333'
const BLOCKS = {
  blocks: [
    { id: 'b1', text: '第一段：导语内容。' },
    { id: 'b2', text: '第二段：广告噪声。' },
    { id: 'b3', text: '第三段：结论。' },
  ],
}

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ClipRevisionDialog clipRef={CLIP_REF} onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F089 剪藏手工修订', () => {
  it('F089: 块清单渲染→取消勾选噪声块→保存（只带保留块 id + hash 基础）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/revision')) {
        return Promise.resolve(jsonResponse(BLOCKS))
      }
      if (method === 'PATCH' && url.endsWith('/revision')) {
        return Promise.resolve(
          jsonResponse({
            ref: CLIP_REF,
            url: 'https://example.com/a',
            title: 't',
            byline: null,
            fetchedAt: '2026-09-19T00:00:00Z',
            createdAt: '2026-09-19T00:00:00Z',
            original: { contentHtml: '<p>一</p><p>二</p><p>三</p>' },
            revised: { revisedAt: '2026-09-19T01:00:00Z', note: '去广告', baseContentHash: 'h1' },
            content: {},
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    expect(await screen.findByText('第二段：广告噪声。')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('保留块：b2'))
    fireEvent.change(screen.getByLabelText('修订说明'), { target: { value: '去广告' } })
    fireEvent.click(screen.getByRole('button', { name: '保存修订' }))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/revision') && c[1]?.method === 'PATCH',
      )
      expect(call).toBeDefined()
      const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as { blocks: string[]; note: string; force: boolean }
      expect(body.blocks.sort()).toEqual(['b1', 'b3'])
      expect(body.note).toBe('去广告')
      expect(body.force).toBe(false)
    })
  })

  it('F089: 全移除需显式确认（force）；422 must_keep_one 诚实透出', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/revision')) {
        return Promise.resolve(jsonResponse(BLOCKS))
      }
      if (method === 'PATCH' && url.endsWith('/revision')) {
        return Promise.resolve(
          jsonResponse({ error: { type: 'must_keep_one', message: '至少保留一个块；如需清空请显式确认。' } }, 422),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await screen.findByText('第一段：导语内容。')
    // 取消所有块。
    for (const id of ['b1', 'b2', 'b3']) {
      fireEvent.click(screen.getByLabelText(`保留块：${id}`))
    }
    expect(screen.getByText(/显式确认/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '清空全部（显式）' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/revision') && c[1]?.method === 'PATCH',
      )
      expect(call).toBeDefined()
      const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as { force: boolean }
      expect(body.force).toBe(true)
      expect(screen.getByRole('alert')).toHaveTextContent(/must_keep_one|显式确认/)
    })
  })
})
