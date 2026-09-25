/** N085/N084 修订面板 —— 修订历史（恢复上一版）与翻译提供方对照。
 *
 * 覆盖：
 * - N085：有历史时显示「恢复上一版」+ 可恢复版数（诚实提示）；点击
 *   调 restore 端点并刷新草稿与历史；无历史时按钮诚实隐藏；
 * - N084：对照按钮 → POST translation-compare（原文块）→ 并排两侧
 *   文本 + 成本口径 chars×2；「采用此版」经既有修订端点显式写入
 *   （只写所选块，其它段零请求）；available=false 时给诚实原因；
 * - 全部对照文本按纯文本渲染（危险 HTML 不被解析）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TranslationRevisionPanel from '../components/TranslationRevisionPanel'
import type { TranslationSegmentState } from '../api/types'
import type { ArticleBlock } from '../lib/translation-blocks'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function makeSegments(): TranslationSegmentState[] {
  return [
    {
      index: 0,
      status: 'success',
      translatedText: '第零段译文。',
      cached: true,
      revisionStale: false,
      noTranslate: false,
      protectedTerms: [],
    },
    {
      index: 1,
      status: 'success',
      translatedText: '第一段译文。',
      cached: true,
      revisionStale: false,
      noTranslate: false,
      protectedTerms: [],
    },
  ]
}

const BLOCKS: ArticleBlock[] = [
  { index: 0, text: 'Source zero.' },
  { index: 1, text: 'Source one.' },
]

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <TranslationRevisionPanel entryRef="e1.n085" segments={makeSegments()} blocks={BLOCKS} />
    </QueryClientProvider>,
  )
}

function openEditor() {
  fireEvent.click(screen.getByRole('button', { name: /译文修订/ }))
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('N085 修订历史（恢复上一版）', () => {
  it('有历史：显示 恢复上一版 + 版数提示；点击调 restore 端点并刷新草稿', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/revision/history')) {
        return Promise.resolve(
          jsonResponse({
            index: 0,
            items: [
              { oldText: '上一版修订文本。', replacedAt: '2026-01-02T00:00:00Z' },
            ],
          }),
        )
      }
      if (url.endsWith('/revision/restore')) {
        return Promise.resolve(
          jsonResponse({
            index: 0,
            userRevision: '上一版修订文本。',
            revisedAt: '2026-01-03T00:00:00Z',
            revisionStale: false,
          }),
        )
      }
      return Promise.resolve(jsonResponse({ index: 0, items: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()
    openEditor()

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.n085/translation/segments/0/revision/history',
        expect.anything(),
      )
    })
    const restore = await screen.findByRole('button', { name: /恢复上一版/ })
    expect(screen.getByText(/可恢复的版本共 1 版/)).toBeInTheDocument()

    fireEvent.click(restore)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.n085/translation/segments/0/revision/restore',
        expect.anything(),
      )
    })
    // 恢复出的上一版成为当前草稿
    const textarea = await screen.findByLabelText('第 1 段译文修订')
    await waitFor(() => {
      expect((textarea as HTMLTextAreaElement).value).toBe('上一版修订文本。')
    })
  })

  it('无历史：恢复按钮诚实隐藏（不出现空操作入口）', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ index: 0, items: [] })),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()
    openEditor()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })
    expect(screen.queryByRole('button', { name: /恢复上一版/ })).toBeNull()
    expect(screen.queryByText(/可恢复的版本/)).toBeNull()
  })
})

describe('N084 翻译提供方对照', () => {
  it('两个提供方：POST compare（原文块）→ 并排两侧 + 成本口径；采用此版只写该块', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/revision/history')) {
        return Promise.resolve(jsonResponse({ index: 0, items: [] }))
      }
      if (url.endsWith('/translation-compare')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as { blockIndex: number; text: string }
        expect(body.blockIndex).toBe(0)
        expect(body.text).toBe('Source zero.')
        return Promise.resolve(
          jsonResponse({
            available: true,
            reason: null,
            estimatedChars: body.text.length * 2,
            sides: [
              { label: '翻译引擎', provider: 'ai', model: 'trans-m', text: '引擎译文。', failureType: null },
              { label: 'AI Profile（chat 用途）', provider: 'ai', model: 'chat-m', text: 'Profile译文。', failureType: null },
            ],
          }),
        )
      }
      if (url.endsWith('/revision')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as { text: string }
        return Promise.resolve(
          jsonResponse({
            index: 0,
            userRevision: body.text,
            revisedAt: '2026-01-03T00:00:00Z',
            revisionStale: false,
          }),
        )
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()
    openEditor()

    fireEvent.click(await screen.findByRole('button', { name: /对照/ }))
    expect(await screen.findByText('引擎译文。')).toBeInTheDocument()
    expect(screen.getByText('Profile译文。')).toBeInTheDocument()
    expect(screen.getByText(/约发送 24 字符/)).toBeInTheDocument()

    // 采用此版：显式写入所选块（只有该块的 revision PUT）
    fireEvent.click(screen.getAllByRole('button', { name: '采用此版' })[0]!)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.n085/translation/segments/0/revision',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
    const puts = fetchMock.mock.calls.filter(
      (call) => String(call[0]).endsWith('/revision') && (call[1] as RequestInit | undefined)?.method === 'PUT',
    )
    expect(puts).toHaveLength(1)
    expect(JSON.parse(String((puts[0]![1] as RequestInit).body))).toEqual({
      text: '引擎译文。',
    })
  })

  it('只有一个提供方可用：诚实原因（不假装对照）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/revision/history')) {
        return Promise.resolve(jsonResponse({ index: 0, items: [] }))
      }
      if (url.endsWith('/translation-compare')) {
        return Promise.resolve(
          jsonResponse({
            available: false,
            reason: 'providers_identical',
            sides: [],
            estimatedChars: 0,
          }),
        )
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()
    openEditor()
    fireEvent.click(await screen.findByRole('button', { name: /对照/ }))
    expect(await screen.findByText(/两个用途解析到同一提供方/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '采用此版' })).toBeNull()
  })

  it('对照文本纯文本渲染：危险 HTML 不被解析', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/revision/history')) {
        return Promise.resolve(jsonResponse({ index: 0, items: [] }))
      }
      if (url.endsWith('/translation-compare')) {
        return Promise.resolve(
          jsonResponse({
            available: true,
            reason: null,
            estimatedChars: 30,
            sides: [
              {
                label: '翻译引擎',
                provider: 'ai',
                model: 'm',
                text: '<img src=x onerror=alert(1)>安全文本',
                failureType: null,
              },
              { label: 'AI Profile（chat 用途）', provider: 'ai', model: 'm2', text: '另一版。', failureType: null },
            ],
          }),
        )
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const { container } = renderPanel()
    openEditor()
    fireEvent.click(await screen.findByRole('button', { name: /对照/ }))
    expect(await screen.findByText(/安全文本/)).toBeInTheDocument()
    // <img> 没有被解析成元素，只是文本内容
    expect(container.querySelector('img')).toBeNull()
  })
})
