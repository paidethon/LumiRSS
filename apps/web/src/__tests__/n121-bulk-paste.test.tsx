/** N121 UI — 粘贴多链接收件箱（书签页 / 剪藏页的 批量粘贴 dialog）。
 *
 * - textarea 逐行输入 → 提交体 {urls, target}（空行剔除、顺序保留）；
 * - 逐条结果列表（created/duplicate/failed + reason）如实渲染；
 * - 50 条上限守卫；书签页与剪藏页各自的 target。
 * 统一 stub 全局 fetch（与 f104/f089 同一约定，真实 client 解析路径）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BulkPasteDialog } from '../components/BulkPasteDialog'
import BookmarksPage from '../components/pages/BookmarksPage'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const BULK_RESULT = {
  target: 'bookmark',
  created: 1,
  duplicate: 1,
  failed: 1,
  items: [
    { url: 'https://a.example/1', status: 'created', ref: 'library:x' },
    { url: 'https://a.example/2', status: 'duplicate' },
    { url: 'bad', status: 'failed', reason: '链接必须是合法的 http(s) URL。' },
  ],
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('N121 批量粘贴', () => {
  it('逐行输入 → 提交 {urls, target}（空行剔除）→ 逐条结果渲染', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/library/bulk-links')) {
        return Promise.resolve(jsonResponse(BULK_RESULT))
      }
      return Promise.resolve(jsonResponse({ items: [], nextCursor: null }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderWithClient(<BulkPasteDialog target="bookmark" onClose={() => {}} />)

    const textarea = screen.getByLabelText('批量链接（每行一个）')
    fireEvent.change(textarea, {
      target: { value: 'https://a.example/1\n\nhttps://a.example/2\nbad\n' },
    })
    fireEvent.click(screen.getByRole('button', { name: '全部存为书签' }))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/library/bulk-links'))
      expect(call).toBeDefined()
      const body = JSON.parse(String(call?.[1]?.body ?? '{}'))
      expect(body.urls).toEqual([
        'https://a.example/1',
        'https://a.example/2',
        'bad',
      ])
      expect(body.target).toBe('bookmark')
    })
    const results = await screen.findByRole('status')
    expect(results.getAttribute('data-bulk-paste-results')).not.toBeNull()
    expect(results).toHaveTextContent('新建 1，重复 1，失败 1')
    expect(screen.getByText('https://a.example/1').closest('li')).toHaveAttribute(
      'data-bulk-result',
      'created',
    )
    expect(screen.getByText('https://a.example/2').closest('li')).toHaveAttribute(
      'data-bulk-result',
      'duplicate',
    )
    const failedRow = screen.getByText('bad').closest('li')
    expect(failedRow).toHaveAttribute('data-bulk-result', 'failed')
    expect(failedRow).toHaveTextContent('链接必须是合法的 http(s) URL。')
  })

  it('剪藏页入口提交 target=clip', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/library/bulk-links')) {
        return Promise.resolve(
          jsonResponse({
            target: 'clip',
            created: 1,
            duplicate: 0,
            failed: 0,
            items: [{ url: 'https://c.example/1', status: 'created' }],
          }),
        )
      }
      return Promise.resolve(jsonResponse({ items: [], nextCursor: null }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderWithClient(<BulkPasteDialog target="clip" onClose={() => {}} />)
    fireEvent.change(screen.getByLabelText('批量链接（每行一个）'), {
      target: { value: 'https://c.example/1' },
    })
    fireEvent.click(screen.getByRole('button', { name: '全部生成剪藏' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/library/bulk-links'))
      expect(JSON.parse(String(call?.[1]?.body ?? '{}')).target).toBe('clip')
    })
    expect(await screen.findByRole('status')).toHaveTextContent('新建 1，重复 0。')
  })

  it('超过 50 条 → 守卫提示且不提交', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    renderWithClient(<BulkPasteDialog target="bookmark" onClose={() => {}} />)
    const many = Array.from({ length: 51 }, (_, i) => `https://x.example/${i}`).join('\n')
    fireEvent.change(screen.getByLabelText('批量链接（每行一个）'), {
      target: { value: many },
    })
    expect(screen.getByRole('alert')).toHaveTextContent('一次最多 50 条')
    const submit = screen.getByRole('button', { name: '全部存为书签' })
    expect(submit).toBeDisabled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('书签页头部有 批量粘贴 入口', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/library/bookmarks')) {
        return Promise.resolve(jsonResponse({ items: [], nextCursor: null }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderWithClient(<BookmarksPage />)
    expect(await screen.findByRole('button', { name: '批量粘贴' })).toBeInTheDocument()
  })
})
