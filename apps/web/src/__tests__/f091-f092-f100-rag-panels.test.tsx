/** F091/F092/F100 UI — RAG 设置面板：排除（F066 优先标注+计数预览）、
 * 试检索（无分数显「—」绝不编 %）、一致性扫描+修复。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RagConsistencyPanel, RagExclusionsPanel, RagTrySearchPanel } from '../components/RagW5Panels'

const resolveAndOpenMock = vi.hoisted(() => vi.fn())

vi.mock('../lib/open-item', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/open-item')>()
  return { ...actual, resolveAndOpen: resolveAndOpenMock }
})

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderUi(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F091 RAG 索引排除', () => {
  it('F091: 来源列表（计数预览 + AI 禁用优先标注）→ 排除触发 PUT', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/rag/exclusions')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              { feedUrl: 'https://a.example/feed', ragExcluded: false, aiDisabled: true, affectedChunks: 12 },
              { feedUrl: 'https://b.example/feed', ragExcluded: false, aiDisabled: false, affectedChunks: 3 },
            ],
          }),
        )
      }
      if (method === 'PUT' && url.endsWith('/rag/exclusions')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              { feedUrl: 'https://a.example/feed', ragExcluded: false, aiDisabled: true, affectedChunks: 12 },
              { feedUrl: 'https://b.example/feed', ragExcluded: true, aiDisabled: false, affectedChunks: 3 },
            ],
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<RagExclusionsPanel />)

    expect(await screen.findByText('https://a.example/feed')).toBeInTheDocument()
    expect(screen.getByText('AI 已禁用（优先排除）')).toBeInTheDocument()
    expect(screen.getByText('3 块')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('纳入索引：https://b.example/feed'))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/rag/exclusions') && c[1]?.method === 'PUT')
      expect(put).toBeDefined()
      const body = JSON.parse(String(put?.[1]?.body ?? '{}')) as { feedRef: string; excluded: boolean }
      expect(body).toEqual({ feedRef: 'https://b.example/feed', excluded: true })
    })
  })
})

describe('F092 RAG 试检索', () => {
  it('F092: 结果映射（title/score/text）；无分数显「—」不编 %；未启用诚实提示', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({
          items: [
            { ref: 'library:11111111-1111-4111-8111-111111111111', kind: 'clip', text: '分块正文……', title: '来源标题 A', modelId: 'bge-small' },
            { ref: 'rss:e1.abc', kind: 'entry', text: '另一分块', score: 0.873 },
          ],
          semanticUsed: true,
          semanticError: null,
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { rerender } = renderUi(<RagTrySearchPanel enabled={false} />)
    expect(document.querySelector('[data-try-search-disabled]')).toHaveTextContent(/未启用/)

    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
        <RagTrySearchPanel enabled />
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByLabelText('试检索查询'), { target: { value: '嵌入模型' } })
    fireEvent.click(screen.getByRole('button', { name: '检索' }))

    expect(await screen.findByText('来源标题 A')).toBeInTheDocument()
    // 无分数 → 「—」；有分数 → 原样数值（非 %）。
    expect(screen.getByText('分数 —')).toBeInTheDocument()
    expect(screen.getByText(/分数 0\.873/)).toBeInTheDocument()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()

    // F092：点击命中行 → resolveAndOpen(ref)（resolve 后打开阅读器）。
    fireEvent.click(screen.getByRole('button', { name: '来源标题 A' }))
    expect(resolveAndOpenMock).toHaveBeenCalledWith('library:11111111-1111-4111-8111-111111111111')
  })
})

describe('F100 RAG 版本一致性', () => {
  it('F100: 扫描列表（依据标注）→ 修复所选 → 结果；空态诚实', async () => {
    let hasMismatch = true
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/rag/inconsistencies')) {
        return Promise.resolve(
          jsonResponse({
            modelId: 'bge-small-zh',
            items: hasMismatch
              ? [
                  { ref: 'library:11111111-1111-4111-8111-111111111111', storedHash: 'a1', currentHash: 'b2', basis: 'content_hash' },
                  { ref: 'rss:e1.xyz', storedHash: null, currentHash: null, basis: 'embedding_model' },
                ]
              : [],
          }),
        )
      }
      if (method === 'POST' && url.endsWith('/rag/repair')) {
        hasMismatch = false
        return Promise.resolve(jsonResponse({ repaired: ['library:11111111-1111-4111-8111-111111111111'], failed: [] }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<RagConsistencyPanel />)

    fireEvent.click(screen.getByRole('button', { name: '扫描版本一致性' }))
    await screen.findByText('library:11111111-1111-4111-8111-111111111111')
    expect(screen.getByText('模型切换')).toBeInTheDocument()
    expect(screen.getByText('内容变更')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('选择修复：library:11111111-1111-4111-8111-111111111111'))
    fireEvent.click(screen.getByRole('button', { name: '修复所选（1）' }))
    await waitFor(() => {
      expect(screen.getByText(/成功 1 条/)).toBeInTheDocument()
    })
  })

  it('F100: 无失配空态', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      if (String(input).endsWith('/rag/inconsistencies')) {
        return Promise.resolve(jsonResponse({ modelId: 'bge-small-zh', items: [] }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<RagConsistencyPanel />)

    fireEvent.click(screen.getByRole('button', { name: '扫描版本一致性' }))
    expect(await screen.findByText(/没有版本失配/)).toBeInTheDocument()
  })
})
