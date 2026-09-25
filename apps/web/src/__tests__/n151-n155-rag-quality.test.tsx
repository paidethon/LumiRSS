/** N151-N155 UI — RAG 质量补位：授权范围摘要卡（N151）、索引覆盖率
 * 卡片（N152）、查看分块模态（N153）、证据强弱 chip 与未验证回答的
 * 重试/摘录操作区（N154/N155）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  RagChunkPreviewPanel,
  RagCoveragePanel,
} from '../components/RagW5Panels'
import {
  EvidenceStrengthChip,
  UnverifiedAnswerActions,
} from '../components/pages/AgentWorkbenchPage'
import { ThreadSettingsButton } from '../components/AgentW5'

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

describe('N152 索引覆盖率卡片', () => {
  it('扫描 → 分桶计数 + 不支持 kind 标注（empty_text）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/rag/coverage')) {
        return Promise.resolve(
          jsonResponse({
            modelId: 'BAAI/bge-small-zh-v1.5',
            indexable: 42,
            indexed: 40,
            stale: 2,
            failed: 1,
            unsupported: { count: 3, kinds: [{ kind: 'clip', reason: 'empty_text' }] },
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<RagCoveragePanel />)

    fireEvent.click(screen.getByRole('button', { name: '扫描索引覆盖率' }))
    expect(await screen.findByText(/可索引 42/)).toBeInTheDocument()
    expect(screen.getByText(/已索引 40/)).toBeInTheDocument()
    expect(screen.getByText(/过期 2/)).toBeInTheDocument()
    expect(screen.getByText(/失败 1/)).toBeInTheDocument()
    expect(screen.getByText(/不支持 3/)).toBeInTheDocument()
    expect(screen.getByText('clip · empty_text')).toBeInTheDocument()
    const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/rag/coverage'))
    expect(call).toBeDefined()
  })

  it('盘点失败 → 错误提示（诚实报错）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ error: { message: 'boom' } }, 500))),
    )
    renderUi(<RagCoveragePanel />)
    fireEvent.click(screen.getByRole('button', { name: '扫描索引覆盖率' }))
    expect(await screen.findByText(/覆盖率盘点失败/)).toBeInTheDocument()
  })
})

describe('N153 查看分块', () => {
  it('输入 ref → POST /rag/chunk-preview → 模态展示分块与方案', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/rag/chunk-preview') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body ?? '{}')) as { ref: string }
        expect(body.ref).toBe('library:abc')
        return Promise.resolve(
          jsonResponse({
            ref: 'library:abc',
            kind: 'clip',
            title: '部署记录',
            chunks: [
              { ord: 0, text: '第一块内容', charStart: 0, charEnd: 120 },
              { ord: 1, text: '第二块内容', charStart: 120, charEnd: 260 },
            ],
            scheme: { maxLen: 800, overlap: 0 },
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<RagChunkPreviewPanel />)

    fireEvent.change(screen.getByLabelText('分块预览 ref'), { target: { value: 'library:abc' } })
    fireEvent.click(screen.getByRole('button', { name: '查看分块' }))
    expect(await screen.findByText(/将产生 2 块/)).toBeInTheDocument()
    expect(screen.getByText(/单块上限 800 字符 · 重叠 0/)).toBeInTheDocument()
    expect(screen.getByText('#0 · 原文位置 0–120')).toBeInTheDocument()
    expect(screen.getByText('第一块内容')).toBeInTheDocument()
    expect(screen.getByText('第二块内容')).toBeInTheDocument()
  })
})

describe('N151 授权范围摘要卡', () => {
  it('打开设置 → 服务端解析 kind × refCount × toolCount；切换范围重新解析', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.endsWith('/workspaces')) {
        return Promise.resolve(
          jsonResponse({
            items: [{ id: 'ws-1', name: '研究', position: 1, itemCount: 3, reserved: false, description: null, archived: false, archivedAt: null }],
          }),
        )
      }
      if (url.endsWith('/agent/scope-preview') && method === 'POST') {
        const body = JSON.parse(String(init?.body ?? '{}')) as {
          scope: { workspaceId?: string } | null
        }
        if (body.scope?.workspaceId === 'ws-1') {
          return Promise.resolve(jsonResponse({ kind: 'workspace', refCount: 3, toolCount: 7 }))
        }
        return Promise.resolve(jsonResponse({ kind: 'all', refCount: null, toolCount: 9 }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ThreadSettingsButton threadId="th-1" />)

    fireEvent.click(await screen.findByRole('button', { name: '会话设置' }))
    // 默认全库：kind=all，refCount=null（条目不限），toolCount=9。
    expect(
      await screen.findByText('全库（不锁定） · 条目不限 · 9 个工具可用'),
    ).toBeInTheDocument()
    const first = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith('/agent/scope-preview') && c[1]?.method === 'POST',
    )
    expect(first).toBeDefined()

    // 切换到工作区 → 重新解析：refCount 服务端返回 3。
    fireEvent.change(screen.getByLabelText('资料范围工作区'), { target: { value: 'ws-1' } })
    expect(await screen.findByText('工作区 · 3 条 · 7 个工具可用')).toBeInTheDocument()
    const calls = fetchMock.mock.calls.filter(
      (c) => String(c[0]).endsWith('/agent/scope-preview') && c[1]?.method === 'POST',
    )
    const last = calls[calls.length - 1]
    expect(JSON.parse(String(last![1].body ?? '{}'))).toMatchObject({
      scope: { workspaceId: 'ws-1' },
    })
  })
})

describe('N154/N155 证据强弱 chip 与未验证操作区', () => {
  it('chip 三态文案（绝无「置信度」措辞）；无分级不渲染', () => {
    const { rerender, container } = renderUi(<EvidenceStrengthChip strength="direct" />)
    expect(screen.getByText('直接支持')).toBeInTheDocument()
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <EvidenceStrengthChip strength="partial" />
      </QueryClientProvider>,
    )
    expect(screen.getByText('部分支持')).toBeInTheDocument()
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <EvidenceStrengthChip strength="none" />
      </QueryClientProvider>,
    )
    expect(screen.getByText('无直接支持')).toBeInTheDocument()
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <EvidenceStrengthChip strength={null} />
      </QueryClientProvider>,
    )
    expect(container.querySelector('[data-evidence-strength]')).toBeNull()
    expect(document.body.textContent).not.toContain('置信度')
  })

  it('未验证回答：诚实标注 + 重试回调 + 摘录模式取原文片段', async () => {
    const onRetry = vi.fn()
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/rag/ask') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body ?? '{}')) as { mode?: string; question?: string }
        expect(body.mode).toBe('excerpt')
        expect(body.question).toBe('这篇讲了什么？')
        return Promise.resolve(
          jsonResponse({
            question: '这篇讲了什么？',
            mode: 'excerpt',
            answer: null,
            citations: [],
            evidenceStrength: null,
            unverifiable: false,
            reason: null,
            effectiveScope: { kind: 'all', refCount: null },
            excerpts: [{ ref: 'library:abc', title: '部署记录', ord: 0, text: '原文片段正文' }],
            semanticUsed: false,
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(
      <UnverifiedAnswerActions threadId="th-1" question="这篇讲了什么？" onRetry={onRetry} />,
    )

    expect(screen.getByText(/证据不足/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(onRetry).toHaveBeenCalledWith('这篇讲了什么？')

    fireEvent.click(screen.getByRole('button', { name: '摘录模式' }))
    expect(await screen.findByText(/摘录 ≠ AI 回答/)).toBeInTheDocument()
    expect(screen.getByText('原文片段正文')).toBeInTheDocument()
  })
})
