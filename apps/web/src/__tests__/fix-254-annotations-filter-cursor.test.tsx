/** FIX-254 — 清空筛选后，下一页请求必须从新查询的起点开始。
 *
 * AnnotationsManager（书签页「批注」页签）是唯一一处手写 continuation
 * 的列表：listQuery（useQuery，key 含 keyword/colorFilter）管第 1 页，
 * 「加载更多」手写续页。契约：
 *  1. 筛选（关键词/颜色）变化或清空时，已加载的手写续页与 cursor 一并
 *     重置（UI 只显示新查询的第 1 页）；
 *  2. 再次「加载更多」必须携带新查询第 1 页的 nextCursor——绝不复用
 *     旧筛选的 continuation（否则新筛选结果的第 2 页会从旧位置续，
 *     跳条/错位）。
 * 基线现状（BASELINE_OK 验证）：两处筛选 onChange 均已 setPages([]) +
 * setCursor(null)，加载更多取 listQuery.data.nextCursor（随 key 更新）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AnnotationsManager } from '../components/AnnotationsManager'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function annotation(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    entryRef: `e1.${id}`,
    anchor: { paraId: 'block-1', prefix: '', exact: `原文 ${id}`, suffix: '' },
    anchorHash: 'h',
    excerpt: `摘录 ${id}`,
    note: `备注 ${id}`,
    color: 'yellow',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-02T00:00:00Z',
    ...overrides,
  }
}

/** 真实分页语义：不同筛选各自独立 keyset（cursor 不跨筛选复用）。 */
const PAGES: Record<string, { items: unknown[]; nextCursor: string | null }> = {
  // 关键词「关键词」：第 1 页 / 第 2 页
  'q=关键词': { items: [annotation('q1')], nextCursor: 'c-q2' },
  'q=关键词&cursor=c-q2': { items: [annotation('q2')], nextCursor: null },
  // 颜色 yellow：第 1 页 / 第 2 页
  'color=yellow': { items: [annotation('y1')], nextCursor: 'c-y2' },
  'color=yellow&cursor=c-y2': { items: [annotation('y2')], nextCursor: null },
  // 清空筛选：无 q 的独立 keyset（起点 nextCursor ≠ 旧筛选的）
  '': { items: [annotation('n1')], nextCursor: 'c-n2' },
  'cursor=c-n2': { items: [annotation('n2')], nextCursor: null },
}

let queriesMade: string[] = []

function fetchMock() {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/v1/annotations/color-labels')) {
      return Promise.resolve(jsonResponse({ items: [] }))
    }
    if (url.includes('/api/v1/annotations?')) {
      const params = new URL(url, 'http://localhost').searchParams
      const key = [
        params.has('q') ? `q=${params.get('q')}` : '',
        params.has('color') ? `color=${params.get('color')}` : '',
        params.has('cursor') ? `cursor=${params.get('cursor')}` : '',
      ]
        .filter((part) => part !== '')
        .join('&')
      queriesMade.push(key)
      const page = PAGES[key]
      if (page === undefined) {
        return Promise.resolve(jsonResponse({ error: 'unexpected_page' }, 500))
      }
      return Promise.resolve(jsonResponse(page))
    }
    return Promise.resolve(jsonResponse({ error: 'not_found' }, 404))
  })
}

function renderManager() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AnnotationsManager />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  queriesMade = []
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-254 清空筛选 → 续页从新查询起点开始', () => {
  it('加载更多后清空关键词：续页请求携带新 keyset 的 nextCursor，不复用旧 cursor', async () => {
    vi.stubGlobal('fetch', fetchMock())
    renderManager()

    // 1. 输入关键词 → 第 1 页（q1，nextCursor=c-q2）
    const input = screen.getByLabelText('搜索批注')
    fireEvent.change(input, { target: { value: '关键词' } })
    expect(await screen.findByText('摘录 q1')).toBeInTheDocument()

    // 2. 加载更多 → 请求 cursor=c-q2（旧 keyset 续页，q2 显示）
    fireEvent.click(screen.getByRole('button', { name: '加载更多' }))
    expect(await screen.findByText('摘录 q2')).toBeInTheDocument()
    expect(queriesMade).toContain('q=关键词&cursor=c-q2')

    // 3. 清空筛选 → 手写续页与 cursor 一并重置：UI 回到新 keyset 第 1 页
    fireEvent.change(input, { target: { value: '' } })
    expect(await screen.findByText('摘录 n1')).toBeInTheDocument()
    expect(screen.queryByText('摘录 q2')).not.toBeInTheDocument()

    // 4. 再点加载更多 → cursor 必须是「新查询起点」c-n2，绝不是旧 c-q2
    queriesMade = []
    fireEvent.click(screen.getByRole('button', { name: '加载更多' }))
    expect(await screen.findByText('摘录 n2')).toBeInTheDocument()
    expect(queriesMade).toContain('cursor=c-n2')
    expect(queriesMade).not.toContain('cursor=c-q2')
    expect(queriesMade).not.toContain('q=关键词&cursor=c-q2')
  })

  it('清空颜色筛选同理：续页不携带旧筛选的 cursor', async () => {
    // 注入一个颜色标签，使颜色下拉出现
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/v1/annotations/color-labels')) {
          return Promise.resolve(
            jsonResponse({ items: [{ color: 'yellow', label: '高亮' }] }),
          )
        }
        if (url.includes('/api/v1/annotations?')) {
          const params = new URL(url, 'http://localhost').searchParams
          const key = [
            params.has('q') ? `q=${params.get('q')}` : '',
            params.has('color') ? `color=${params.get('color')}` : '',
            params.has('cursor') ? `cursor=${params.get('cursor')}` : '',
          ]
            .filter((part) => part !== '')
            .join('&')
          queriesMade.push(key)
          const page = PAGES[key]
          if (page === undefined) {
            return Promise.resolve(jsonResponse({ error: 'unexpected_page' }, 500))
          }
          return Promise.resolve(jsonResponse(page))
        }
        return Promise.resolve(jsonResponse({ error: 'not_found' }, 404))
      }),
    )
    renderManager()

    // 等颜色下拉出现（color-labels 返回后渲染）
    const colorSelect = await screen.findByLabelText('按颜色筛选')
    fireEvent.change(colorSelect, { target: { value: 'yellow' } })
    expect(await screen.findByText('摘录 y1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '加载更多' }))
    expect(await screen.findByText('摘录 y2')).toBeInTheDocument()
    expect(queriesMade).toContain('color=yellow&cursor=c-y2')

    // 清空颜色 → 回到无筛选 keyset；再次加载更多不得携带 color=yellow 的 cursor
    fireEvent.change(screen.getByLabelText('按颜色筛选'), { target: { value: 'all' } })
    expect(await screen.findByText('摘录 n1')).toBeInTheDocument()
    queriesMade = []
    fireEvent.click(screen.getByRole('button', { name: '加载更多' }))
    expect(await screen.findByText('摘录 n2')).toBeInTheDocument()
    expect(queriesMade).toContain('cursor=c-n2')
    expect(queriesMade).not.toContain('color=yellow&cursor=c-y2')
  })
})
