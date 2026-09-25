/** N164–N170 Agent ops UI — 暂停/续接控制、工具执行时间线行、批准参数
 * 修订、失败步骤重试、差异撤销、任务配方面板（保存/列表/预览/运行）。
 * 全部走 mock fetch（黑盒：断言请求路径与载荷 + 诚实错误呈现）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApprovalEditSection,
  PauseResumeControls,
  RecipePanel,
  ThreadRetryButton,
  ToolTimelineRow,
} from '../components/AgentW5'
import type { AgentMessage } from '../api/client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
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

describe('N164 暂停与续接', () => {
  it('暂停按钮 POST /pause；续接按钮 POST /resume', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/pause')) return Promise.resolve(jsonResponse({ paused: true, status: 'pausing' }))
      if (url.includes('/resume'))
        return Promise.resolve(jsonResponse({ status: 'processing', approval: null, reconfirmRequired: false }))
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<PauseResumeControls threadId="th-1" processing={false} />)

    fireEvent.click(screen.getByRole('button', { name: '暂停' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith('/pause'))).toBe(true)
    })
    fireEvent.click(screen.getByRole('button', { name: '续接' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith('/resume'))).toBe(true)
    })
  })

  it('无可暂停对象 409 → 诚实报错', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(jsonResponse({ error: { type: 'no_active_run', message: '当前没有正在运行或等待批准的回合。' } }, 409)),
      )
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<PauseResumeControls threadId="th-1" processing={false} />)
    fireEvent.click(screen.getByRole('button', { name: '暂停' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/没有正在运行或等待批准/)
    })
  })

  it('处理中暂停/续接都禁用（不打断进行中的回合）', () => {
    renderUi(<PauseResumeControls threadId="th-1" processing={true} />)
    expect(screen.getByRole('button', { name: '暂停' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '续接' })).toBeDisabled()
  })
})

describe('N166 工具执行时间线', () => {
  const baseRow = {
    id: 'm1',
    threadId: 'th-1',
    seq: 3,
    role: 'tool' as const,
    citations: [],
    createdAt: '2026-09-25T00:00:00Z',
  }

  it('渲染 per-step 行：耗时徽标 + 成功/失败状态 + 脱敏参数摘要', () => {
    const message = {
      ...baseRow,
      content: {
        callId: 'c1',
        name: 'search',
        result: { untrusted: true, payload: { results: [] } },
        durationMs: 42,
        resultType: 'result',
        maskedArgsSummary: '{"query":"vLLM"}',
      },
    } as unknown as AgentMessage
    renderUi(<ToolTimelineRow message={message} />)
    const row = screen.getByText('工具 · search').closest('[data-timeline-row]')
    expect(row).not.toBeNull()
    expect(screen.getByText('42 ms')).toBeInTheDocument()
    expect(screen.getByText('成功')).toBeInTheDocument()
    expect(screen.getByText('{"query":"vLLM"}')).toBeInTheDocument()
  })

  it('失败行红色标注 + durationMs 缺失时不渲染耗时徽标', () => {
    const message = {
      ...baseRow,
      content: {
        callId: 'c2',
        name: 'rag_search',
        error: 'tool_denied',
        resultType: 'error',
      },
    } as unknown as AgentMessage
    renderUi(<ToolTimelineRow message={message} />)
    expect(screen.getByText('失败')).toBeInTheDocument()
    expect(screen.queryByText(/ms$/)).not.toBeInTheDocument()
  })

  it('时间线行绝无 api-key 形态的值（脱敏摘要内也不出现 sk- 密钥）', () => {
    const message = {
      ...baseRow,
      content: {
        callId: 'c3',
        name: 'search',
        result: { untrusted: true, payload: { note: 'ok' } },
        durationMs: 7,
        resultType: 'result',
        maskedArgsSummary: '{"apiKey":"***","query":"x"}',
      },
    } as unknown as AgentMessage
    renderUi(<ToolTimelineRow message={message} />)
    expect(screen.queryByText(/sk-[A-Za-z0-9_-]{8,}/)).not.toBeInTheDocument()
    expect(screen.queryByText(/sk-/i)).not.toBeInTheDocument()
  })

  it('N169：可撤销写步骤渲染撤销按钮；点击 POST /undo；冲突诚实标注', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({ undone: false, stepId: 'step-1', tool: 'add_to_workspace', result: null, conflictReason: '条目已被移出' }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const message = {
      ...baseRow,
      content: {
        callId: 'c4',
        name: 'add_to_workspace',
        result: { untrusted: true, payload: { added: true } },
        resultType: 'result',
        stepId: 'step-1',
        undoable: true,
      },
    } as unknown as AgentMessage
    renderUi(<ToolTimelineRow message={message} />)
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith('/undo'))).toBe(true)
      expect(screen.getByText('冲突跳过')).toBeInTheDocument()
    })
  })
})

describe('N167 批准内容修改', () => {
  it('编辑参数 → 保存修订 POST /revise 携带 newArgs', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({
          approval: {
            approvalId: 'ap-new',
            callId: 'c1',
            tool: 'save_bookmark',
            args: { url: 'https://example.com/v2' },
            status: 'pending',
          },
          supersededApprovalId: 'ap-old',
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ApprovalEditSection threadId="th-1" approvalId="ap-old" args={{ url: 'https://example.com/v1' }} />)

    fireEvent.click(screen.getByRole('button', { name: '编辑参数' }))
    const textarea = screen.getByLabelText('修订批准参数')
    expect(textarea).toHaveValue('{\n  "url": "https://example.com/v1"\n}')
    fireEvent.change(textarea, { target: { value: '{"url": "https://example.com/v2"}' } })
    fireEvent.click(screen.getByRole('button', { name: '保存并重新批准' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes('/revise'))
      expect(call).toBeTruthy()
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        newArgs: { url: 'https://example.com/v2' },
      })
    })
  })

  it('非法 JSON 在本地拦截（不发请求）', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ApprovalEditSection threadId="th-1" approvalId="ap-old" args={{ url: 'x' }} />)
    fireEvent.click(screen.getByRole('button', { name: '编辑参数' }))
    fireEvent.change(screen.getByLabelText('修订批准参数'), { target: { value: '{not json' } })
    fireEvent.click(screen.getByRole('button', { name: '保存并重新批准' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/不是合法 JSON/)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('N168 失败步骤重试', () => {
  it('重试按钮 POST /retry（已完成步骤由服务端复用 transcript）', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ status: 'completed', retried: [], skipped: [], approval: null })),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ThreadRetryButton threadId="th-1" processing={false} />)
    fireEvent.click(screen.getByRole('button', { name: '重试失败步骤' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith('/retry'))).toBe(true)
    })
  })
})

describe('N170 任务配方', () => {
  function mockRecipesFetch() {
    return vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/agent/recipes') && globalThis.fetch === undefined) {
        return Promise.resolve(jsonResponse({ items: [] }))
      }
      if (url.endsWith('/agent/recipes')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 'rc-1',
                name: '稍后读整理',
                input: '把搜索到的第一条加入稍后读',
                toolWhitelist: ['search', 'add_to_workspace'],
                scope: null,
                createdAt: '2026-09-25T00:00:00Z',
                updatedAt: '2026-09-25T00:00:00Z',
              },
            ],
          }),
        )
      }
      if (url.includes('/preview')) {
        return Promise.resolve(
          jsonResponse({
            recipeId: 'rc-1',
            name: '稍后读整理',
            input: '把搜索到的第一条加入稍后读',
            toolWhitelist: ['search', 'add_to_workspace'],
            unknownTools: [],
            scope: null,
            toolPolicy: { allowedTools: ['search', 'add_to_workspace'] },
            threadTitle: '稍后读整理',
            note: '运行将创建新会话。',
          }),
        )
      }
      if (url.includes('/run')) {
        return Promise.resolve(
          jsonResponse({
            recipeId: 'rc-1',
            thread: { id: 'th-new', title: '稍后读整理', createdAt: '2026-09-25T00:00:00Z' },
            status: 'processing',
          }),
        )
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
  }

  it('配方列表渲染；点击配方 → 预览 → 运行 → onRun 回调新会话', async () => {
    const fetchMock = mockRecipesFetch()
    vi.stubGlobal('fetch', fetchMock)
    const onRun = vi.fn()
    renderUi(<RecipePanel onRun={onRun} />)

    expect(await screen.findByText('稍后读整理')).toBeInTheDocument()
    expect(screen.getByText('2 个工具')).toBeInTheDocument()

    fireEvent.click(screen.getByText('稍后读整理'))
    expect(await screen.findByText('运行配方（预览）')).toBeInTheDocument()
    expect(await screen.findByText(/工具白名单：search、add_to_workspace/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '运行（创建新会话）' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/run'))).toBe(true)
      expect(onRun).toHaveBeenCalledWith('th-new')
    })
  })

  it('新建配方：填写名称/输入/白名单 → POST /agent/recipes', async () => {
    const fetchMock = mockRecipesFetch()
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<RecipePanel onRun={vi.fn()} />)
    await screen.findByText('稍后读整理')

    fireEvent.click(screen.getByRole('button', { name: '新建' }))
    fireEvent.change(screen.getByLabelText('配方名称'), { target: { value: '晨报整理' } })
    fireEvent.change(screen.getByLabelText('配方首条消息'), { target: { value: '整理稍后读' } })
    fireEvent.change(screen.getByLabelText('配方工具白名单'), { target: { value: 'search, add_to_workspace' } })
    fireEvent.click(screen.getByRole('button', { name: '保存配方' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/agent/recipes') && c[1]?.method === 'POST',
      )
      expect(call).toBeTruthy()
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        name: '晨报整理',
        input: '整理稍后读',
        toolWhitelist: ['search', 'add_to_workspace'],
        scope: null,
      })
    })
  })

  it('未知白名单 422 → 诚实报错', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/agent/recipes') && init?.method !== 'POST') {
        return Promise.resolve(jsonResponse({ items: [] }))
      }
      return Promise.resolve(
        jsonResponse({ error: { type: 'invalid_recipe', message: '未知工具：delete_everything' } }, 422),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<RecipePanel onRun={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '新建' }))
    fireEvent.change(screen.getByLabelText('配方名称'), { target: { value: '坏配方' } })
    fireEvent.change(screen.getByLabelText('配方首条消息'), { target: { value: 'x' } })
    fireEvent.change(screen.getByLabelText('配方工具白名单'), { target: { value: 'delete_everything' } })
    fireEvent.click(screen.getByRole('button', { name: '保存配方' }))
    await waitFor(() => {
      expect(screen.getByText(/未知工具：delete_everything/)).toBeInTheDocument()
    })
  })
})
