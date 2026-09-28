/** FIX-146 — AI 输出与文章身份绑定：切换文章后不串入另一篇。
 *
 * Web 端读者内的 AI 面板没有裸 SSE 流；「生成中逐步产出」的最小等价物
 * 是摘要生成（POST 挂起 → 服务端确认后写回 query cache）。客户端身份
 * 守卫 = 双保险：
 * 1. mutation 在创建时捕获 entryRef（闭包），onSuccess 只写
 *    `['entry-summary', 该 entryRef]`——A 迟到的结果物理上进不了 B；
 * 2. Reader 以 key=entryRef 重挂载面板——A 的 pending/error/result UI
 *    不泄漏到 B。
 *
 * 本套件以确定性时序锁住这两层：A 的生成挂起时切到 B → B 面板无
 * A 的生成态；A 的响应随后才到达 → 只落 A 的缓存，B 的缓存与 UI 不变。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ReaderSummary from '../components/ReaderSummary'
import type { EntrySummary } from '../api/types'

function summaryBody(entryRef: string, status: 'not_generated' | 'success', text?: string): EntrySummary {
  return {
    entryRef,
    status,
    ...(status === 'success' ? { summary: text, cached: false, generatedAt: '2026-09-28T00:00:00Z' } : {}),
  } as unknown as EntrySummary
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-146 AI 摘要按文章身份隔离', () => {
  it('A 生成挂起时切到 B：B 面板无 A 生成态；A 迟到结果只写 A 缓存', async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    // A 的 POST 挂起（手动放行）；其余请求即时返回各自身份的载荷。
    let releaseA: ((body: EntrySummary) => void) | null = null
    const aResult = new Promise<EntrySummary>((resolve) => {
      releaseA = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (url.endsWith('/api/v1/entries/e1.a/summary') && method === 'POST') {
          return aResult.then((body) => jsonResponse(body))
        }
        if (url.endsWith('/api/v1/entries/e1.a/summary')) {
          return Promise.resolve(jsonResponse(summaryBody('e1.a', 'not_generated')))
        }
        if (url.endsWith('/api/v1/entries/e1.b/summary')) {
          return Promise.resolve(jsonResponse(summaryBody('e1.b', 'not_generated')))
        }
        return Promise.resolve(jsonResponse({ items: [] }))
      }),
    )

    const { rerender } = render(
      <QueryClientProvider client={qc}>
        {/* 与 Reader 相同的 key=entryRef 重挂载契约 */}
        <ReaderSummary
          key="summary-e1.a"
          entryRef="e1.a"
          articleTitle="文章甲"
          articleText="甲的正文"
        />
      </QueryClientProvider>,
    )
    // A 就绪后点「AI 摘要」→ 生成挂起
    fireEvent.click(await screen.findByRole('button', { name: 'AI 摘要' }))
    expect(await screen.findByText('正在生成…')).toBeInTheDocument()

    // 切到 B（key 变化 = 重挂载）：B 面板绝不显示 A 的生成态/结果
    rerender(
      <QueryClientProvider client={qc}>
        <ReaderSummary
          key="summary-e1.b"
          entryRef="e1.b"
          articleTitle="文章乙"
          articleText="乙的正文"
        />
      </QueryClientProvider>,
    )
    await screen.findByRole('button', { name: 'AI 摘要' }) // B 的 not_generated UI
    expect(screen.queryByText('正在生成…')).toBeNull()

    // A 的响应此刻才到达：只写 A 的缓存；B 的缓存与 UI 保持自己的状态
    releaseA!(summaryBody('e1.a', 'success', '甲的独有摘要'))
    await waitFor(() => {
      expect(qc.getQueryData<EntrySummary>(['entry-summary', 'e1.a'])?.summary).toBe('甲的独有摘要')
    })
    // B 的缓存只有它自己的状态（GET 所得 not_generated），绝无 A 的摘要
    const bCache = qc.getQueryData<EntrySummary>(['entry-summary', 'e1.b'])
    expect(bCache?.status).toBe('not_generated')
    expect(bCache?.summary).toBeUndefined()
    // B 面板仍未显示 A 的摘要文本
    expect(screen.queryByText('甲的独有摘要')).toBeNull()
    // 挂起的 A 生成按钮不复存在于 B 面板（无「正在生成…」）
    expect(screen.queryByText('正在生成…')).toBeNull()
  })
})
