/** NEW-219/220 内容整理工作台入口测试 —— 批量归档勾选链路 + 处理记录
 * 按日追踪。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import New219InboxOpsPanel from '../components/new211/New219InboxOpsPanel'

const PREVIEW = {
  count: 2,
  sample: [
    { ref: 'rss:e1.old1', title: '旧文一', feedTitle: '源A', publishedAt: '2026-01-01T00:00:00+00:00', read: false, starred: false },
    { ref: 'rss:e1.old2', title: '旧文二', feedTitle: '源B', publishedAt: '2026-02-01T00:00:00+00:00', read: false, starred: false },
  ],
  effectiveExclusions: ['starred'],
}
const RECEIPT = {
  batchId: 'batch-1',
  archived: ['rss:e1.old1'],
  failed: [],
  createdAt: '2026-09-28T00:00:00+00:00',
}
const UNDO = { restored: ['rss:e1.old1'], skipped: [] }
const TRAIL = {
  days: [
    {
      date: '2026-09-28',
      entries: [
        {
          id: 't1',
          fromLocation: '收件箱',
          toLocation: '工作区:调研',
          refs: ['rss:e1.old1'],
          reason: '集中管理',
          createdAt: '2026-09-28T10:00:00+00:00',
        },
      ],
    },
  ],
  count: 1,
}

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'POST' && url.includes('/api/v1/archive-batches/preview')) {
    return Promise.resolve(new Response(JSON.stringify(PREVIEW), { status: 200 }))
  }
  if (method === 'POST' && url.endsWith('/api/v1/archive-batches')) {
    return Promise.resolve(new Response(JSON.stringify(RECEIPT), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/undo')) {
    return Promise.resolve(new Response(JSON.stringify(UNDO), { status: 200 }))
  }
  if (method === 'GET' && url.includes('/api/v1/triage-journal')) {
    return Promise.resolve(new Response(JSON.stringify(TRAIL), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/api/v1/triage-journal')) {
    return Promise.resolve(
      new Response(JSON.stringify({ id: 't2', fromLocation: '收件箱', toLocation: '归档', refs: ['rss:e1.x'], reason: '', createdAt: '2026-09-28T11:00:00+00:00' }), { status: 201 }),
    )
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <New219InboxOpsPanel onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)
})

describe('New219InboxOpsPanel', () => {
  it('批量归档：条件清单 → 勾选 → 归档 → 收据 → 撤销', async () => {
    renderPanel()
    fireEvent.click(await screen.getByRole('button', { name: '生成清单' }))
    const preview = await screen.findByTestId('new219-preview')
    expect(preview).toHaveTextContent('待归档 2 篇')
    const checkboxes = screen.getAllByRole('checkbox')
    fireEvent.click(checkboxes[0])
    fireEvent.click(screen.getByRole('button', { name: '归档所选（1）' }))
    const receiptBox = await screen.findByTestId('new219-receipt')
    expect(receiptBox).toHaveTextContent('归档 1 篇')
    fireEvent.click(screen.getByRole('button', { name: '撤销本批（未被后续修改的部分）' }))
    await waitFor(() => expect(screen.getByTestId('new219-undo-result')).toBeInTheDocument())
    expect(screen.getByTestId('new219-undo-result')).toHaveTextContent('已恢复 1 篇')
  })

  it('处理记录：按日分组展示轨迹，可写入新记录', async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole('tab', { name: '处理记录' }))
    const trail = await screen.findByTestId('new220-trail')
    expect(trail).toHaveTextContent('2026-09-28')
    expect(trail).toHaveTextContent('收件箱 → 工作区:调研（1 条；原因：集中管理）')
    fireEvent.change(screen.getByLabelText('到哪里'), { target: { value: '归档' } })
    fireEvent.change(screen.getByLabelText('涉及引用（空格分隔）'), { target: { value: 'rss:e1.x' } })
    fireEvent.click(screen.getByRole('button', { name: '记录本次整理' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/triage-journal'),
      expect.objectContaining({ method: 'POST' }),
    ))
  })
})
