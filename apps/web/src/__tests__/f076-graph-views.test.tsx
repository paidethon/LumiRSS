/** F076 图谱命名视图 — 布局应用逻辑单测（存在→位置/新增→默认位/
 * 失效→跳过）+ 工具栏保存/覆盖 409/恢复往返。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { applyGraphLayout } from '../lib/graph-views'
import { GraphViewsToolbar } from '../components/GraphViewsToolbar'

const NODES = [{ ref: 'tag:1' }, { ref: 'tag:2' }, { ref: 'tag:new' }]

describe('F076 applyGraphLayout 布局应用逻辑', () => {
  it('F076: 存在节点应用位置；新增节点默认位；失效节点跳过；不崩', () => {
    const result = applyGraphLayout(NODES, {
      'tag:1': { x: 10, y: -5 },
      'tag:2': { x: 3, y: 4 },
      'tag:gone': { x: 99, y: 99 }, // 失效节点（已不在图中）
    })
    expect(result.applied).toBe(2)
    expect(result.defaulted).toBe(1) // 新增节点默认位
    expect(result.skipped).toBe(1) // 失效节点跳过
    expect(result.positions.get('tag:1')).toEqual({ x: 10, y: -5 })
    expect(result.positions.get('tag:new')).toEqual({ x: 0, y: 0 })
  })
})

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const SAVED = {
  id: 'gv1',
  name: '我的布局',
  layout: { 'tag:1': { x: 10, y: -5 } },
  filters: { scope: 'tag:1' },
  focusNode: 'tag:2',
  createdAt: '2026-09-19T00:00:00Z',
  updatedAt: '2026-09-19T00:00:00Z',
}

function renderToolbar(props: {
  onRestore: (payload: { layout: Record<string, { x: number; y: number }>; filters: Record<string, unknown>; focusNode: string | null }) => void
  items?: unknown[]
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <GraphViewsToolbar
        nodes={NODES}
        filters={{ scope: 'all' }}
        focusNode={null}
        captureLayout={() => ({})}
        onRestore={props.onRestore}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F076 图谱视图工具栏', () => {
  it('F076: 保存当前 → POST；恢复 → filters/focus 回调应用（往返）', async () => {
    const onRestore = vi.fn()
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (method === 'POST' && url === '/api/v1/graph/views') {
          return Promise.resolve(jsonResponse(SAVED))
        }
        if (method === 'GET' && url === '/api/v1/graph/views') {
          return Promise.resolve(jsonResponse({ items: [SAVED] }))
        }
        return Promise.resolve(jsonResponse({}))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderToolbar({ onRestore })

    // 保存当前
    fireEvent.change(screen.getByLabelText('视图名称'), { target: { value: '我的布局' } })
    fireEvent.click(screen.getByRole('button', { name: '保存当前' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/graph/views',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    const saveBody = JSON.parse(
      (fetchMock.mock.calls.find((c) => (c[1] as RequestInit)?.method === 'POST')?.[1] as RequestInit).body as string,
    )
    expect(saveBody.name).toBe('我的布局')
    expect(saveBody.filters).toEqual({ scope: 'all' })

    // 恢复：下拉选择 → onRestore 收到 layout/filters/focus
    fireEvent.change(screen.getByLabelText('恢复命名视图'), { target: { value: 'gv1' } })
    expect(onRestore).toHaveBeenCalledWith({
      layout: SAVED.layout,
      filters: { scope: 'tag:1' },
      focusNode: 'tag:2',
    })
    expect(await screen.findByText(/已恢复「我的布局」/)).toBeInTheDocument()
  })

  it('F076: 同名保存先确认覆盖（两步流）；删除调用 DELETE', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        if (method === 'POST') {
          return Promise.resolve(jsonResponse(SAVED))
        }
        if (method === 'DELETE') {
          return new Response(null, { status: 204 })
        }
        return Promise.resolve(jsonResponse({ items: [SAVED] }))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderToolbar({ onRestore: vi.fn() })

    // 输入已存在名称 → 第一次点击变为「确认覆盖」（未发请求）
    fireEvent.change(screen.getByLabelText('视图名称'), { target: { value: '我的布局' } })
    await screen.findByRole('button', { name: '删除' }) // 名称已存在 → 出现删除
    fireEvent.click(screen.getByRole('button', { name: '保存当前' }))
    // 确认覆盖 → 发送 overwrite: true
    fireEvent.click(screen.getByRole('button', { name: '确认覆盖' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/graph/views',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    const body = JSON.parse(
      (fetchMock.mock.calls.find((c) => (c[1] as RequestInit)?.method === 'POST')?.[1] as RequestInit).body as string,
    )
    expect(body.overwrite).toBe(true)

    // 删除
    fireEvent.click(screen.getByRole('button', { name: '删除' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/graph/views/gv1',
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
  })
})
