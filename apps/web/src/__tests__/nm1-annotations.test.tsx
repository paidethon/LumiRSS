/** NM1 批注/学习六特性 Web 测试 — N071/N073/N074/N075/N076/N077。
 *
 * 环境：jsdom（无 CSS Custom Highlight API，组件降级渲染）；
 * fetch 以 URL 匹配 mock（service 真源在 BFF，后端口径见 BFF 测试）。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AnnotationsLayer from '../components/AnnotationsLayer'
import { AnnotationsManager } from '../components/AnnotationsManager'
import { KnowledgeCardsManager } from '../components/KnowledgeCardsManager'
import {
  ANNOTATIONS_STORAGE_KEY,
  readAllAnnotations,
  type Annotation,
} from '../lib/annotations'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderWithQuery(ui: React.ReactElement): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

function makeArticle(html: string): HTMLElement {
  const div = document.createElement('div')
  div.className = 'lumi-reader-article'
  div.innerHTML = html
  document.body.appendChild(div)
  return div
}

function seedAnnotation(annotation: Annotation): void {
  localStorage.setItem(
    ANNOTATIONS_STORAGE_KEY,
    JSON.stringify([...readAllAnnotations(), annotation]),
  )
}

function serverAnnotation(overrides: Record<string, unknown>): Record<string, unknown> {
  return {
    id: 'a1',
    entryRef: 'e1.a',
    anchor: { paraId: 'block-1', prefix: '', exact: '正文里新的原句在这里', suffix: '' },
    anchorHash: 'newhash',
    excerpt: '正文里新的原句在这里',
    note: '备注',
    color: 'yellow',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-02T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---- N071 修复流 -------------------------------------------------------------

describe('N071 锚点失效修复流', () => {
  it('失效徽章 → 修复定位 → 选定候选 → 重绑并更新本地缓存', async () => {
    makeArticle('<p>开头段。</p><p>重构后正文里新的原句在这里，位置变化。</p>')
    seedAnnotation({
      id: 'a1',
      entryRef: 'e1.a',
      color: 'yellow',
      note: '备注',
      anchor: { prefix: '', exact: '旧的原句已经不存在', suffix: '' },
      createdAt: 1,
      contentVersion: '',
    })
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/repair-candidates')) {
        return Promise.resolve(
          jsonResponse({
            annotationId: 'a1',
            entryRef: 'e1.a',
            quote: '旧的原句已经不存在',
            candidates: [{ blockIndex: 1, score: 1, excerpt: '正文里新的原句在这里' }],
          }),
        )
      }
      if (url.endsWith('/repair')) {
        return Promise.resolve(
          jsonResponse({
            annotation: serverAnnotation({}),
            blockIndex: 1,
            score: 1,
          }),
        )
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AnnotationsLayer entryRef="e1.a" />)
    expect(await screen.findByText(/锚点失效/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '跳回原文' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '修复定位' }))
    const candidate = await screen.findByRole('button', { name: /块 1 · 相似度 100%/ })
    fireEvent.click(candidate)

    await waitFor(() => {
      expect(screen.queryByText(/锚点失效/)).not.toBeInTheDocument()
    })
    // 修复请求使用候选块 + 候选摘录文本
    const repairCall = fetchMock.mock.calls.find(([, init]) =>
      String(init?.body ?? '').includes('blockIndex'),
    )
    expect(repairCall).toBeDefined()
    expect(JSON.parse(String(repairCall![1]?.body))).toEqual({
      blockIndex: 1,
      quoteText: '正文里新的原句在这里',
    })
    // 本地缓存被服务端返回覆盖（anchor 重绑 + 不再失效）
    const stored = readAllAnnotations()
    expect(stored[0]!.anchor.exact).toBe('正文里新的原句在这里')
    expect(stored[0]!.anchor.prefix).toBe('')
    expect(screen.getByRole('button', { name: '跳回原文' })).toBeEnabled()
  })

  it('无候选（低分拒绝）→ 诚实提示手动处理', async () => {
    makeArticle('<p>正文完全变了。</p>')
    seedAnnotation({
      id: 'lost',
      entryRef: 'e1.a',
      color: 'yellow',
      note: '',
      anchor: { prefix: '', exact: '旧的原句已经不存在', suffix: '' },
      createdAt: 1,
      contentVersion: '',
    })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        if (String(input).endsWith('/repair-candidates')) {
          return Promise.resolve(
            jsonResponse({
              annotationId: 'lost',
              entryRef: 'e1.a',
              quote: '旧的原句已经不存在',
              candidates: [],
            }),
          )
        }
        return Promise.resolve(jsonResponse({}, 404))
      }),
    )
    render(<AnnotationsLayer entryRef="e1.a" />)
    fireEvent.click(await screen.findByRole('button', { name: '修复定位' }))
    expect(
      await screen.findByText(/未能在当前原文中找到足够接近的位置/),
    ).toBeInTheDocument()
  })
})

// ---- N074 记为问题 -----------------------------------------------------------

describe('N074 批注弹层记为问题', () => {
  it('编辑弹层 → 记为问题 → POST 带 entryRef + annotationId', async () => {
    makeArticle('<p>正文里可定位的原句。</p>')
    seedAnnotation({
      id: 'a9',
      entryRef: 'e1.a',
      color: 'yellow',
      note: '作者论据是什么？',
      anchor: { prefix: '', exact: '正文里可定位的原句', suffix: '' },
      createdAt: 1,
      contentVersion: '',
    })
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/reading-questions')) {
        return Promise.resolve(
          jsonResponse({
            id: 'q1',
            question: '作者论据是什么？',
            status: 'open',
            entryRef: 'e1.a',
            annotationId: 'a9',
            workspaceId: null,
            createdAt: '2026-01-01T00:00:00Z',
            updatedAt: '2026-01-01T00:00:00Z',
          }),
        )
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AnnotationsLayer entryRef="e1.a" />)
    fireEvent.click(screen.getByRole('button', { name: '编辑' }))
    fireEvent.click(screen.getByRole('button', { name: '记为问题' }))

    await waitFor(() => {
      expect(screen.getByText(/已记为问题/)).toBeInTheDocument()
    })
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/reading-questions'))
    expect(call).toBeDefined()
    const body = JSON.parse(String(call![1]?.body))
    expect(body).toEqual({
      question: '作者论据是什么？',
      entryRef: 'e1.a',
      annotationId: 'a9',
    })
  })
})

// ---- Manager：N073 过滤 / N075 引用格式 / N074 问题页签 / N076+N077 复习 ----

const COLOR_LABELS = {
  items: [
    { color: 'yellow', label: '重要' },
    { color: 'green', label: '' },
    { color: 'blue', label: '' },
    { color: 'red', label: '重点反驳' },
    { color: 'purple', label: '' },
  ],
}

function annotationItem(overrides: Record<string, unknown>): Record<string, unknown> {
  return {
    id: 'an1',
    entryRef: 'e1.abcdefgh',
    anchor: { paraId: 'p1' },
    anchorHash: 'h',
    excerpt: '摘录文本',
    note: '批注',
    color: 'red',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('N073 颜色语义过滤', () => {
  it('未命名颜色诚实显示原始色名；选择标签 → color= 查询参数', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/color-labels')) {
        return Promise.resolve(jsonResponse(COLOR_LABELS))
      }
      if (url.startsWith('/api/v1/annotations?')) {
        return Promise.resolve(
          jsonResponse({ items: [annotationItem({})], nextCursor: null }),
        )
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderWithQuery(<AnnotationsManager />)

    // 未命名 → 原始色名；已命名 → 标签
    expect(await screen.findByText('重点反驳')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'green' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('按颜色筛选'), { target: { value: 'red' } })
    await waitFor(() => {
      const filtered = fetchMock.mock.calls.filter(([url]) =>
        String(url).includes('color=red'),
      )
      expect(filtered.length).toBeGreaterThan(0)
    })
  })
})

describe('N075 引用格式导出', () => {
  it('勾选引用格式 → 导出请求携带 citeBibliography=true', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/color-labels')) {
        return Promise.resolve(jsonResponse(COLOR_LABELS))
      }
      if (url.startsWith('/api/v1/annotations?')) {
        return Promise.resolve(
          jsonResponse({ items: [annotationItem({})], nextCursor: null }),
        )
      }
      if (url.endsWith('/annotations/export')) {
        return Promise.resolve(new Response('# 批注汇编\n', { status: 200 }))
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderWithQuery(<AnnotationsManager />)

    fireEvent.click(await screen.findByRole('checkbox', { name: '导出附带引用格式' }))
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    fireEvent.click(screen.getByRole('button', { name: /导出汇编/ }))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/annotations/export'))
      expect(call).toBeDefined()
      expect(JSON.parse(String(call![1]?.body))).toEqual({ citeBibliography: true })
    })
  })
})

describe('N074 问题页签', () => {
  it('列表 / 完成与重新打开（PATCH）/ 按状态与链接过滤', async () => {
    const questions = [
      {
        id: 'q1',
        question: '待解决问题',
        status: 'open',
        entryRef: 'e1.a',
        annotationId: null,
        workspaceId: null,
        createdAt: '2026-01-01T00:00:00Z',
        updatedAt: '2026-01-01T00:00:00Z',
      },
      {
        id: 'q2',
        question: '无链接问题',
        status: 'done',
        entryRef: null,
        annotationId: null,
        workspaceId: null,
        createdAt: '2026-01-02T00:00:00Z',
        updatedAt: '2026-01-02T00:00:00Z',
      },
    ]
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/color-labels')) return Promise.resolve(jsonResponse(COLOR_LABELS))
      if (url.includes('/reading-questions')) {
        if (String((input as Request).method) === 'PATCH' || url.includes('/reading-questions/')) {
          const id = url.split('/').pop()
          const target = questions.find((q) => q.id === id)!
          const next = { ...target, status: target.status === 'open' ? 'done' : 'open' }
          return Promise.resolve(jsonResponse(next))
        }
        return Promise.resolve(jsonResponse({ items: questions }))
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderWithQuery(<AnnotationsManager />)

    fireEvent.click(await screen.findByRole('tab', { name: '问题' }))
    expect(await screen.findByText('待解决问题')).toBeInTheDocument()
    expect(screen.getByText('无链接问题')).toBeInTheDocument()

    // 按链接过滤：无链接 → 只剩 q2
    fireEvent.change(screen.getByLabelText('按链接筛选问题'), { target: { value: 'unlinked' } })
    expect(screen.queryByText('待解决问题')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('按链接筛选问题'), { target: { value: 'all' } })

    // 完成 → 重新打开（同一 PATCH 路径）
    fireEvent.click(screen.getByRole('button', { name: /完成/ }))
    expect(await screen.findByRole('button', { name: /重新打开/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /重新打开/ }))
    expect(await screen.findByRole('button', { name: /完成/ })).toBeInTheDocument()
  })
})

describe('N076/N077 复习页签', () => {
  const reviewItems = {
    items: [
      {
        id: 'r1',
        itemKind: 'annotation',
        annotationId: 'an1',
        knowledgeCardId: null,
        entryRef: 'e1.a',
        paraId: 'p-7',
        dueAt: '2020-01-01T00:00:00Z',
        completedAt: null,
        due: true,
        lastViewedAt: null,
        sourceAvailable: true,
        excerpt: '批注摘录',
        note: '批注答案',
        concept: null,
        explanation: null,
      },
      {
        id: 'r2',
        itemKind: 'knowledge_card',
        annotationId: null,
        knowledgeCardId: 'kc1',
        entryRef: 'e1.b',
        paraId: null,
        dueAt: '2020-01-01T00:00:00Z',
        completedAt: null,
        due: true,
        lastViewedAt: null,
        sourceAvailable: false,
        excerpt: null,
        note: null,
        concept: '检索漏斗',
        explanation: '检索漏斗的解释',
      },
    ],
  }

  function reviewFetchMock(): ReturnType<typeof vi.fn> {
    return vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/color-labels')) return Promise.resolve(jsonResponse(COLOR_LABELS))
      if (url.endsWith('/review-queue?status=due')) {
        return Promise.resolve(jsonResponse(reviewItems))
      }
      if (url.includes('/review-queue/') && url.endsWith('/view')) {
        return Promise.resolve(jsonResponse({ id: 'r1', lastViewedAt: '2026-01-03T00:00:00Z' }))
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
  }

  it('kind 徽章；揭示调用 /view；来源不可用诚实降级（无 deep link、无揭示）', async () => {
    const fetchMock = reviewFetchMock()
    vi.stubGlobal('fetch', fetchMock)
    renderWithQuery(<AnnotationsManager />)

    fireEvent.click(await screen.findByRole('tab', { name: '复习' }))
    expect(await screen.findByText('批注摘录')).toBeInTheDocument()
    expect(screen.getByText('知识卡片')).toBeInTheDocument() // N076 kind 徽章
    expect(screen.getByText('该来源已不可用')).toBeInTheDocument() // N077

    // N077：来源不可用 → 无 deep link、无揭示按钮、不显示内容
    const cardLi = screen
      .getAllByRole('listitem')
      .find((el) => el.textContent?.includes('该来源已不可用'))!
    expect(cardLi.querySelector('a[aria-label="查看原文段落"]')).toBeNull()
    expect(cardLi.textContent).not.toContain('检索漏斗的解释')
    expect(cardLi.textContent).not.toContain('检索漏斗') // 不缓存、不展示来源内容

    // N077：批注项有 deep link（带 para）；揭示 → POST /view
    const annotationLi = screen.getByText('批注摘录').closest('li')!
    const deepLink = annotationLi.querySelector('a[aria-label="查看原文段落"]') as HTMLAnchorElement
    expect(deepLink.getAttribute('href')).toBe('/reader?entry=e1.a&para=p-7')
    fireEvent.click(screen.getByRole('button', { name: '显示批注' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).endsWith('/view')),
      ).toBe(true)
    })
    expect(await screen.findByText('批注答案')).toBeInTheDocument()
  })

  it('N076 知识卡片管理器：加入复习 → POST kind=knowledge_card', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/knowledge-cards')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 'kc9',
                entryRef: 'e1.k',
                concept: '双链笔记',
                explanation: '解释文本',
                sourceQuote: '',
                quoteVerified: false,
                createdAt: '2026-01-01T00:00:00Z',
                entryTitle: '标题',
                stale: false,
              },
            ],
          }),
        )
      }
      if (url.endsWith('/review-queue')) {
        return Promise.resolve(jsonResponse({ id: 'r9', rescheduled: false }))
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderWithQuery(<KnowledgeCardsManager />)

    fireEvent.click(await screen.findByRole('button', { name: /加入复习/ }))
    await waitFor(() => {
      expect(screen.getByText(/已加入复习/)).toBeInTheDocument()
    })
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/review-queue'))
    const body = JSON.parse(String(call![1]?.body))
    expect(body.kind).toBe('knowledge_card')
    expect(body.knowledgeCardId).toBe('kc9')
    expect(body.dueAt).toBeTruthy()
  })
})
