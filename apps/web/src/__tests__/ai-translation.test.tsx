/** 0016 — ReaderTranslation 状态机测试。
 *
 * 所有 fetch 全部 stub：零网络。重点验证：
 * - 默认原文视图（ArticleContent 渲染原文，译文 GET 只读）；
 * - 切到「译文」触发唯一 POST → 渲染译文标题 + 纯文本正文 + 缓存徽标；
 * - 缓存命中（cached=true）不再发出 POST；
 * - failed → 错误 + 重试；原文随时可切回（原文不因 AI 失败受影响）；
 * - not_configured / content 不可用诚实呈现。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReaderTranslation from '../components/ReaderTranslation'
import type { EntryDetail } from '../api/types'

const REF = 'e1.a'

function detail(): EntryDetail {
  return {
    entryRef: REF,
    title: '原始标题',
    feedTitle: '测试源',
    author: null,
    url: null,
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '原始正文内容。',
    contentHtml: null,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const TRANSLATION_BODY = {
  status: 'not_generated',
  translatedTitle: null,
  translatedText: null,
  provider: 'openai_compatible',
  model: 'model-a',
  promptVersion: 'translation-v1',
  targetLanguage: 'zh-CN',
  generatedAt: null,
  failureType: null,
  cached: false,
}

function renderTranslation(queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})) {
  return render(
    <QueryClientProvider client={queryClient}>
      <ReaderTranslation detail={detail()} />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ReaderTranslation', () => {
  it('默认原文视图：渲染原文内容，译文 GET 只读（无 POST）', async () => {
    let postCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          postCount += 1
        }
        if (url === `/api/v1/entries/${REF}/translation`) {
          return Promise.resolve(jsonResponse(TRANSLATION_BODY))
        }
        throw new Error(`unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
      }),
    )

    renderTranslation()

    await waitFor(() => {
      expect(screen.getByText('原始正文内容。')).toBeInTheDocument()
    })
    expect(postCount).toBe(0)
    expect(screen.getByRole('button', { name: '原文' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('切到「译文」→ 唯一 POST → 渲染译文标题 + 纯文本正文', async () => {
    let postCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          postCount += 1
          return Promise.resolve(
            jsonResponse({
              ...TRANSLATION_BODY,
              status: 'success',
              translatedTitle: '翻译标题',
              translatedText: '翻译正文。',
              generatedAt: '2026-09-03T10:00:00+00:00',
              cached: false,
            }),
          )
        }
        if (url === `/api/v1/entries/${REF}/translation`) {
          return Promise.resolve(jsonResponse(TRANSLATION_BODY))
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )

    renderTranslation()

    fireEvent.click(await screen.findByRole('button', { name: '译文' }))

    await waitFor(() => {
      expect(screen.getByText('翻译标题')).toBeInTheDocument()
    })
    expect(screen.getByText('翻译正文。')).toBeInTheDocument()
    expect(postCount).toBe(1)
    // 原文已切换出视图（不残留）
    expect(screen.queryByText('原始正文内容。')).not.toBeInTheDocument()
    // 缓存徽标不存在（本次为实时生成）
    expect(screen.queryByText('缓存')).not.toBeInTheDocument()
  })

  it('缓存命中（cached=true）：展示译文 + 「缓存」徽标，绝不发出 POST', async () => {
    let postCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          postCount += 1
        }
        if (url === `/api/v1/entries/${REF}/translation`) {
          return Promise.resolve(
            jsonResponse({
              ...TRANSLATION_BODY,
              status: 'success',
              translatedTitle: '缓存翻译标题',
              translatedText: '缓存翻译正文。',
              generatedAt: '2026-09-03T09:00:00+00:00',
              cached: true,
            }),
          )
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )

    renderTranslation()

    fireEvent.click(await screen.findByRole('button', { name: '译文' }))

    await waitFor(() => {
      expect(screen.getByText('缓存翻译正文。')).toBeInTheDocument()
    })
    expect(screen.getByText('缓存')).toBeInTheDocument()
    expect(postCount).toBe(0)
  })

  it('failed 状态：错误 + 显式重试；原文随时可切回不受影响', async () => {
    let mode: 'failed' | 'success' = 'failed'
    let postCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          postCount += 1
          return Promise.resolve(
            jsonResponse({
              ...TRANSLATION_BODY,
              status: 'success',
              translatedTitle: '重试后标题',
              translatedText: '重试后正文。',
              cached: false,
            }),
          )
        }
        if (url === `/api/v1/entries/${REF}/translation`) {
          return Promise.resolve(
            jsonResponse(
              mode === 'failed'
                ? { ...TRANSLATION_BODY, status: 'failed', failureType: 'timeout' }
                : {
                    ...TRANSLATION_BODY,
                    status: 'success',
                    translatedTitle: '重试后标题',
                    translatedText: '重试后正文。',
                    cached: true,
                  },
            ),
          )
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )

    renderTranslation()

    fireEvent.click(await screen.findByRole('button', { name: '译文' }))

    // failed 状态：只呈现错误 + 显式重试，不自动 POST
    await waitFor(() => {
      expect(screen.getByText(/AI 服务响应超时/)).toBeInTheDocument()
    })
    expect(postCount).toBe(0)
    // 原文仍在（切换即可读，不因 AI 失败丢失）
    fireEvent.click(screen.getByRole('button', { name: '原文' }))
    expect(screen.getByText('原始正文内容。')).toBeInTheDocument()

    // 回到译文 → 显式重试成功
    mode = 'success'
    fireEvent.click(screen.getByRole('button', { name: '译文' }))
    fireEvent.click(await screen.findByRole('button', { name: '重试' }))
    await waitFor(() => {
      expect(screen.getByText('重试后正文。')).toBeInTheDocument()
    })
    expect(postCount).toBe(1)
  })

  it('POST 失败（未配置 503）：诚实说明，原文不受影响', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse(
              { error: { type: 'ai_not_configured', message: 'not configured' } },
              503,
            ),
          )
        }
        if (url === `/api/v1/entries/${REF}/translation`) {
          return Promise.resolve(jsonResponse(TRANSLATION_BODY))
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )

    renderTranslation()

    fireEvent.click(await screen.findByRole('button', { name: '译文' }))

    await waitFor(() => {
      expect(screen.getByText(/AI 未配置/)).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: '原文' }))
    expect(screen.getByText('原始正文内容。')).toBeInTheDocument()
  })
})
