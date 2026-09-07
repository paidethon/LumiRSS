/** Gate — ReaderTranslation 三模式行为契约。
 *
 * 所有 fetch 全部 stub：零网络。重点验证（钱规则）：
 * - 原文模式：零翻译请求（打开页面不付翻译钱）；
 * - 切到双语 = 显式动作：lookup → 未生成块自动 generate 一次，
 *   译文以纯文本节点插入（不进 HTML 路径），原文保留成对；
 * - 精确缓存命中：不发出 generate；
 * - bilingual ↔ translated 纯排版切换：零额外请求；
 * - 失败块：状态栏如实展示，重试只送失败块；
 * - 旧的正文内“原文/译文”切换控件不存在（控件在工具栏）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReaderTranslation from '../components/ReaderTranslation'
import type { EntryDetail } from '../api/types'
import type { ReaderViewMode } from '../lib/translation-blocks'

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

const AI_SETTINGS = {
  provider: 'openai_compatible',
  baseUrl: 'http://127.0.0.1:9999/v1',
  model: 'model-a',
  summaryLanguage: 'zh-CN',
  translationLanguage: 'zh-CN',
  translationEngine: 'ai',
  libretranslateUrl: '',
  libretranslateKeyConfigured: false,
  configured: false,
  envKeyConfigured: false,
  defaultKeyConfigured: false,
  purposes: {},
  purposeStatus: {},
}

const LOOKUP_URL = `/api/v1/entries/${REF}/translation/segments/lookup`
const GENERATE_URL = `/api/v1/entries/${REF}/translation/segments/generate`

function segment(index: number, status: string, extra: Record<string, unknown> = {}) {
  return { index, status, translatedText: null, failureType: null, cached: false, ...extra }
}

function Harness({ mode }: { mode: ReaderViewMode }) {
  return <ReaderTranslation detail={detail()} viewMode={mode} />
}

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const calls: { url: string; method: string; body: unknown }[] = []
  const fetchMock = vi.fn()
  return { queryClient, calls, fetchMock }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ReaderTranslation 三模式', () => {
  it('原文模式：渲染原文，零翻译请求（无 lookup / generate）', async () => {
    const { queryClient, calls, fetchMock } = setup()
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), method: init?.method ?? 'GET', body: null })
      if (String(input) === '/api/v1/settings/ai') return Promise.resolve(jsonResponse(AI_SETTINGS))
      return Promise.resolve(jsonResponse({ error: { type: 'not_found', message: 'x' } }, 404))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <QueryClientProvider client={queryClient}>
        <Harness mode="original" />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText('原始正文内容。')).toBeInTheDocument()
    })
    await new Promise((r) => setTimeout(r, 250))
    const translateCalls = calls.filter((c) => c.url.includes('/translation'))
    expect(translateCalls).toEqual([])
    // 正文内不再有旧的语言切换控件（控件在 ReaderHeader 工具栏）
    expect(screen.queryByRole('group', { name: '文章语言视图' })).toBeNull()
  })

  it('切到双语：lookup → 自动 generate 一次 → 译文纯文本成对插入', async () => {
    const { queryClient, calls, fetchMock } = setup()
    let generated = false
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
      if (url === '/api/v1/settings/ai') return Promise.resolve(jsonResponse(AI_SETTINGS))
      if (url === LOOKUP_URL && method === 'POST') {
        if (!generated) {
          return Promise.resolve(
            jsonResponse({ engine: 'ai', targetLanguage: 'zh-CN', segments: [segment(0, 'not_generated')] }),
          )
        }
        return Promise.resolve(
          jsonResponse({
            engine: 'ai',
            targetLanguage: 'zh-CN',
            segments: [segment(0, 'success', { translatedText: '第一段译文。', cached: false })],
          }),
        )
      }
      if (url === GENERATE_URL && method === 'POST') {
        generated = true
        return Promise.resolve(
          jsonResponse({
            engine: 'ai',
            targetLanguage: 'zh-CN',
            segments: [segment(0, 'success', { translatedText: '第一段译文。' })],
          }),
        )
      }
      throw new Error(`unexpected fetch: ${url} ${method}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <Harness mode="original" />
      </QueryClientProvider>,
    )
    rerender(
      <QueryClientProvider client={queryClient}>
        <Harness mode="bilingual" />
      </QueryClientProvider>,
    )

    // 译文以纯文本出现（textContent 注入）
    await waitFor(() => {
      expect(screen.getByText('第一段译文。')).toBeInTheDocument()
    }, { timeout: 3000 })
    // 原文保留（双语成对）
    expect(screen.getByText('原始正文内容。')).toBeInTheDocument()
    // 注入的译文节点不包含任何 HTML（textContent only）
    const translationNode = screen.getByText('第一段译文。')
    expect(translationNode.getAttribute('data-lb-t')).toBe('1')
    // 正好一次 generate（显式动作一次）
    await waitFor(() => {
      const generateCalls = calls.filter((c) => c.url === GENERATE_URL)
      expect(generateCalls.length).toBe(1)
    })
    // 状态栏标注执行位置
    expect(screen.getByText(/AI 翻译（AI 提供者执行）/)).toBeInTheDocument()
  }, 15000)

  it('精确缓存命中：无 generate；纯排版切换（双语↔译文）零额外请求', async () => {
    const { queryClient, calls: calls, fetchMock } = setup()
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      calls.push({ url, method, body: null })
      if (url === '/api/v1/settings/ai') return Promise.resolve(jsonResponse(AI_SETTINGS))
      if (url === LOOKUP_URL && method === 'POST') {
        return Promise.resolve(
          jsonResponse({
            engine: 'ai',
            targetLanguage: 'zh-CN',
            segments: [segment(0, 'success', { translatedText: '缓存译文。', cached: true })],
          }),
        )
      }
      throw new Error(`unexpected fetch: ${url} ${method}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <Harness mode="bilingual" />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText('缓存译文。')).toBeInTheDocument()
    }, { timeout: 3000 })
    expect(screen.getByText('缓存')).toBeInTheDocument()
    const callsAfterBilingual = calls.filter((c) => c.url.includes('/translation')).length
    expect(callsAfterBilingual).toBe(1) // 只有 lookup，无 generate

    // 纯排版切换：bilingual → translated
    rerender(
      <QueryClientProvider client={queryClient}>
        <Harness mode="translated" />
      </QueryClientProvider>,
    )
    await waitFor(() => {
      // 仅译文模式：原文块被隐藏
      const original = screen.getByText('原始正文内容。')
      expect(original.style.display).toBe('none')
    })
    expect(screen.getByText('缓存译文。')).toBeInTheDocument()
    const callsAfterSwitch = calls.filter((c) => c.url.includes('/translation')).length
    expect(callsAfterSwitch).toBe(1) // 零新增请求
  }, 15000)

  it('失败块：状态栏展示 + 只重试失败段（body 只含失败块）', async () => {
    const { queryClient, fetchMock } = setup()
    let retried = false
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/settings/ai') return Promise.resolve(jsonResponse(AI_SETTINGS))
      if (url === LOOKUP_URL && method === 'POST') {
        if (!retried) {
          return Promise.resolve(
            jsonResponse({
              engine: 'ai',
              targetLanguage: 'zh-CN',
              segments: [segment(0, 'failed', { failureType: 'rate_limited' })],
            }),
          )
        }
        return Promise.resolve(
          jsonResponse({
            engine: 'ai',
            targetLanguage: 'zh-CN',
            segments: [segment(0, 'success', { translatedText: '第二段已补译。' })],
          }),
        )
      }
      if (url === GENERATE_URL && method === 'POST') {
        retried = true
        const body = JSON.parse(String(init?.body))
        // 只送失败块（index 0；成功块不重送）
        expect(body.blocks.map((b: { index: number }) => b.index)).toEqual([0])
        return Promise.resolve(
          jsonResponse({
            engine: 'ai',
            targetLanguage: 'zh-CN',
            segments: [segment(1, 'success', { translatedText: '第二段已补译。' })],
          }),
        )
      }
      throw new Error(`unexpected fetch: ${url} ${method}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <QueryClientProvider client={queryClient}>
        <Harness mode="bilingual" />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText(/1 段失败/)).toBeInTheDocument()
    }, { timeout: 3000 })
    fireEvent.click(screen.getByRole('button', { name: /只重试失败段/ }))
    await waitFor(() => {
      expect(screen.getByText('第二段已补译。')).toBeInTheDocument()
    }, { timeout: 3000 })
  }, 15000)
})
