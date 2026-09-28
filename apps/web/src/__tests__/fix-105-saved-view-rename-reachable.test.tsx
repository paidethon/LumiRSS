/** FIX-105 — 触屏/键盘不可达的 hover 专属交互：已存视图的重命名。
 *
 * 修复前：重命名入口只有「双击 chip」，且唯一说明藏在 title（hover 才
 * 可见）——触屏无 hover、双击还会先触发单击「应用视图」。修复后：chip
 * 行有显式重命名按钮（与比较/私有订阅同型），触屏与键盘直达；双击保留
 * 为桌面加速路径。
 *
 * 本用例不模拟 hover：直接断言改名控件存在（可访问名），点击即进入
 * 重命名输入态。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const SAVED_VIEW = {
  id: 'view-1',
  name: '运维周报',
  query: 'k8s',
  view: 'all',
  categoryKey: 'search',
  createdAt: '2026-09-01T00:00:00Z',
  hasFeedToken: false,
  filters: null,
  workspaceId: null,
  contentTypes: null,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function mockSearchApiFetch(): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST' || init?.method === 'PATCH' || init?.method === 'DELETE') {
      return Promise.resolve(jsonResponse({}))
    }
    const url = String(input)
    if (url.startsWith('/api/v1/search/views')) {
      return Promise.resolve(jsonResponse({ items: [SAVED_VIEW] }))
    }
    if (url.startsWith('/api/v1/search')) {
      return Promise.resolve(
        jsonResponse({ items: [], hasMore: false, nextCursor: null, index: null, library: [] }),
      )
    }
    if (url.startsWith('/api/v1/feeds')) {
      return Promise.resolve(
        jsonResponse([{ id: 'user/-/label/默认', title: '默认', feedUrl: 'https://a.example/rss' }]),
      )
    }
    if (url.startsWith('/api/v1/subscriptions')) {
      return Promise.resolve(
        jsonResponse([
          { subscriptionRef: 's1.a', title: '源甲', feedUrl: 'https://a.example/rss', category: null },
        ]),
      )
    }
    if (url.startsWith('/api/v1/entries')) {
      return Promise.resolve(jsonResponse({ items: [], nextCursor: null }))
    }
    return Promise.resolve(jsonResponse({}))
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('FIX-105: 已存视图重命名不依赖 hover/双击', () => {
  it('chip 行有显式重命名按钮（可访问名）；点击（无 hover）进入重命名输入态', async () => {
    vi.stubGlobal('fetch', mockSearchApiFetch())
    const { default: SearchPage } = await import('../components/pages/SearchPage')
    const { useReaderUi } = await import('../store/reader-ui')
    useReaderUi.setState({ section: 'search', view: 'all' })
    const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query')
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <SearchPage />
      </QueryClientProvider>,
    )

    // chip 出现（保存的视图列表加载完成）
    const chip = await screen.findByRole('button', { name: '运维周报' })
    expect(chip).toBeInTheDocument()

    // 显式重命名控件（FIX-105 修复点）：不依赖 hover 的可发现入口
    const renameButton = await screen.findByRole('button', { name: '重命名视图「运维周报」' })
    expect(renameButton).toBeInTheDocument()

    // 普通 click（触屏/键盘语义）即进入重命名输入态——不需要 dblclick
    fireEvent.click(renameButton)
    const input = await waitFor(() => {
      const el = screen.getByLabelText('重命名视图', { selector: 'input' })
      expect(el).toHaveValue('运维周报')
      return el
    })
    expect(input).toHaveFocus()
  })
})
