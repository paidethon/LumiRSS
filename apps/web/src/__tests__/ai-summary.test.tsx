/** 0015 Gate 7 — ReaderSummary 状态机测试。
 *
 * 所有 fetch 全部 stub：零网络。重点验证：
 * - not_generated → 「AI 摘要」按钮；点击是唯一触发 POST 的动作；
 * - 成功后渲染纯文本摘要 + model · 时间；缓存命中显示「缓存」徽标且无 POST；
 * - not_configured / failed / content 不可用 / generating 各自诚实呈现。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReaderSummary from '../components/ReaderSummary'

const REF = 'e1.a'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>

function mockApi(handler: Handler) {
  return vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    return handler(String(input), init)
  })
}

function renderSummary(queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})) {
  return render(
    <QueryClientProvider client={queryClient}>
      <ReaderSummary entryRef={REF} />
    </QueryClientProvider>,
  )
}

const summaryGet = (body: unknown, status = 200): Handler =>
  (url, init) => {
    if ((init?.method ?? 'GET') === 'GET' && url === `/api/v1/entries/${REF}/summary`) {
      return jsonResponse(body, status)
    }
    throw new Error(`unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
  }

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ReaderSummary', () => {
  it('not_generated：渲染「AI 摘要」按钮，点击发出唯一 POST 并展示成功摘要', async () => {
    let postCount = 0
    vi.stubGlobal(
      'fetch',
      mockApi((url, init) => {
        if ((init?.method ?? 'GET') === 'GET') {
          return jsonResponse({
            status: 'not_generated',
            summary: null,
            provider: 'openai_compatible',
            model: 'model-a',
            promptVersion: 'summary-v1',
            language: 'zh-CN',
            generatedAt: null,
            failureType: null,
            cached: false,
          })
        }
        if (init?.method === 'POST') {
          postCount += 1
          return jsonResponse({
            status: 'success',
            summary: '这是一段生成好的摘要。',
            provider: 'openai_compatible',
            model: 'model-a',
            promptVersion: 'summary-v1',
            language: 'zh-CN',
            generatedAt: '2026-09-02T10:00:00+00:00',
            failureType: null,
            cached: false,
          })
        }
        throw new Error(`unexpected: ${url} ${init?.method}`)
      }),
    )

    renderSummary()

    const button = await screen.findByRole('button', { name: /AI 摘要/ })
    expect(screen.getByText(/按需生成，不会自动调用 AI/)).toBeInTheDocument()
    fireEvent.click(button)

    await waitFor(() => {
      expect(screen.getByText('这是一段生成好的摘要。')).toBeInTheDocument()
    })
    expect(postCount).toBe(1)
    expect(screen.queryByRole('button', { name: /AI 摘要/ })).toBeNull()
    expect(screen.getByText(/model-a/)).toBeInTheDocument()
  })

  it('缓存命中（cached=true）：展示摘要与「缓存」徽标，绝不发出 POST', async () => {
    const fetchMock = mockApi(
      summaryGet({
        status: 'success',
        summary: '缓存摘要内容。',
        provider: 'openai_compatible',
        model: 'model-a',
        promptVersion: 'summary-v1',
        language: 'zh-CN',
        generatedAt: '2026-09-02T09:00:00+00:00',
        failureType: null,
        cached: true,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    renderSummary()

    await waitFor(() => {
      expect(screen.getByText('缓存摘要内容。')).toBeInTheDocument()
    })
    expect(screen.getByText('缓存')).toBeInTheDocument()
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(posts).toHaveLength(0)
  })

  it('AI 未配置（503 ai_not_configured）：诚实说明，无生成按钮', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi(
        summaryGet(
          { error: { type: 'ai_not_configured', message: 'AI is not configured.' } },
          503,
        ),
      ),
    )

    renderSummary()

    await waitFor(() => {
      expect(screen.getByText(/AI 摘要未配置/)).toBeInTheDocument()
    })
    expect(screen.getByText(/设置 → AI/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /AI 摘要/ })).toBeNull()
  })

  it('failed 状态：按 failureType 说明 + 重试按钮可再生成', async () => {
    let mode: 'failed' | 'success' = 'failed'
    vi.stubGlobal(
      'fetch',
      mockApi((_url, init) => {
        if ((init?.method ?? 'GET') === 'GET') {
          return jsonResponse({
            status: mode,
            summary: mode === 'success' ? '重试后的摘要。' : null,
            provider: 'openai_compatible',
            model: 'model-a',
            promptVersion: 'summary-v1',
            language: 'zh-CN',
            generatedAt: null,
            failureType: mode === 'failed' ? 'timeout' : null,
            cached: false,
          })
        }
        if (init?.method === 'POST') {
          mode = 'success'
          return jsonResponse({
            status: 'success',
            summary: '重试后的摘要。',
            provider: 'openai_compatible',
            model: 'model-a',
            promptVersion: 'summary-v1',
            language: 'zh-CN',
            generatedAt: '2026-09-02T11:00:00+00:00',
            failureType: null,
            cached: false,
          })
        }
        throw new Error('unexpected')
      }),
    )

    renderSummary()

    await waitFor(() => {
      expect(screen.getByText(/AI 服务响应超时/)).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /重试/ }))
    await waitFor(() => {
      expect(screen.getByText('重试后的摘要。')).toBeInTheDocument()
    })
  })

  it('正文不可用（422）：说明且无生成按钮', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi(
        summaryGet(
          { error: { type: 'ai_content_unavailable', message: 'no content' } },
          422,
        ),
      ),
    )

    renderSummary()

    await waitFor(() => {
      expect(screen.getByText(/没有可摘要的正文内容/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /AI 摘要/ })).toBeNull()
  })

  it('generating 状态：显示加载提示', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi(
        summaryGet({
          status: 'generating',
          summary: null,
          provider: 'openai_compatible',
          model: 'model-a',
          promptVersion: 'summary-v1',
          language: 'zh-CN',
          generatedAt: null,
          failureType: null,
          cached: false,
        }),
      ),
    )

    renderSummary()

    await waitFor(() => {
      expect(screen.getByText('正在生成摘要…')).toBeInTheDocument()
    })
  })
})
