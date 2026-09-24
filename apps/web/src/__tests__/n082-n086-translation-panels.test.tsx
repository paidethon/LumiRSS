/** N082/N086 面板 —— 数字校验与不翻译标记：
 * - 数字校验：按需 GET、逐块列出差异、诚实文案（基于可见数字差异，
 *   非语义判断）、点击差异定位到对应块；
 * - 不翻译开关：PUT/DELETE 持久到服务端；
 * - 修订与差异上下文一律纯文本渲染（危险 HTML 不被解析）。 */

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

const VERIFICATION = {
  entryRef: 'e1.n082',
  language: 'zh-CN',
  totalFindings: 3,
  blocks: [
    {
      blockIndex: 0,
      verifiable: true,
      revised: false,
      reason: null,
      findings: [
        {
          kind: 'missing',
          token: '45%',
          sourceContext: 'Sales rose 45% in 2023 with 3,50',
          translatedContext: '',
        },
      ],
    },
    {
      blockIndex: 2,
      verifiable: true,
      revised: false,
      reason: null,
      findings: [
        { kind: 'changed', token: '50%', sourceContext: 'grew by 50%.', translatedContext: '增长了 60%。' },
        { kind: 'added', token: '12%', sourceContext: '', translatedContext: '下降了 12%。' },
      ],
    },
    {
      blockIndex: 3,
      verifiable: false,
      revised: true,
      reason: 'user_revised',
      findings: [],
    },
  ],
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
      translatedText: '<img src=x onerror=alert(1)>GraphQL 已保留',
      cached: true,
      revisionStale: false,
      noTranslate: true,
      protectedTerms: [{ term: 'GraphQL', protected: true, count: 1 }],
    },
  ]
}

const BLOCKS: ArticleBlock[] = [
  { index: 0, text: 'Source zero.' },
  { index: 1, text: 'GraphQL source one.' },
]

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <TranslationRevisionPanel entryRef="e1.n082" segments={makeSegments()} blocks={BLOCKS} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('N082 数字校验', () => {
  it('按需校验：GET verification → 差异逐块列出 + 诚实文案 + 点击定位', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse(VERIFICATION)))
    vi.stubGlobal('fetch', fetchMock)
    const { container } = renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /数字校验/ }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.n082/translation-verification',
        expect.objectContaining({ method: 'GET' }),
      )
    })

    // 诚实文案：基于可见数字差异，非语义判断
    expect(screen.getByText(/基于可见数字差异，非语义判断/)).toBeInTheDocument()
    // 三种差异逐条列出（含块定位前缀）
    const findingButtons = Array.from(container.querySelectorAll('button')).filter(
      (b) => /段 ·/.test(b.textContent ?? ''),
    )
    const texts = findingButtons.map((b) => b.textContent ?? '')
    expect(texts.some((t) => /第 1 段 · 缺失 45%/.test(t))).toBe(true)
    expect(texts.some((t) => /第 3 段 · 变动 50%/.test(t))).toBe(true)
    expect(texts.some((t) => /第 3 段 · 新增 12%/.test(t))).toBe(true)
    // 修订块不产生 findings（人类定稿）
    expect(texts.every((t) => !/第 4 段/.test(t))).toBe(true)

    // 点击差异 → 定位到正文第 0 块（[data-reader-body] 里的 data-lb-index=0）
    const body = document.createElement('div')
    body.setAttribute('data-reader-body', '')
    const block = document.createElement('p')
    block.setAttribute('data-lb-index', '0')
    body.appendChild(block)
    document.body.appendChild(body)
    const scrollSpy = Element.prototype.scrollIntoView as ReturnType<typeof vi.fn>
    scrollSpy.mockClear()
    const target = findingButtons.find((b) => /第 1 段 · 缺失 45%/.test(b.textContent ?? ''))
    expect(target).toBeDefined()
    fireEvent.click(target as HTMLElement)
    expect(scrollSpy).toHaveBeenCalledTimes(1)
    expect((scrollSpy.mock.instances.at(-1) as unknown as HTMLElement).getAttribute('data-lb-index')).toBe('0')
    body.remove()
  })

  it('校验失败 → 稳定错误提示，不假成功', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({}, 500)))
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: /数字校验/ }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('数字校验失败，请稍后重试。')
    })
  })
})

describe('N086 不翻译开关', () => {
  it('开启 → PUT no-translate；块已标记 → 显示「已有译文将继续显示」', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(new Response(null, { status: 204 })))
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    // 打开面板并选中已标记段（index 1）
    fireEvent.click(screen.getByRole('button', { name: /译文修订/ }))
    fireEvent.change(screen.getByLabelText('选择要修订的段落'), { target: { value: '1' } })
    expect(screen.getByText('已有译文将继续显示')).toBeInTheDocument()

    // 撤销标记 → DELETE
    fireEvent.click(screen.getByRole('switch', { name: '不翻译此段' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.n082/translation/segments/1/no-translate',
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
  })

  it('未标记段：开启 → PUT；选项列表带「不翻译」徽标', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(new Response(null, { status: 204 })))
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /译文修订/ }))
    expect(screen.getByRole('option', { name: /第 2 段.*（不翻译）/ })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('选择要修订的段落'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('switch', { name: '不翻译此段' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.n082/translation/segments/0/no-translate',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
  })
})

describe('N083 保护报告', () => {
  it('protectedTerms 逐条展示；未保护给原因；危险 HTML 按纯文本渲染', () => {
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: /译文修订/ }))
    fireEvent.change(screen.getByLabelText('选择要修订的段落'), { target: { value: '1' } })

    expect(screen.getByText(/「GraphQL」已保留/)).toBeInTheDocument()
    // 机器原文（含危险 HTML）按纯文本渲染：不存在被解析出的元素
    expect(screen.queryByRole('img')).toBeNull()
    expect(document.querySelector('img')).toBeNull()
  })
})
