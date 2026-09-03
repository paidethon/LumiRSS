/** 0016 — ArticleConversation 文章限定对话面板测试。
 *
 * 所有 fetch 全部 stub：零网络。重点验证：
 * - 打开 → GET 只读（零 POST）；empty → 诚实空态提示；
 * - 提交问题 → 唯一 POST → 用户/助手气泡渲染 + 输入清空；
 * - 失败 → 内联错误、输入保留（可原样重发）、不伪造消息；
 * - 关闭按钮触发 onClose；reopen 恢复历史（GET 返回 active）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ArticleConversation from '../components/ArticleConversation'

const REF = 'e1.a'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const EMPTY_CONVERSATION = { status: 'empty', messages: [] }

const ACTIVE_CONVERSATION = {
  status: 'active',
  messages: [
    { id: 1, role: 'user', content: '这篇文章主要在说什么？', createdAt: '2026-09-03T10:00:00+00:00' },
    { id: 2, role: 'assistant', content: '这篇讲的是……', createdAt: '2026-09-03T10:00:05+00:00' },
  ],
}

function renderConversation({
  open = true,
  onClose = () => {},
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }),
}: {
  open?: boolean
  onClose?: () => void
  queryClient?: QueryClient
} = {}) {
  return render(
    <QueryClientProvider client={queryClient}>
      <ArticleConversation
        entryRef={REF}
        articleTitle="测试文章标题"
        open={open}
        onClose={onClose}
      />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ArticleConversation', () => {
  it('打开 → GET 只读 + 空态提示（无 POST）', async () => {
    let postCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          postCount += 1
        }
        if (url === `/api/v1/entries/${REF}/conversation`) {
          return Promise.resolve(jsonResponse(EMPTY_CONVERSATION))
        }
        throw new Error(`unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
      }),
    )

    renderConversation()

    await waitFor(() => {
      expect(screen.getByText('就当前文章提问')).toBeInTheDocument()
    })
    expect(screen.getByText('针对：测试文章标题')).toBeInTheDocument()
    expect(screen.getByText(/这篇文章主要在说什么/)).toBeInTheDocument()
    expect(postCount).toBe(0)
  })

  it('提交问题 → POST → 用户/助手气泡渲染 + 输入清空', async () => {
    let postBody: unknown = null
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          postBody = JSON.parse(String(init!.body))
          return Promise.resolve(jsonResponse(ACTIVE_CONVERSATION))
        }
        if (url === `/api/v1/entries/${REF}/conversation`) {
          return Promise.resolve(jsonResponse(EMPTY_CONVERSATION))
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )

    renderConversation()

    const input = await screen.findByLabelText('输入问题')
    fireEvent.change(input, { target: { value: '这篇文章主要在说什么？' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      expect(screen.getByText('这篇讲的是……')).toBeInTheDocument()
    })
    expect(screen.getByText('这篇文章主要在说什么？')).toBeInTheDocument()
    expect(postBody).toEqual({ question: '这篇文章主要在说什么？' })
    expect(input).toHaveValue('')
  })

  it('Enter 提交；Shift+Enter 只换行不提交', async () => {
    let postCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          postCount += 1
          return Promise.resolve(jsonResponse(ACTIVE_CONVERSATION))
        }
        if (url === `/api/v1/entries/${REF}/conversation`) {
          return Promise.resolve(jsonResponse(EMPTY_CONVERSATION))
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )

    renderConversation()

    const input = await screen.findByLabelText('输入问题')
    fireEvent.change(input, { target: { value: '问题' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    expect(postCount).toBe(0)
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false })
    await waitFor(() => {
      expect(postCount).toBe(1)
    })
  })

  it('发送失败 → 内联错误 + 输入保留（可直接重发）；无伪造消息', async () => {
    let mode: 'fail' | 'ok' = 'fail'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          if (mode === 'fail') {
            return Promise.resolve(
              jsonResponse(
                { error: { type: 'ai_rate_limited', message: 'rate limited' } },
                429,
              ),
            )
          }
          return Promise.resolve(jsonResponse(ACTIVE_CONVERSATION))
        }
        if (url === `/api/v1/entries/${REF}/conversation`) {
          return Promise.resolve(jsonResponse(EMPTY_CONVERSATION))
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )

    renderConversation()

    const input = await screen.findByLabelText('输入问题')
    fireEvent.change(input, { target: { value: '会被限流的问题' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      expect(screen.getByText(/请求过于频繁/)).toBeInTheDocument()
    })
    // 失败不伪造任何消息，输入保留
    expect(input).toHaveValue('会被限流的问题')
    expect(screen.queryByText('这篇讲的是……')).not.toBeInTheDocument()

    // 直接重发成功
    mode = 'ok'
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => {
      expect(screen.getByText('这篇讲的是……')).toBeInTheDocument()
    })
  })

  it('reopen 恢复历史：GET 返回 active → 消息直接呈现', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        if (String(input) === `/api/v1/entries/${REF}/conversation`) {
          return Promise.resolve(jsonResponse(ACTIVE_CONVERSATION))
        }
        throw new Error(`unexpected fetch: ${String(input)}`)
      }),
    )

    renderConversation()

    await waitFor(() => {
      expect(screen.getByText('这篇讲的是……')).toBeInTheDocument()
    })
    expect(screen.queryByText('就当前文章提问')).not.toBeInTheDocument()
  })

  it('关闭按钮触发 onClose；关闭时不发对话请求', async () => {
    const onClose = vi.fn()
    vi.stubGlobal('fetch', vi.fn())

    const { rerender } = renderConversation({ open: true, onClose })

    fireEvent.click(await screen.findByRole('button', { name: '关闭对话' }))
    expect(onClose).toHaveBeenCalledTimes(1)

    rerender(
      <QueryClientProvider client={new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      })}>
        <ArticleConversation
          entryRef={REF}
          articleTitle="测试文章标题"
          open={false}
          onClose={onClose}
        />
      </QueryClientProvider>,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('面板是 dialog：aria-modal + Escape 关闭（Sheet 原语行为）', async () => {
    const onClose = vi.fn()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(EMPTY_CONVERSATION))),
    )

    renderConversation({ onClose })

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })
})
