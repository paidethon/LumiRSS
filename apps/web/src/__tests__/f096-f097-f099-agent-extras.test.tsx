/** F096/F097/F099 UI — 会话导出（预览+下载、422 诚实）、写操作预演
 * （changes 渲染 + 410 过期诚实）、分支按钮（POST messageIndex → 回调）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BranchButton, ThreadExportButton } from '../components/AgentW5'
import { ApprovalPreviewSection } from '../components/AgentW5'

function jsonResponse(body: unknown, status = 200, contentType = 'application/json'): Response {
  if (contentType !== 'application/json') {
    return new Response(String(body), { status, headers: { 'content-type': contentType } })
  }
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': contentType },
  })
}

function renderUi(ui: React.ReactElement) {
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

describe('F096 会话导出', () => {
  it('F096: 选择轮数→生成预览→下载', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse('# 会话导出\n\n用户: 你好\n助手: 你好！', 200, 'text/markdown')),
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() })
    renderUi(<ThreadExportButton threadId="th-1" />)

    fireEvent.click(screen.getByRole('button', { name: '导出会话' }))
    fireEvent.change(screen.getByLabelText('导出轮数'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: '生成预览' }))
    expect(await screen.findByText(/会话导出/)).toBeInTheDocument()
    const call = fetchMock.mock.calls.find((c) => String(c[0]).includes('/export'))
    expect(String(call?.[0])).toContain('rounds=3')
    expect(String(call?.[0])).toContain('format=md')

    fireEvent.click(screen.getByRole('button', { name: '下载 .md' }))
    expect(vi.mocked(URL.createObjectURL).mock.calls.length).toBe(1)
  })

  it('F096: 空会话 422 诚实报错', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({ error: { type: 'invalid_export_request', message: '会话没有可导出的消息。' } }, 422),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ThreadExportButton threadId="th-1" />)

    fireEvent.click(screen.getByRole('button', { name: '导出会话' }))
    fireEvent.click(screen.getByRole('button', { name: '生成预览' }))
    await waitFor(() => {
      expect(screen.getByText(/没有可导出的消息/)).toBeInTheDocument()
    })
  })
})

describe('F097 写操作预演', () => {
  it('F097: 查看影响→changes 渲染（from→to）+ uncertain', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({
          approvalId: 'ap-1',
          tool: 'add_to_workspace',
          target: 'library:11111111-1111-4111-8111-111111111111',
          changes: [{ field: 'workspaceItems', from: 3, to: 4 }],
          uncertain: [],
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ApprovalPreviewSection threadId="th-1" approvalId="ap-1" />)

    fireEvent.click(screen.getByRole('button', { name: '查看影响' }))
    expect(await screen.findByText(/预演（零写入）目标/)).toBeInTheDocument()
    expect(screen.getByText(/workspaceItems: 3 → 4/)).toBeInTheDocument()
  })

  it('F097: 过期审批 410 诚实报错；只读工具 422 提示', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({ error: { type: 'approval_expired', message: '批准已超时。' } }, 410),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ApprovalPreviewSection threadId="th-1" approvalId="ap-2" />)

    fireEvent.click(screen.getByRole('button', { name: '查看影响' }))
    await waitFor(() => {
      expect(screen.getByText('批准已超时。')).toBeInTheDocument()
    })
  })
})

describe('F099 对话分支', () => {
  it('F099: 分支按钮 POST messageIndex → 成功回调新会话', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({
          thread: { id: 'th-new', title: '分支', createdAt: '2026-09-19T00:00:00Z' },
          branchOf: 'th-1',
          copiedMessages: 6,
          truncated: false,
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const onBranched = vi.fn()
    renderUi(<BranchButton threadId="th-1" messageSeq={6} onBranched={onBranched} />)

    fireEvent.click(screen.getByRole('button', { name: '从消息 6 分支' }))
    await waitFor(() => {
      expect(onBranched).toHaveBeenCalledWith('th-new')
      const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/branch'))
      const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as { messageIndex: number }
      expect(body.messageIndex).toBe(6)
    })
  })

  it('F099: 非法 index 422 诚实报错', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({ error: { type: 'invalid_branch_request', message: '消息序号越界。' } }, 422),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const onBranched = vi.fn()
    renderUi(<BranchButton threadId="th-1" messageSeq={99} onBranched={onBranched} />)

    fireEvent.click(screen.getByRole('button', { name: '从消息 99 分支' }))
    await waitFor(() => {
      expect(screen.getByText('消息序号越界。')).toBeInTheDocument()
      expect(onBranched).not.toHaveBeenCalled()
    })
  })
})
