/** E1: N046/N047 面板交互 —— 撞车提示（定位/仍要加入）与 409 按项合并。

- N047：加入成功响应携带 duplicateWarning → 面板显示「疑似已收录」条，
  提供 定位 / 仍要加入（非阻断：条目已加入）；
- N046：变更撞上 409 queue_revision_conflict → 拉取服务端最新视图做
  差异，弹「按项合并」对话框（逐 ref 保留服务端/本地）；完成合并发出
  resolutions（keep-mine 携带本地状态）；未冲突项不出现在对话框。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingQueuePanel } from '../components/ReadingQueuePanel'

function item(
  id: string,
  ref: string,
  title: string,
  extra: Partial<{ status: string; position: number }> = {},
) {
  return {
    id,
    itemRef: ref,
    addedAt: '2026-09-25T08:00:00Z',
    position: extra.position ?? 1,
    queueDate: '2026-09-25',
    source: 'budget',
    status: extra.status ?? 'pending',
    segment: null,
    title,
    estimateMinutes: 2,
  }
}

const a = () => item('rq-1', 'rss:e1.a', '文章甲', { position: 1 })
const b = () => item('rq-2', 'rss:e1.b', '文章乙', { position: 2 })

interface QueueView {
  queueDate: string
  items: ReturnType<typeof a>[]
  segments: { name: string | null; items: ReturnType<typeof a>[] }[]
  segmentOrder: string[]
  totalEstimateMinutes: number
  revision: number
}
let queueView: () => QueueView
let lastMergeBody: unknown = null

let serverAdvanced = false

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/queue/today') && !url.includes('snapshots')) {
    // 409 之后 = 服务端已被「另一设备」推进：a=done、修订号 +1。
    return Promise.resolve(
      new Response(
        JSON.stringify(
          serverAdvanced
            ? {
                ...queueView(),
                revision: 6,
                items: queueView().items.map((row) =>
                  row.id === 'rq-1' ? { ...row, status: 'done' } : row,
                ),
              }
            : queueView(),
        ),
        { status: 200 },
      ),
    )
  }
  if (method === 'POST' && url.includes('/items/rq-1/done')) {
    serverAdvanced = true
    return Promise.resolve(
      new Response(
        JSON.stringify({
          error: {
            type: 'queue_revision_conflict',
            message: '队列已被其他设备修改',
            currentRevision: 6,
            conflicts: [],
          },
        }),
        { status: 409 },
      ),
    )
  }
  if (method === 'POST' && url.includes('/queue/today/items')) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          ...a(),
          outcome: 'created',
          duplicateWarning: {
            duplicateOf: { ref: 'rss:e1.a', scope: 'queue', title: '文章甲（旧）' },
          },
        }),
        { status: 201 },
      ),
    )
  }
  if (method === 'POST' && url.includes('/merge-conflicts')) {
    lastMergeBody = JSON.parse(String(init?.body ?? '{}'))
    const merged = queueView()
    return Promise.resolve(
      new Response(
        JSON.stringify({ ...merged, revision: merged.revision + 1, merge: { applied: 1, resolutions: 1 } }),
        { status: 200 },
      ),
    )
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ReadingQueuePanel currentItemRef="e1.a" onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  serverAdvanced = false
  queueView = () => ({
    queueDate: '2026-09-25',
    items: [a(), b()],
    segments: [{ name: null, items: [a(), b()] }],
    segmentOrder: [],
    totalEstimateMinutes: 4,
    revision: 5,
  })
  lastMergeBody = null
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)
})

afterEach(() => {
  vi.unstubAllGlobals()
  fetchMock.mockClear()
})

describe('N047 duplicate warning (queue add)', () => {
  it('shows locate / keep-both actions on collision warning (non-blocking)', async () => {
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: /加入当前文章/ })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: /加入当前文章/ }))
    const warning = await screen.findByTestId('queue-duplicate-warning')
    expect(warning.textContent).toContain('疑似已收录')
    expect(warning.textContent).toContain('文章甲（旧）')
    // 定位与仍要加入都在（非阻断：条目已加入）。
    expect(screen.getByRole('button', { name: '定位' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '仍要加入' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '仍要加入' }))
    await waitFor(() => expect(screen.queryByTestId('queue-duplicate-warning')).toBeNull())
  })
})

describe('N046 revision conflict merge (panel)', () => {
  it('409 → per-item merge dialog; unmodified item is not a conflict', async () => {
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: /加入当前文章/ })).toBeTruthy())

    // 本地把「文章甲」标记完成 → 409（另一设备已改）。
    // 注意：第一个 checkbox 是「只看未完成」过滤开关；行 checkbox 按
    // 队列顺序排列，第 2 个 = 队列第 1 行（文章甲）。等队列行渲染完成。
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBe(3))
    const rowCheckbox = screen.getAllByRole('checkbox')[1]!
    fireEvent.click(rowCheckbox)

    // 冲突对话框出现：只有分歧的「文章甲」，未修改的「文章乙」不在。
    const dialog = await screen.findByTestId('queue-merge-dialog', {}, { timeout: 3000 })
    expect(dialog.textContent).toContain('文章甲')
    expect(dialog.textContent).not.toContain('文章乙')

    // 选择「保留本地」→ 完成合并 → keep-mine 携带本地 pending 状态。
    fireEvent.click(screen.getByRole('radio', { name: '保留本地' }))
    fireEvent.click(screen.getByRole('button', { name: '完成合并' }))
    await waitFor(() => expect(screen.queryByTestId('queue-merge-dialog')).toBeNull())
    expect(lastMergeBody).not.toBeNull()
    const body = lastMergeBody as {
      expectedRevision: number
      resolutions: { itemRef: string; action: string; clientItem?: { status: string } }[]
    }
    expect(body.expectedRevision).toBe(6) // 服务端最新修订号
    expect(body.resolutions).toHaveLength(1)
    expect(body.resolutions[0]!.itemRef).toBe('rss:e1.a')
    expect(body.resolutions[0]!.action).toBe('keep-mine')
    expect(body.resolutions[0]!.clientItem?.status).toBe('pending')
  })
})
