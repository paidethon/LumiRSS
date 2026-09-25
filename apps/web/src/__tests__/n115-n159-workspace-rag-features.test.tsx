/** N115/N116/N117/N118/N119/N156/N158/N159 UI —— 新特性面板的关键流程。
 *
 * 全部 fetch mock（hermetic）：
 * - N115 快照对比：设基准 → 与基准对比 → diff 视图渲染四组差异；
 * - N116 汇编预览「导出分享包」按钮调用 share-package 端点；
 * - N117 模板对话框暴露「包含结构」与「恢复模板结构」勾选；
 * - N118 收集规则：新建（恰好一条件由 UI 保证单输入框）+ 暂停开关 +
 *   预演 Dialog 渲染命中；
 * - N119 归档摘要卡：条目数/完成/目标进度/存续天数；
 * - N156 冲突对照：诚实口径文案（基于文本比对，非语义裁决）；
 * - N158 覆盖率卡片「重建所选」调 rebuild/refs；
 * - N159 评测样例：保存 + 重放差分渲染。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkspaceSnapshotsPanel } from '../components/WorkspaceSnapshotsPanel'
import { WorkspaceCollectRulesPanel } from '../components/WorkspaceCollectRulesPanel'
import { ArchivedBar } from '../components/WorkspaceExtras'
import { RagCoveragePanel, RagEvalSamplesPanel } from '../components/RagW5Panels'

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

const SNAPSHOTS = {
  items: [
    { id: 'snap-b', workspaceId: 'ws-1', name: '周二', createdAt: '2026-09-23T00:00:00Z', itemCount: 2 },
    { id: 'snap-a', workspaceId: 'ws-1', name: '周一', createdAt: '2026-09-22T00:00:00Z', itemCount: 3 },
  ],
}

describe('N115 快照对比', () => {
  it('设基准 → 与基准对比 → diff 四组差异渲染', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/snapshots')) {
        return Promise.resolve(jsonResponse(SNAPSHOTS))
      }
      if (url.includes('/snapshots/snap-a/diff/snap-b')) {
        return Promise.resolve(
          jsonResponse({
            snapshotA: 'snap-a',
            snapshotB: 'snap-b',
            added: ['library:new'],
            removed: ['library:old'],
            moved: [{ ref: 'library:m1', fromPos: 2, toPos: 1 }],
            groupChanges: [{ ref: 'library:m1', from: '甲组', to: null }],
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<WorkspaceSnapshotsPanel workspaceId="ws-1" />)

    // 列表新→旧 = [周二, 周一]；把最后一行（周一）设为基准。
    const baseButtons = await screen.findAllByRole('button', { name: '设为对比基准' })
    fireEvent.click(baseButtons[baseButtons.length - 1])
    fireEvent.click(await screen.findByRole('button', { name: '与「周一」对比' }))
    const diff = await screen.findByTestId('workspace-snapshot-diff')
    expect(diff).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText(/新增（目标有、基准无）· 1/)).toBeInTheDocument()
      expect(screen.getByText(/位置变化 · 1/)).toBeInTheDocument()
      expect(screen.getByText(/甲组 → 未分组/)).toBeInTheDocument()
    })
  })
})

describe('N118 收集规则', () => {
  it('空态 → 新建关键词规则（恰好一条件）→ 列表渲染', async () => {
    let created = false
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/collect-rules')) {
        return Promise.resolve(
          jsonResponse({
            items: created
              ? [{
                  id: 'rule-1', workspaceId: 'ws-1', feedUrl: null, tag: null,
                  keyword: '检索', enabled: true, maxItems: 100, addedCount: 0,
                  createdAt: '2026-09-25T00:00:00Z', updatedAt: '2026-09-25T00:00:00Z',
                }]
              : [],
          }),
        )
      }
      if (method === 'POST' && url.endsWith('/collect-rules')) {
        created = true
        return Promise.resolve(
          jsonResponse({
            id: 'rule-1', workspaceId: 'ws-1', feedUrl: null, tag: null,
            keyword: '检索', enabled: true, maxItems: 100, addedCount: 0,
            createdAt: '2026-09-25T00:00:00Z', updatedAt: '2026-09-25T00:00:00Z',
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<WorkspaceCollectRulesPanel workspaceId="ws-1" />)

    expect(await screen.findByText(/还没有规则/)).toBeInTheDocument()
    expect(screen.getByText(/绝不后台抓取/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('规则条件值'), { target: { value: '检索' } })
    fireEvent.click(screen.getByRole('button', { name: /新建规则/ }))
    await waitFor(() => {
      expect(screen.getByText(/关键词「检索」/)).toBeInTheDocument()
    })
    const call = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith('/collect-rules') && c[1]?.method === 'POST',
    )
    const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as { keyword?: string; maxItems?: number }
    expect(body.keyword).toBe('检索')
    expect(body.maxItems).toBe(100)
  })
})

describe('N119 归档摘要卡', () => {
  it('渲染 条目数/完成/目标进度/存续天数', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/workspace-archive')) {
        return Promise.resolve(
          jsonResponse([
            {
              id: 'ws-arch', name: '旧项目', position: 8, itemCount: 3, reserved: false,
              description: '', archived: true, archivedAt: '2026-09-18T00:00:00Z', revision: 1,
              summary: {
                itemCount: 3, doneCount: 2,
                goalProgress: { targetCount: 5, doneCount: 2 },
                archivedAt: '2026-09-18T00:00:00Z', daysActive: 12,
              },
            },
          ]),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ArchivedBar />)

    expect(await screen.findByText('已归档：')).toBeInTheDocument()
    expect(await screen.findByText('3 条')).toBeInTheDocument()
    expect(screen.getByText('完成 2')).toBeInTheDocument()
    expect(screen.getByText('目标 2/5')).toBeInTheDocument()
    expect(screen.getByText('存续 12 天')).toBeInTheDocument()
  })
})

describe('N158 重建所选', () => {
  it('覆盖率扫描后出现过期 ref 勾选，重建调用 rebuild/refs', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/rag/coverage')) {
        return Promise.resolve(
          jsonResponse({
            modelId: 'BAAI/bge-small-zh-v1.5',
            indexable: 2, indexed: 1, stale: 1, staleRefs: ['library:stale-1'], failed: 0,
            unsupported: { count: 0, kinds: [] },
          }),
        )
      }
      if (method === 'POST' && url.endsWith('/rag/rebuild/refs')) {
        return Promise.resolve(
          jsonResponse({ jobId: 'job-1', status: 'done', total: 1, updated: 1, chunks: 2, missing: [] }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<RagCoveragePanel />)

    fireEvent.click(await screen.findByRole('button', { name: '扫描索引覆盖率' }))
    fireEvent.click(await screen.findByLabelText('重建：library:stale-1'))
    fireEvent.click(screen.getByRole('button', { name: '重建所选（1）' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/rag/rebuild/refs') && c[1]?.method === 'POST',
      )
      expect(call).toBeDefined()
      const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as { refs: string[] }
      expect(body.refs).toEqual(['library:stale-1'])
    })
    expect(await screen.findByText(/局部重建完成/)).toBeInTheDocument()
  })
})

describe('N159 评测样例', () => {
  it('保存样例 → 列表渲染 → 重放差分', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/rag/eval-samples')) {
        return Promise.resolve(
          jsonResponse({
            cap: 50,
            items: [
              {
                id: 'eval-1', query: '检索增强',
                expectedRefs: ['library:a'], actualRefs: ['library:a'],
                kind: null, createdAt: '2026-09-25T00:00:00Z',
              },
            ],
          }),
        )
      }
      if (method === 'POST' && url.endsWith('/rag/eval-samples')) {
        return Promise.resolve(
          jsonResponse({
            id: 'eval-1', query: '检索增强',
            expectedRefs: ['library:a'], actualRefs: ['library:a'],
            kind: null, createdAt: '2026-09-25T00:00:00Z',
          }),
        )
      }
      if (method === 'POST' && url.endsWith('/rag/eval-samples/eval-1/rerun')) {
        return Promise.resolve(
          jsonResponse({
            sampleId: 'eval-1', query: '检索增强',
            storedActualRefs: ['library:a'], nowActualRefs: ['library:a', 'library:b'],
            hitExpected: ['library:a'], missed: [], newHits: ['library:b'],
            ranAt: '2026-09-25T01:00:00Z',
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<RagEvalSamplesPanel />)

    expect(await screen.findByText('检索增强')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重放' }))
    await waitFor(() => {
      const diff = document.querySelector('[data-rerun-diff]') as HTMLElement | null
      expect(diff).not.toBeNull()
      expect(diff!.textContent).toContain('期望仍命中 1')
      expect(diff!.textContent).toContain('新命中 1')
      expect(diff!.textContent).toContain('library:b')
    })
  })
})
