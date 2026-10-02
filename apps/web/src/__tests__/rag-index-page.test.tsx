/** R24 RAG 索引页测试。
 *
 * 全部 fetch stub：验证总览数值渲染（全部来自 overview 端点）、失败
 * 警示与单项重试载荷、检索试验命中渲染、删除确认（明示不删原文 +
 * DELETE 调用）。不 mount App（挂载由主 Agent 接线）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RagIndexPage } from '../components/pages/RagIndexPage'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const OVERVIEW = {
  enabled: true,
  modelId: 'BAAI/bge-small-zh-v1.5',
  dim: 512,
  configuredModel: 'BAAI/bge-small-zh-v1.5',
  documents: 3,
  chunks: 7,
  sources: [{ kind: 'clip', corpusDocs: 3, indexedDocs: 3, chunks: 7 }],
  excludedFeeds: 1,
  aiDisabledFeeds: 0,
  lastUpdatedAt: '2026-10-01T08:00:00+00:00',
  lastRebuildAt: '2026-10-01T07:00:00+00:00',
  lastError: null,
  storage: { basis: 'dbstat', vecBytes: 14336, chunkBytes: 8192, totalBytes: 22528 },
  queue: { pending: 1, done: 3, failed: 2, stale: 0 },
  failures: [
    { ref: 'library:gone-a', reason: '重建期间来源已删除，已跳过', at: '2026-10-01T07:00:00+00:00' },
    { ref: 'library:gone-b', reason: '重建期间来源已删除，已跳过', at: '2026-10-01T07:00:00+00:00' },
  ],
  incrementalPaused: false,
  calendarPaused: false,
  vecTable: true,
  fastembedAvailable: true,
  job: null,
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>

function renderPage(handler: Handler) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
    handler(String(input), init),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={queryClient}>
      <RagIndexPage />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('RagIndexPage 总览', () => {
  it('总览数值全部来自 overview 端点并渲染进度条', async () => {
    renderPage((url) => {
      if (url.endsWith('/rag/index/overview')) return jsonResponse(OVERVIEW)
      return jsonResponse({ error: { type: 'not_found', message: 'unexpected ' + url } }, 404)
    })

    await waitFor(() => {
      expect(screen.getByText('索引总览')).toBeTruthy()
    })
    expect(screen.getByText('7')).toBeTruthy() // 分块
    expect(screen.getByText(/BAAI\/bge-small-zh-v1.5（512 维）/)).toBeTruthy()
    expect(
      screen.getByText(/待处理 1 · 已完成 3/, { selector: '[data-rag-index-queue]' }),
    ).toBeTruthy()
    expect(screen.getByText(/失败 2/).textContent).toContain('失败 2')
    expect(screen.getByText(/22 KB/)).toBeTruthy() // 磁盘占用（dbstat 实测）
    expect(screen.getByLabelText('索引队列进度')).toBeTruthy()
  })

  it('未启用且无索引时空态 + 去设置入口', async () => {
    renderPage((url) => {
      if (url.endsWith('/rag/index/overview')) {
        return jsonResponse({ ...OVERVIEW, enabled: false, documents: 0, chunks: 0 })
      }
      return jsonResponse({ error: { type: 'not_found', message: 'unexpected' } }, 404)
    })
    await waitFor(() => {
      expect(screen.getByText('语义索引未启用')).toBeTruthy()
    })
    expect(screen.getByRole('button', { name: '去设置启用' })).toBeTruthy()
  })

  it('overview 加载失败时错误态可重试', async () => {
    renderPage(() =>
      jsonResponse({ error: { type: 'request_failed', message: 'boom' } }, 500),
    )
    await waitFor(() => {
      expect(screen.getByText('索引总览加载失败')).toBeTruthy()
    })
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
  })
})

describe('RagIndexPage 失败项', () => {
  it('失败计数 > 0 时显式警示「处理完任务 ≠ 全部成功」', async () => {
    renderPage((url) => {
      if (url.endsWith('/rag/index/overview')) return jsonResponse(OVERVIEW)
      return jsonResponse({ error: { type: 'not_found', message: 'unexpected' } }, 404)
    })
    await waitFor(() => {
      expect(screen.getByText('处理完成 ≠ 全部成功：2 项失败')).toBeTruthy()
    })
    expect(screen.getByText('library:gone-a')).toBeTruthy()
    expect(screen.getAllByText('重建期间来源已删除，已跳过').length).toBe(2)
  })

  it('失败项为 0 时不渲染失败区块', async () => {
    renderPage((url) => {
      if (url.endsWith('/rag/index/overview')) {
        return jsonResponse({
          ...OVERVIEW,
          queue: { pending: 0, done: 3, failed: 0, stale: 0 },
          failures: [],
        })
      }
      return jsonResponse({ error: { type: 'not_found', message: 'unexpected' } }, 404)
    })
    await waitFor(() => {
      expect(screen.getByText('索引总览')).toBeTruthy()
    })
    expect(screen.queryByText(/处理完成 ≠ 全部成功/)).toBeNull()
  })

  it('单项重试只带该失败 ref，全部重试不带 refs', async () => {
    const fetchMock = renderPage((url) => {
      if (url.endsWith('/rag/index/overview')) return jsonResponse(OVERVIEW)
      if (url.endsWith('/rag/index/retry-failed')) {
        return jsonResponse({ requested: 1, updated: 1, chunks: 2, missing: [] })
      }
      return jsonResponse({ error: { type: 'not_found', message: 'unexpected' } }, 404)
    })

    await waitFor(() => {
      expect(screen.getByText('处理完成 ≠ 全部成功：2 项失败')).toBeTruthy()
    })
    const row = screen.getByText('library:gone-a').closest('li')
    const retryButton = row?.querySelector('button')
    expect(retryButton).toBeTruthy()
    fireEvent.click(retryButton as Element)

    await waitFor(() => {
      const retryCalls = fetchMock.mock.calls.filter(
        ([u]) => String(u).endsWith('/rag/index/retry-failed'),
      )
      expect(retryCalls.length).toBe(1)
      expect(JSON.parse(String(retryCalls[0][1]?.body))).toEqual({ refs: ['library:gone-a'] })
    })
    expect(screen.getByText('请求 1 项，成功 1 项')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '全部重试' }))
    await waitFor(() => {
      const retryCalls = fetchMock.mock.calls.filter(
        ([u]) => String(u).endsWith('/rag/index/retry-failed'),
      )
      expect(retryCalls.length).toBe(2)
      expect(JSON.parse(String(retryCalls[1][1]?.body))).toEqual({})
    })
  })
})

describe('RagIndexPage 检索试验', () => {
  it('输入 query 检索后渲染命中分数与内容预览', async () => {
    renderPage((url) => {
      if (url.endsWith('/rag/index/overview')) return jsonResponse(OVERVIEW)
      if (url.includes('/rag/search')) {
        return jsonResponse({
          items: [
            {
              ref: 'library:hit-1',
              kind: 'clip',
              text: '命中分块的内容预览文本。',
              score: 0.032,
              title: '量化部署笔记',
            },
          ],
          semanticUsed: true,
          semanticError: null,
        })
      }
      return jsonResponse({ error: { type: 'not_found', message: 'unexpected' } }, 404)
    })

    await waitFor(() => {
      expect(screen.getByText('检索试验')).toBeTruthy()
    })
    fireEvent.change(screen.getByLabelText('试检索查询'), {
      target: { value: '量化' },
    })
    fireEvent.click(screen.getByRole('button', { name: '检索' }))

    await waitFor(() => {
      expect(screen.getByText('量化部署笔记')).toBeTruthy()
    })
    expect(screen.getByText(/命中分块的内容预览文本。/)).toBeTruthy()
    expect(screen.getByText(/0\.032/)).toBeTruthy() // 分数原样展示，绝不编造
  })
})

describe('RagIndexPage 删除索引', () => {
  it('确认框明示不删原文；确认后发起 DELETE 且不带原文路径', async () => {
    const fetchMock = renderPage((url, init) => {
      if (url.endsWith('/rag/index/overview')) return jsonResponse(OVERVIEW)
      if (url.endsWith('/rag/index') && (init?.method ?? '') === 'DELETE') {
        return jsonResponse({ removedChunks: 7, removedVecRows: 7 })
      }
      return jsonResponse({ error: { type: 'not_found', message: 'unexpected' } }, 404)
    })

    await waitFor(() => {
      expect(screen.getByText('索引总览')).toBeTruthy()
    })
    // jsdom 恒为移动档：工具行动作收进「更多」菜单，先展开再点删除。
    fireEvent.click(screen.getByRole('button', { name: '更多' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '删除索引' }))

    // 明示「原文不会被删除」的承诺文案必须出现；对话框 footer 的确认按钮。
    expect(screen.getByText(/原文不会被删除/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '删除索引' }))

    await waitFor(() => {
      const del = fetchMock.mock.calls.find(
        ([u, init]) => String(u).endsWith('/rag/index') && (init?.method ?? '') === 'DELETE',
      )
      expect(del).toBeTruthy()
    })
    // 删除成功后总览被失效重取（overview 再次请求发生）。
    const overviewCalls = fetchMock.mock.calls.filter(
      ([u]) => String(u).endsWith('/rag/index/overview'),
    )
    expect(overviewCalls.length).toBeGreaterThanOrEqual(2)
  })
})
