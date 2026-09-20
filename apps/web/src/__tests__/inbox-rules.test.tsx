/** F022 收件箱归类规则面板 —— 列表/启停/试跑。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import InboxRulesPanel from '../components/InboxRulesPanel'

const RULES = {
  items: [
    {
      id: 1,
      priority: 0,
      field: 'title',
      operator: 'contains',
      value: '周报',
      targetWorkspaceId: 'ws-1',
      enabled: true,
      createdAt: '2026-09-19T00:00:00Z',
    },
    {
      id: 2,
      priority: 1,
      field: 'source',
      operator: 'equals',
      value: 'scripts',
      targetWorkspaceId: 'ws-2',
      enabled: false,
      createdAt: '2026-09-19T00:00:00Z',
    },
  ],
}

const WORKSPACES = {
  items: [
    { id: 'ws-1', name: '优先工作区', position: 1, itemCount: 0, reserved: false, description: '' },
    { id: 'ws-2', name: '归档区', position: 2, itemCount: 0, reserved: false, description: '' },
  ],
}

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/api/v1/inbox/rules')) {
    return Promise.resolve(new Response(JSON.stringify(RULES), { status: 200 }))
  }
  if (method === 'GET' && url.includes('/api/v1/workspaces')) {
    return Promise.resolve(new Response(JSON.stringify(WORKSPACES), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/inbox/rules/dry-run')) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          matchedRule: RULES.items[0],
          explanation: '第 1 条规则命中：标题「晚间周报」包含「周报」→ 归入工作区 ws-1。',
        }),
        { status: 200 },
      ),
    )
  }
  if (method === 'PATCH' && url.includes('/inbox/rules/1')) {
    return Promise.resolve(new Response(JSON.stringify({ ...RULES.items[0], enabled: false }), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/move')) {
    return Promise.resolve(new Response(JSON.stringify(RULES.items[0]), { status: 200 }))
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <InboxRulesPanel />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

describe('F022 收件箱归类规则', () => {
  it('F022: 列出规则并展示启停状态；上移禁用首条', async () => {
    renderPanel()
    fireEvent.click(await screen.findByText(/归类规则（2）/))
    expect(await screen.findByText(/标题 包含「周报」/)).toBeInTheDocument()
    expect(screen.getByText(/来源 等于「scripts」/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '上移规则 周报' })).toBeDisabled()
  })

  it('F022: 启停开关发出 PATCH enabled', async () => {
    renderPanel()
    fireEvent.click(await screen.findByText(/归类规则（2）/))
    fireEvent.click(await screen.findByRole('switch', { name: '启用规则 周报' }))
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([url, init]) => url.toString().includes('/inbox/rules/1') && (init as RequestInit).method === 'PATCH',
      )
      expect(patch).toBeTruthy()
      expect(JSON.parse(String((patch as unknown as [string, RequestInit])[1].body)).enabled).toBe(false)
    })
  })

  it('F022: dry-run 展示命中解释（不落库，仅 POST dry-run）', async () => {
    renderPanel()
    fireEvent.click(await screen.findByText(/归类规则（2）/))
    fireEvent.change(await screen.findByLabelText('试跑样本值'), { target: { value: '晚间周报' } })
    fireEvent.click(screen.getByRole('button', { name: '试跑' }))
    expect(await screen.findByText(/第 1 条规则命中/)).toBeInTheDocument()
    const dryRuns = fetchMock.mock.calls.filter(
      ([url, init]) =>
        String(url).includes('/inbox/rules/dry-run') && (init as RequestInit | undefined)?.method === 'POST',
    )
    expect(dryRuns).toHaveLength(1)
    // 除 dry-run 外，本用例不应有其他写请求打到 /inbox/rules
    const writes = fetchMock.mock.calls.filter(
      ([url, init]) =>
        String(url).includes('/inbox/rules') &&
        (init as RequestInit | undefined)?.method !== undefined &&
        (init as RequestInit).method !== 'GET',
    )
    expect(writes).toHaveLength(1)
  })
})
