/** F063 UI — AI 任务中心面板：任务列表渲染（时间/类型/状态/耗时/错误
 * 类型）、失败摘要任务的重试按钮（调用 retry API）、Agent 会话说明。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AiTaskCenterPanel } from '../components/settings/AiTaskCenterPanel'
import type { AiTaskRecord } from '../api/client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const TASKS: AiTaskRecord[] = [
  {
    id: 't1',
    kind: 'summary',
    entryRef: 'e1.a',
    status: 'failed',
    model: 'model-a',
    durationMs: 1234,
    inputChars: 5000,
    errorType: 'rate_limited',
    createdAt: '2026-09-19T02:00:00Z',
  },
  {
    id: 't2',
    kind: 'translation',
    entryRef: 'e1.a',
    status: 'done',
    model: 'model-a',
    durationMs: 800,
    inputChars: null,
    errorType: null,
    createdAt: '2026-09-19T01:00:00Z',
  },
]

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AiTaskCenterPanel />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F063 AI 任务中心', () => {
  it('F063: 列表渲染类型/状态/耗时/错误类型；失败摘要任务有重试且调用 retry API', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && String(input).includes('/retry')) {
          return Promise.resolve(
            jsonResponse({
              task: { ...TASKS[0], status: 'done', errorType: null },
              originalId: 't1',
            }),
          )
        }
        return Promise.resolve(jsonResponse({ items: TASKS }))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    // 列表内容：类型/状态/耗时/错误类型标签
    expect(await screen.findByText('1234 ms')).toBeInTheDocument()
    expect(screen.getByText('摘要')).toBeInTheDocument()
    expect(screen.getByText('翻译')).toBeInTheDocument()
    expect(screen.getByText('完成')).toBeInTheDocument()
    expect(screen.getByText('上游限流')).toBeInTheDocument()
    // Agent 会话说明（不在此重试）
    expect(screen.getByText(/Agent 会话请沿用会话内既有的取消入口/)).toBeInTheDocument()

    // 失败 summary 任务的重试按钮（done 的翻译任务没有）
    const retryBtn = screen.getByRole('button', { name: /重试/ })
    fireEvent.click(retryBtn)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/ai/tasks/t1/retry',
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })

  it('F063: 空列表诚实空态；非 summary 失败任务不显示重试按钮', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          jsonResponse({
            items: [
              {
                ...TASKS[0],
                id: 't3',
                kind: 'conversation',
                errorType: 'timeout',
              },
            ],
          }),
        ),
      ),
    )
    renderPanel()
    expect(await screen.findByText('对话')).toBeInTheDocument()
    expect(screen.getByText('上游超时')).toBeInTheDocument()
    // conversation 失败任务：无重试按钮（输入由页面会话持有）
    expect(screen.queryByRole('button', { name: /重试/ })).toBeNull()
  })

  it('F063: 无任务记录 → 空态提示而非空白', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ items: [] }))),
    )
    renderPanel()
    expect(
      await screen.findByText(/还没有 AI 任务记录/),
    ).toBeInTheDocument()
  })
})
