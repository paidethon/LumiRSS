/** F094/F098 UI — 会话设置：资料范围 + 工具权限保存（PATCH）、下轮生效
 * 说明、非法上限被 input 约束后仍以服务端 422 为准。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ThreadSettingsButton } from '../components/AgentW5'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const THREAD = 'th-1'

function renderButton() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThreadSettingsButton threadId={THREAD} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    if (String(input).endsWith('/workspaces')) {
      return Promise.resolve(jsonResponse({ items: [{ id: 'ws-1', name: '研究', position: 1, itemCount: 0, reserved: false, description: null, archived: false, archivedAt: null }] }))
    }
    return Promise.resolve(jsonResponse({}))
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function patchCall(fetchMock: ReturnType<typeof vi.fn>): unknown {
  const call = fetchMock.mock.calls.find(
    (c) => String(c[0]) === `/api/v1/agent/threads/${THREAD}` && c[1]?.method === 'PATCH',
  )
  expect(call).toBeDefined()
  return JSON.parse(String(call![1].body ?? '{}')) as unknown
}

describe('F094/F098 会话设置', () => {
  it('F094: 保存资料范围（工作区）→ PATCH scope', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith('/workspaces')) {
        return Promise.resolve(jsonResponse({ items: [{ id: 'ws-1', name: '研究', position: 1, itemCount: 0, reserved: false, description: null, archived: false, archivedAt: null }] }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderButton()
    fireEvent.click(await screen.findByRole('button', { name: '会话设置' }))
    fireEvent.change(screen.getByLabelText('资料范围工作区'), { target: { value: 'ws-1' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(screen.getByText(/下一轮对话生效/)).toBeInTheDocument()
    })
    const body = patchCall(fetchMock) as { scope: unknown; clearScope: boolean }
    expect(body.scope).toEqual({ workspaceId: 'ws-1' })
    expect(body.clearScope).toBe(false)
  })

  it('F098: 只读模式 + allowed 子集 + 每轮上限 → PATCH toolPolicy', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith('/workspaces')) {
        return Promise.resolve(jsonResponse({ items: [] }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderButton()
    fireEvent.click(await screen.findByRole('button', { name: '会话设置' }))
    fireEvent.change(screen.getByLabelText('工具权限模式'), { target: { value: 'readonly' } })
    fireEvent.change(screen.getByLabelText('仅允许的工具'), { target: { value: 'search, rag_search' } })
    fireEvent.change(screen.getByLabelText('每轮工具调用上限'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(screen.getByText(/下一轮对话生效/)).toBeInTheDocument()
    })
    const body = patchCall(fetchMock) as {
      toolPolicy: { mode: string; allowedTools: string[]; maxOpsPerTurn: number }
    }
    expect(body.toolPolicy).toEqual({ mode: 'readonly', allowedTools: ['search', 'rag_search'], maxOpsPerTurn: 5 })
  })
})
