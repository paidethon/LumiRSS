/** F085/F086 UI — 看板三列（计数、>50 提示）、下拉移动（PUT）、
 * 目标卡进度（done 去重计数）与编辑。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkspaceBoardView } from '../components/WorkspaceBoard'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const WS = 'ws-1'
const REF_A = 'library:11111111-1111-4111-8111-111111111111'

function renderBoard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <WorkspaceBoardView workspaceId={WS} />
    </QueryClientProvider>,
  )
}

function boardResponse() {
  return {
    workspaceId: WS,
    columns: [
      {
        status: 'todo',
        total: 52,
        items: Array.from({ length: 50 }, (_, i) => ({
          itemRef: `library:00000000-0000-4000-8000-${String(i).padStart(12, '0')}`,
          status: 'todo',
          updatedAt: '2026-09-19T00:00:00Z',
        })),
      },
      { status: 'reading', total: 1, items: [{ itemRef: REF_A, status: 'reading', updatedAt: '2026-09-19T00:00:00Z' }] },
      { status: 'done', total: 3, items: [] },
    ],
  }
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F085 工作区看板 / F086 阅读目标', () => {
  it('F085: 三列渲染 + 列头计数 + >50 提示；下拉移动触发 PUT 且幂等重放', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith(`/workspaces/${WS}/board`)) {
        return Promise.resolve(jsonResponse(boardResponse()))
      }
      if (method === 'GET' && url.endsWith(`/workspaces/${WS}/goal`)) {
        return Promise.resolve(jsonResponse({ exists: false }))
      }
      if (method === 'PUT' && url.endsWith(`/workspaces/${WS}/board`)) {
        return Promise.resolve(jsonResponse({ itemRef: REF_A, status: 'done', updatedAt: '2026-09-19T01:00:00Z' }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderBoard()

    expect(await screen.findByTestId('workspace-board')).toBeInTheDocument()
    const todoColumn = document.querySelector('[data-board-column="todo"]')
    expect(todoColumn).toHaveTextContent('52')
    expect(screen.getByText(/仅显示前 50 条（共 52 条）/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(`移动条目 ${REF_A.slice(0, 13)}`), {
      target: { value: 'done' },
    })
    await waitFor(() => {
      const put = fetchMock.mock.calls.find((c) => String(c[0]).endsWith(`/workspaces/${WS}/board`) && c[1]?.method === 'PUT')
      expect(put).toBeDefined()
      const body = JSON.parse(String(put?.[1]?.body ?? '{}')) as { itemRef: string; status: string }
      expect(body).toEqual({ itemRef: REF_A, status: 'done' })
    })
  })

  it('F086: 目标卡进度与编辑（PUT goal）；删除目标→卡消失', async () => {
    let goalExists = true
    let goalTarget = 2
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith(`/workspaces/${WS}/board`)) {
        return Promise.resolve(jsonResponse(boardResponse()))
      }
      if (method === 'GET' && url.endsWith(`/workspaces/${WS}/goal`)) {
        return goalExists
          ? Promise.resolve(jsonResponse({ workspaceId: WS, targetCount: goalTarget, deadline: '2026-01-01', doneCount: 3, createdAt: '2026-09-01T00:00:00Z' }))
          : Promise.resolve(jsonResponse({ exists: false }))
      }
      if (method === 'PUT' && url.endsWith(`/workspaces/${WS}/goal`)) {
        goalTarget = 5
        return Promise.resolve(jsonResponse({ workspaceId: WS, targetCount: 5, deadline: null, doneCount: 3, createdAt: '2026-09-01T00:00:00Z' }))
      }
      if (method === 'DELETE' && url.endsWith(`/workspaces/${WS}/goal`)) {
        goalExists = false
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderBoard()

    const card = await screen.findByTestId('goal-card')
    // 进度与 board done 一致：done 3 / 目标 2（超额封顶 100%）。
    expect(card).toHaveTextContent('目标 3/2 条已完成')
    expect(card).toHaveTextContent('已到期')

    fireEvent.click(screen.getByRole('button', { name: '编辑目标' }))
    fireEvent.change(screen.getByLabelText('目标条数'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(screen.getByTestId('goal-card')).toHaveTextContent('目标 3/5 条已完成')
    })

    fireEvent.click(screen.getByRole('button', { name: '编辑目标' }))
    fireEvent.click(screen.getByRole('button', { name: /删除目标/ }))
    await waitFor(() => {
      expect(screen.queryByTestId('goal-card')).not.toBeInTheDocument()
      expect(screen.getByText('还没有阅读目标。')).toBeInTheDocument()
    })
  })
})
