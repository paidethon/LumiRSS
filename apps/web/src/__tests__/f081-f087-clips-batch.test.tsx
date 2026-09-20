/** F081/F087 ClipsPage 接入 — 剪藏多选批量编辑与检查链接（复用书签页
 * 同款对话框）；选中计数、按选中 refs 发请求。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import ClipsPage from '../components/pages/ClipsPage'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const CLIP_A = 'library:11111111-1111-4111-8111-111111111111'
const CLIP_B = 'library:22222222-2222-4222-8222-222222222222'

const CLIPS_PAGE = {
  items: [
    { ref: CLIP_A, url: 'https://example.com/a', title: '剪藏 A', byline: null, createdAt: '2026-09-01T08:00:00Z', fetchedAt: '2026-09-01T08:00:00Z' },
    { ref: CLIP_B, url: 'https://example.com/b', title: '剪藏 B', byline: null, createdAt: '2026-09-02T08:00:00Z', fetchedAt: '2026-09-02T08:00:00Z' },
  ],
  nextCursor: null as string | null,
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ClipsPage />
    </QueryClientProvider>,
  )
}

/** 与全局 beforeEach 等价：默认提供 clips 列表；各测试内再 stub 一次
 * 以便拿到 fetchMock 引用（vitest stubGlobal 不返回 mock）。 */
function stubFetch(extra?: (url: string, method: string, init?: RequestInit) => Response | null) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (method === 'GET' && url.includes('/library/clips')) {
      return Promise.resolve(jsonResponse(CLIPS_PAGE))
    }
    const handled = extra?.(url, method, init)
    if (handled !== null && handled !== undefined) return Promise.resolve(handled)
    return Promise.resolve(jsonResponse({}))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('F081/F087 ClipsPage 多选批量操作', () => {
  it('F081: 勾选两条→批量编辑→预览请求携带两条 clip ref', async () => {
    const fetchMock = stubFetch((url, method) => {
      if (method === 'POST' && url.endsWith('/library/batch-edit/preview')) {
        return jsonResponse({
          items: [CLIP_A, CLIP_B].map((ref) => ({
            ref,
            before: { title: 'T', tags: [], workspaceIds: [] },
            after: { title: 'T【荐】', tags: [], workspaceIds: [] },
          })),
        })
      }
      return null
    })
    renderPage()

    expect(await screen.findByText('剪藏 A')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('选择剪藏：剪藏 A'))
    fireEvent.click(screen.getByLabelText('选择剪藏：剪藏 B'))
    expect(document.querySelector('[data-selection-count]')).toHaveTextContent('已选 2 条')

    fireEvent.click(screen.getByRole('button', { name: '批量编辑' }))
    fireEvent.click(screen.getByLabelText('勾选：标题追加后缀'))
    fireEvent.change(screen.getByLabelText('标题后缀'), { target: { value: '【荐】' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    await screen.findByText('变更前')
    const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/library/batch-edit/preview'))
    const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as { refs: string[] }
    expect(body.refs.sort()).toEqual([CLIP_A, CLIP_B])
  })

  it('F087: 勾选一条→检查链接→只带该 ref 且不改写 URL', async () => {
    const fetchMock = stubFetch((url, method, init) => {
      if (method === 'POST' && url.endsWith('/library/bookmarks/check-links')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as { refs: string[] }
        return jsonResponse({
          items: body.refs.map((ref) => ({ ref, status: 'ok', httpStatus: 200, checkedAt: '2026-09-19T00:00:00Z' })),
        })
      }
      return null
    })
    renderPage()

    expect(await screen.findByText('剪藏 B')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('选择剪藏：剪藏 B'))
    fireEvent.click(screen.getByRole('button', { name: '检查链接' }))
    fireEvent.click(await screen.findByRole('button', { name: '开始检查' }))
    await waitFor(() => {
      expect(screen.getByText('正常 · HTTP 200')).toBeInTheDocument()
    })
    const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/library/bookmarks/check-links'))
    const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as { refs: string[] }
    expect(body.refs).toEqual([CLIP_B])
  })
})
