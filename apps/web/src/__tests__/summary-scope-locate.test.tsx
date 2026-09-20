/** F025 输入预览 + F026 摘要证据定位（util 与组件两态）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReaderSummary from '../components/ReaderSummary'
import { locateSentence, splitSentences } from '../lib/locate-sentence'

const ENTRY_REF = 'e1.aWVtLTI'

const BODY =
  '第一段讲背景。这里出现了独特的锚点句：量子纠缠是核心概念。第二段展开论述。' +
  '更多的正文内容，让文本足够长以验证定位与计数。'

let summaryState = 'not_generated'

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/summary')) {
    if (summaryState === 'not_generated') {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            status: 'not_generated',
            summary: null,
            provider: 'openai',
            model: 'm',
            promptVersion: 'v',
            language: 'zh-CN',
            generatedAt: null,
            failureType: null,
            cached: false,
            inputChars: null,
            truncated: false,
            versions: [],
            activeVersionId: null,
          }),
          { status: 200 },
        ),
      )
    }
    return Promise.resolve(
      new Response(
        JSON.stringify({
          status: 'success',
          summary: '量子纠缠是核心概念。第二句不存在于原文的说法。',
          provider: 'openai',
          model: 'm',
          promptVersion: 'v',
          language: 'zh-CN',
          generatedAt: '2026-09-19T00:00:00Z',
          failureType: null,
          cached: true,
          inputChars: 2000,
          truncated: true,
          versions: [],
          activeVersionId: null,
        }),
        { status: 200 },
      ),
    )
  }
  if (method === 'POST' && url.includes('/summary')) {
    const body = JSON.parse(String(init?.body ?? '{}'))
    expect(body.maxChars).toBe(4000)
    summaryState = 'success'
    return Promise.resolve(
      new Response(
        new Response(JSON.stringify({})).body ? JSON.stringify({
          status: 'success',
          summary: '量子纠缠是核心概念。',
          provider: 'openai',
          model: 'm',
          promptVersion: 'v',
          language: 'zh-CN',
          generatedAt: '2026-09-19T00:00:00Z',
          failureType: null,
          cached: false,
          inputChars: 4000,
          truncated: true,
          versions: [],
          activeVersionId: null,
        }) : '{}',
        { status: 200 },
      ),
    )
  }
  return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
})

function renderCard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ReaderSummary entryRef={ENTRY_REF} articleTitle="标题文本" articleText={BODY} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockClear()
  summaryState = 'not_generated'
  vi.stubGlobal('fetch', fetchMock)
})

describe('F025 AI 输入预览与范围控制', () => {
  it('F025: 预览显示标题/正文字符数与诚实口径；范围选择进入请求', async () => {
    renderCard()
    expect(await screen.findByText(/标题 4 字符 · 正文 \d+ 字符/)).toBeInTheDocument()
    expect(screen.getByText(/token 计数以 Provider 为准/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('输入范围'), { target: { value: '4000' } })
    fireEvent.click(screen.getByRole('button', { name: /AI 摘要/ }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('/summary') && init?.method === 'POST')).toBe(true)
    })
  })

  it('F025: 默认不点生成 → 零请求发出', async () => {
    renderCard()
    await screen.findByText(/token 计数以 Provider 为准/)
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })
})

describe('F026 摘要证据定位', () => {
  it('F026 util: 中文命中、重复句取第一处、空白/全半角差异、失配 -1', () => {
    expect(locateSentence('量子纠缠是核心概念。', BODY)).toBeGreaterThanOrEqual(0)
    expect(locateSentence('重复句。重复句。', '重复句。重复句。')).toBe(0)
    expect(locateSentence(' Quantum\uff26\uff25 todo ', 'xx QuantumFE todo yy')).toBeGreaterThanOrEqual(3)
    expect(locateSentence('正文更新后失配的句子。', BODY)).toBe(-1)
    expect(splitSentences('第一句。第二句！第三句？')).toEqual(['第一句。', '第二句！', '第三句？'])
  })

  it('F026 组件: 命中句派发定位事件；失配句显示诚实徽标', async () => {
    summaryState = 'success'
    renderCard()
    const hit = await screen.findByText('量子纠缠是核心概念。')
    const listener = vi.fn()
    document.addEventListener('lumi:locate-evidence', listener)
    fireEvent.click(hit)
    expect(listener).toHaveBeenCalledTimes(1)
    const detail = (listener.mock.calls[0][0] as CustomEvent).detail
    expect(detail.sentence).toBe('量子纠缠是核心概念。')
    document.removeEventListener('lumi:locate-evidence', listener)

    // 失配句：诚实徽标，不臆造
    fireEvent.click(screen.getByText('第二句不存在于原文的说法。'))
    expect(screen.getByText('未在原文定位')).toBeInTheDocument()
  })
})
