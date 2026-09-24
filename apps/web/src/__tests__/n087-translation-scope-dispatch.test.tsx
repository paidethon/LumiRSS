/** N087 派发与取消 —— fetch mock 计数：
 * - 范围派发只送所选块（请求体逐批核对，未选块零请求）；
 * - 取消中止在途批次且不再派发后续批次（真停止请求，不只是隐藏 UI）；
 * - TranslationScopeBar 显示预计字符量并触发/取消派发。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TranslationQueue, defaultQueueSend } from '../lib/translation-scope'
import { TranslationScopeBar } from '../components/TranslationScopeBar'
import type { ArticleBlock } from '../lib/translation-blocks'
import type { ScopeSelection } from '../lib/translation-scope'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function makeBlocks(count: number, text = 'x'.repeat(40)): ArticleBlock[] {
  return Array.from({ length: count }, (_, i) => ({ index: i, text }))
}

function generateBodies(fetchMock: ReturnType<typeof vi.fn>): number[][] {
  return fetchMock.mock.calls
    .filter(([url]) => String(url).includes('/translation/segments/generate'))
    .map(([, init]) => (JSON.parse(String((init as RequestInit).body)) as { blocks: Array<{ index: number }> }).blocks.map((b) => b.index))
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('N087 TranslationQueue（fetch 计数）', () => {
  it('只发送所选块：分批顺序请求，请求体合并后恰为所选块', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ segments: [] })),
    )
    vi.stubGlobal('fetch', fetchMock)
    const selected = makeBlocks(19) // → 3 批（8/8/3）
    const queue = new TranslationQueue(defaultQueueSend('e1.n087'))
    const result = await queue.run(selected)

    expect(result.cancelled).toBe(false)
    expect(result.dispatched).toBe(3)
    const generateCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes('/translation/segments/generate'),
    )
    expect(generateCalls).toHaveLength(3)
    const sent = generateBodies(fetchMock).flat()
    expect(sent).toEqual(selected.map((b) => b.index))
  })

  it('未选中的块绝不产生远程请求', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ segments: [] })),
    )
    vi.stubGlobal('fetch', fetchMock)
    const queue = new TranslationQueue(defaultQueueSend('e1.n087b'))
    // 只送 2 块（例如“当前章节”），其余 10 块不在请求中。
    await queue.run([makeBlocks(12)[3], makeBlocks(12)[4]])
    const sent = generateBodies(fetchMock).flat()
    expect(sent).toEqual([3, 4])
  })

  it('取消：当前批次中止后不再派发任何后续批次', async () => {
    let calls = 0
    const queue = new TranslationQueue(async (_blocks, signal) => {
      calls += 1
      if (calls === 1) {
        queue.cancel() // 第一批在途时取消
        await Promise.resolve()
        if (signal.aborted) {
          throw new DOMException('The operation was aborted.', 'AbortError')
        }
      }
      await Promise.resolve()
    })
    const result = await queue.run(makeBlocks(19))

    expect(calls).toBe(1) // 第二批从未发出
    expect(result.cancelled).toBe(true)
    expect(result.dispatched).toBe(1)
  })
})

describe('N087 TranslationScopeBar', () => {
  const selection: ScopeSelection = {
    scope: 'chapter',
    blocks: makeBlocks(4),
    chars: 160,
  }

  function renderBar(overrides?: {
    computeSelection?: () => ScopeSelection | null
    scope?: 'all' | 'chapter' | 'toEnd'
  }) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    return render(
      <QueryClientProvider client={queryClient}>
        <TranslationScopeBar
          entryRef="e1.n087c"
          scope={overrides?.scope ?? 'chapter'}
          onScopeChange={() => {}}
          computeSelection={overrides?.computeSelection ?? (() => selection)}
        />
      </QueryClientProvider>,
    )
  }

  it('显示预计字符量；点击派发只发所选块（fetch 计数）', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ segments: [] })),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderBar()

    // 预计字符量在派发前展示
    expect(screen.getByText(/预计约 160 字符 · 4 段/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /翻译所选范围/ }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.n087c/translation/segments/generate',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /翻译所选范围/ }),
      ).toBeInTheDocument()
    })
    // 4 块一批发完：恰一次 generate，请求体恰为所选块
    expect(generateBodies(fetchMock)).toEqual([[0, 1, 2, 3]])
  })

  it('取消 → 第二批请求不再发出（不只是隐藏按钮）', async () => {
    const fetchMock = vi.fn()
    let releaseFirst!: () => void
    const firstBatch = new Promise<void>((resolve) => {
      releaseFirst = resolve
    })
    let calls = 0
    fetchMock.mockImplementation(() => {
      calls += 1
      if (calls === 1) return firstBatch.then(() => jsonResponse({ segments: [] }))
      return Promise.resolve(jsonResponse({ segments: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)

    function slowCompute(): ScopeSelection | null {
      // 12 块 → 2 批；第一批在途时取消
      const blocks = makeBlocks(12)
      return { scope: 'all', blocks, chars: blocks.length * 40 }
    }
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <TranslationScopeBar
          entryRef="e1.n087d"
          scope="all"
          onScopeChange={() => {}}
          computeSelection={slowCompute}
        />
      </QueryClientProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: /翻译所选范围/ }))
    // 第一批 fetch 已发出（正在等待 release）
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })
    // 取消 → 第二批的请求不再发出
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))
    releaseFirst()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /翻译所选范围/ })).toBeInTheDocument()
    })
    expect(generateBodies(fetchMock)).toHaveLength(1)
  })

  it('选取为空 → 派发按钮禁用', () => {
    renderBar({ computeSelection: () => null })
    expect(screen.getByRole('button', { name: /翻译所选范围/ })).toBeDisabled()
  })
})
