/** F070 UI — 知识卡片：取消零写入（不发保存请求）、勾选保存逐条状态、
 * 书签页知识卡片管理器（检索/列表/删除）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { KnowledgeCardsPanel } from '../components/KnowledgeCardsPanel'
import { KnowledgeCardsManager } from '../components/KnowledgeCardsManager'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const PREVIEW = {
  entryRef: 'e1.a',
  cards: [
    { concept: '向量检索', explanation: '语义相似度检索。', sourceQuote: '向量检索相关原句内容', verified: true },
    { concept: '关键词腿', explanation: '关键词倒排召回。', sourceQuote: '', verified: false },
  ],
}

const DETAIL = {
  entryRef: 'e1.a',
  title: 'T',
  feedTitle: 'S',
  publishedAt: '2026-09-19T00:00:00Z',
  url: 'https://x/a',
} as never

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <KnowledgeCardsPanel detail={DETAIL} />
    </QueryClientProvider>,
  )
}

function renderManager() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <KnowledgeCardsManager />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F070 知识卡片', () => {
  it('F070: 取消零写入（不调用 save）；勾选保存 → save 载荷只含所选', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL) => {
        if (String(input).endsWith('/save')) {
          return Promise.resolve(
            jsonResponse({ results: [{ concept: '向量检索', status: 'created', cardId: 'kc1' }] }),
          )
        }
        return Promise.resolve(jsonResponse(PREVIEW))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: '知识卡片' }))
    fireEvent.click(screen.getByRole('button', { name: '提取候选卡片' }))
    expect(await screen.findByText('向量检索')).toBeInTheDocument()
    expect(screen.getByText('证据未通过核验')).toBeInTheDocument() // 坏卡片诚实标注

    // 取消：零写入（没有 save 请求），面板收起
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith('/save'))).toBe(false)

    // 重新打开并提取，取消坏卡选择 → save 只含所选
    fireEvent.click(screen.getByRole('button', { name: '知识卡片' }))
    fireEvent.click(screen.getByRole('button', { name: '提取候选卡片' }))
    await screen.findByText('向量检索')
    fireEvent.click(screen.getByLabelText('选择卡片 关键词腿'))
    fireEvent.click(screen.getByRole('button', { name: '保存所选（1）' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith('/save'))).toBe(true)
    })
    const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/save'))
    const body = JSON.parse((call?.[1] as RequestInit).body as string)
    expect(body.cards).toHaveLength(1)
    expect(body.cards[0].concept).toBe('向量检索')
    expect(await screen.findByText(/向量检索：已保存/)).toBeInTheDocument()
  })

  it('F070: 管理器列表（stale 标注）+ 检索 + 删除调用', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        if (method === 'DELETE') {
          return new Response(null, { status: 204 })
        }
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 'kc1',
                entryRef: 'e1.a',
                concept: 'RAG 检索',
                explanation: '双路检索。',
                sourceQuote: '引文句子内容',
                quoteVerified: true,
                createdAt: '2026-09-19T00:00:00Z',
                entryTitle: null,
                stale: true,
              },
            ],
          }),
        )
      })
    vi.stubGlobal('fetch', fetchMock)
    renderManager()

    expect(await screen.findByText('RAG 检索')).toBeInTheDocument()
    expect(screen.getByText('原文已删除')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '跳原文' })).toBeNull() // stale → 不能跳原文
    fireEvent.click(screen.getByRole('button', { name: '删除' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/knowledge-cards/kc1',
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
  })
})
