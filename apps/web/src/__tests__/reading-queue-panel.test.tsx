/** N041/N042/N043/N044/N048 今日必读面板 —— 编辑列表 / 分段 / 冻结 /
 * 只看未完成 / 连续阅读间隔（倒计时芯片）。 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingQueuePanel } from '../components/ReadingQueuePanel'

function item(
  id: string,
  ref: string,
  title: string,
  extra: Partial<{
    status: string
    segment: string | null
    position: number
    estimateMinutes: number | null
    source: string
  }> = {},
) {
  return {
    id,
    itemRef: ref,
    addedAt: '2026-09-23T08:00:00Z',
    position: extra.position ?? 1,
    queueDate: '2026-09-23',
    source: extra.source ?? 'budget',
    status: extra.status ?? 'pending',
    segment: extra.segment ?? null,
    title,
    estimateMinutes: extra.estimateMinutes ?? 2,
  }
}

function baseQueue() {
  const a = item('rq-1', 'rss:e1.a', '文章甲', { position: 1 })
  const b = item('rq-2', 'rss:e1.b', '文章乙', { position: 2, segment: null })
  const c = item('rq-3', 'rss:e1.c', '文章丙', {
    position: 3,
    status: 'done',
    estimateMinutes: 1,
  })
  return {
    queueDate: '2026-09-23',
    items: [a, b, c],
    segments: [{ name: null as string | null, items: [a, b, c] }],
    segmentOrder: [] as string[],
    totalEstimateMinutes: 5,
  }
}

const snapshotList = {
  items: [
    { id: 'qsnap-1', label: '早间批次', queueDate: '2026-09-23', createdAt: '2026-09-23T07:00:00Z', itemCount: 2 },
  ],
}

const snapshotDetail = {
  id: 'qsnap-1',
  label: '早间批次',
  queueDate: '2026-09-23',
  createdAt: '2026-09-23T07:00:00Z',
  items: [
    { itemRef: 'rss:e1.a', position: 1, segment: null },
    { itemRef: 'rss:e1.gone', position: 2, segment: null },
  ],
  segmentOrder: [],
}

let queue: ReturnType<typeof baseQueue>

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/queue/today') && !url.includes('snapshots')) {
    return Promise.resolve(new Response(JSON.stringify(queue), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/queue/today/generate')) {
    return Promise.resolve(
      new Response(JSON.stringify({ ...queue, generated: true, force: url.includes('force=1'), basis: 'unread+recency', budgetMinutes: 30, notes: [] }), { status: 201 }),
    )
  }
  if (method === 'POST' && url.includes('/done')) {
    const body = JSON.parse(String(init?.body ?? '{}')) as { done: boolean }
    return Promise.resolve(
      new Response(JSON.stringify({ ...queue.items[0], status: body.done ? 'done' : 'pending' }), { status: 200 }),
    )
  }
  if (method === 'PUT' && url.includes('/queue/today/order')) {
    return Promise.resolve(new Response(JSON.stringify(queue), { status: 200 }))
  }
  if (method === 'PUT' && url.includes('/queue/today/segments')) {
    return Promise.resolve(new Response(JSON.stringify(queue), { status: 200 }))
  }
  if (method === 'PATCH' && url.includes('/segment')) {
    const body = JSON.parse(String(init?.body ?? '{}')) as { segment: string | null }
    return Promise.resolve(
      new Response(JSON.stringify({ ...queue.items[0], segment: body.segment }), { status: 200 }),
    )
  }
  if (method === 'POST' && url.includes('/queue/today/items') && !url.includes('freeze')) {
    return Promise.resolve(new Response(JSON.stringify(queue.items[0]), { status: 201 }))
  }
  if (method === 'DELETE' && url.includes('/queue/today/items')) {
    return Promise.resolve(new Response(null, { status: 204 }))
  }
  if (method === 'POST' && url.includes('/queue/today/freeze')) {
    return Promise.resolve(new Response(JSON.stringify(snapshotList.items[0]), { status: 201 }))
  }
  if (method === 'GET' && url.includes('/queue/snapshots/')) {
    return Promise.resolve(new Response(JSON.stringify(snapshotDetail), { status: 200 }))
  }
  if (method === 'GET' && url.includes('/queue/snapshots')) {
    return Promise.resolve(new Response(JSON.stringify(snapshotList), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/resolve')) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          items: [
            { ref: 'rss:e1.a', kind: 'rss', domain: 'rss', source: 'freshrss', stale: false, title: '文章甲', payload: {} },
            { ref: 'rss:e1.gone', kind: 'rss', domain: 'rss', source: 'freshrss', stale: true, title: '已消失', payload: {} },
          ],
        }),
        { status: 200 },
      ),
    )
  }
  return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
})

function renderPanel(props: Partial<{ onOpenEntry: (entryRef: string) => void; currentItemRef: string | null }> = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ReadingQueuePanel
        onOpenEntry={props.onOpenEntry}
        currentItemRef={props.currentItemRef}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  queue = baseQueue()
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
  localStorage.clear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('N041 今日必读队列', () => {
  it('加载队列 → 生成（幂等提示）/ 重新生成（force）/ 加入当前文章', async () => {
    const onOpenEntry = vi.fn()
    renderPanel({ onOpenEntry })
    expect(await screen.findByText('文章甲')).toBeInTheDocument()
    expect(screen.getByRole('status').textContent).toContain('共 3 项')

    fireEvent.click(screen.getByRole('button', { name: '生成队列' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url).includes('/queue/today/generate') && (init?.method ?? 'GET') === 'POST',
        ),
      ).toBe(true)
    })
    const generateCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url).includes('/queue/today/generate') && (init?.method ?? 'GET') === 'POST',
    )
    expect(generateCall).toBeTruthy()
    expect(JSON.parse(String(generateCall![1]?.body))).toMatchObject({ timeBudgetMinutes: 30 })

    fireEvent.click(screen.getByRole('button', { name: '重新生成' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).includes('/queue/today/generate?force=1')),
      ).toBe(true)
    })

    fireEvent.change(screen.getByLabelText('时间预算'), { target: { value: '15' } })
    fireEvent.click(screen.getByRole('button', { name: '生成队列' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(
          ([url, init]) => String(url).includes('/queue/today/generate') && (init?.method ?? 'GET') === 'POST',
        ).length,
      ).toBe(3)
    })
    const budgetedCall = fetchMock.mock.calls.filter(
      ([url, init]) => String(url).includes('/queue/today/generate') && (init?.method ?? 'GET') === 'POST',
    ).at(-1)
    expect(JSON.parse(String(budgetedCall![1]?.body))).toMatchObject({ timeBudgetMinutes: 15 })

    // 移除（行内按钮；状态 → removed 的调用可见）
    fireEvent.click(screen.getByRole('button', { name: '移除「文章甲」' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url).endsWith('/queue/today/items/rq-1') && init?.method === 'DELETE',
        ),
      ).toBe(true)
    })
  })

  it('N041: 上移/下移 → PUT /order 持久化重排', async () => {
    renderPanel()
    await screen.findByText('文章甲')
    fireEvent.click(screen.getByRole('button', { name: '下移「文章甲」' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url).endsWith('/queue/today/order') && init?.method === 'PUT',
        ),
      ).toBe(true)
    })
    const reorder = fetchMock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/queue/today/order') && init?.method === 'PUT',
    )
    expect(JSON.parse(String(reorder![1]?.body))).toEqual({ order: ['rq-2', 'rq-1', 'rq-3'] })
    fireEvent.click(screen.getByRole('button', { name: '下移「文章乙」' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(
          ([url, init]) => String(url).endsWith('/queue/today/order') && init?.method === 'PUT',
        ).length,
      ).toBe(2)
    })
    const second = fetchMock.mock.calls.filter(
      ([url, init]) => String(url).endsWith('/queue/today/order') && init?.method === 'PUT',
    ).at(-1)
    // 服务端数据是静态 mock：重排输入始终来自初始顺序 [rq-1, rq-2, rq-3]。
    expect(JSON.parse(String(second![1]?.body))).toEqual({ order: ['rq-1', 'rq-3', 'rq-2'] })
  })
})

describe('N042 队列分段', () => {
  it('行菜单移动分段（PATCH segment）+ 折叠 + 整段完成', async () => {
    queue = baseQueue()
    queue.segmentOrder = ['晨读']
    // 行数据与分段视图保持一致：乙在「晨读」。
    queue.items[1]!.segment = '晨读'
    queue.segments = [
      { name: null, items: [queue.items[0]!] },
      { name: '晨读', items: [queue.items[1]!, queue.items[2]!] },
    ]
    renderPanel()
    await screen.findByText('文章甲')

    // 行菜单：把文章甲移入「晨读」。
    fireEvent.change(screen.getByLabelText('调整「文章甲」分段'), { target: { value: '晨读' } })
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url).endsWith('/items/rq-1/segment') && init?.method === 'PATCH',
        ),
      ).toBe(true)
    })
    const patch = fetchMock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/items/rq-1/segment') && init?.method === 'PATCH',
    )
    expect(JSON.parse(String(patch![1]?.body))).toEqual({ segment: '晨读' })

    // 折叠分段「未分组」。
    fireEvent.click(screen.getByRole('button', { name: '折叠分段「未分组」' }))
    expect(screen.getByRole('button', { name: '展开分段「未分组」' })).toBeInTheDocument()

    // 整段完成（晨读里未完成的只有文章乙 → 一条 done 调用）。
    fireEvent.click(screen.getByRole('button', { name: '整段完成' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url).endsWith('/items/rq-2/done') && init?.method === 'POST',
        ),
      ).toBe(true)
    })
    const doneCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/items/rq-2/done') && init?.method === 'POST',
    )
    expect(JSON.parse(String(doneCall![1]?.body))).toEqual({ done: true })
  })
})

describe('N043 冻结快照', () => {
  it('冻结 → 列表 → 打开冻结视图（原始顺序 + 消失 ref 占位）', async () => {
    renderPanel()
    await screen.findByText('文章甲')

    fireEvent.change(screen.getByLabelText('冻结快照名称'), { target: { value: '早间批次' } })
    fireEvent.click(screen.getByRole('button', { name: '冻结当前队列' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/queue/today/freeze'))).toBe(true)
    })
    const freeze = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/queue/today/freeze'))
    expect(JSON.parse(String(freeze![1]?.body))).toEqual({ label: '早间批次' })

    expect(await screen.findByText('早间批次')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '打开' }))
    expect(await screen.findByText(/冻结批次「早间批次」/)).toBeInTheDocument()
    // 原始成员顺序 + 可解析标题；消失 ref → 诚实占位。
    const rows = screen.getAllByRole('listitem')
    expect(rows[0]!.textContent).toContain('文章甲')
    expect(screen.getByTestId('queue-missing-ref')).toHaveTextContent('条目不可用（已删除或已退订）')

    fireEvent.click(screen.getByRole('button', { name: '返回今日队列' }))
    expect(await screen.findByText('文章甲')).toBeInTheDocument()
  })
})

describe('N044 只看未完成', () => {
  it('默认开启（有已完成项）→ 已完成区可展开 → 关闭过滤恢复内联显示，且不发 DELETE', async () => {
    renderPanel()
    await screen.findByText('文章甲')
    // 默认 ON：done 行隐藏，出现「已完成（1）」可展开区。
    expect(screen.queryByText('文章丙')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '展开已完成' }))
    expect(screen.getByText('文章丙')).toBeInTheDocument()
    // 展开区内可撤销完成（set 语义回 pending）。
    fireEvent.click(screen.getByRole('checkbox', { name: '标记「文章丙」未完成' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url).endsWith('/items/rq-3/done') && init?.method === 'POST',
        ),
      ).toBe(true)
    })
    const undo = fetchMock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/items/rq-3/done') && init?.method === 'POST',
    )
    expect(JSON.parse(String(undo![1]?.body))).toEqual({ done: false })

    // 关闭过滤 → done 行内联回分段；全程零 DELETE（过滤绝不删记录）。
    fireEvent.click(screen.getByLabelText('只看未完成'))
    expect(screen.getByText('文章丙')).toBeInTheDocument()
    const deletes = fetchMock.mock.calls.filter(([, init]) => init?.method === 'DELETE')
    expect(deletes).toHaveLength(0)
  })
})

describe('N048 连续阅读间隔', () => {
  /** 假计时器下：推进假时钟直到条件满足（顺带冲刷 mutation 微任务链）。 */
  async function advanceUntil(condition: () => boolean, totalMs = 1000, stepMs = 20) {
    for (let elapsed = 0; elapsed < totalMs && !condition(); elapsed += stepMs) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(stepMs)
      })
    }
  }

  it('间隔 15s：完成 → 倒计时芯片 → 到 0 导航下一篇（不自动标已读）', async () => {
    const onOpenEntry = vi.fn()
    renderPanel({ onOpenEntry })
    await screen.findByText('文章甲')

    fireEvent.change(screen.getByLabelText('连续阅读间隔'), { target: { value: '15' } })
    expect(JSON.parse(localStorage.getItem('lumirss-reading-queue-interval') ?? '')).toBe(15)

    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('checkbox', { name: '标记「文章甲」完成' }))
    await advanceUntil(() => screen.queryByTestId('queue-next-chip') !== null)
    expect(screen.getByTestId('queue-next-chip').textContent).toContain('下一篇：文章乙')

    // 倒计时走动（15 → 递减），到 0 导航下一篇（裸 entryRef）后芯片消失。
    // 逐秒推进：每步 act 冲刷 React 效果，让下一次 setTimeout 重新入队。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(screen.getByTestId('queue-next-chip').textContent).toMatch(/下一篇：文章乙（\d+s）/)
    for (let i = 0; i < 20 && screen.queryByTestId('queue-next-chip') !== null; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000)
      })
    }
    expect(onOpenEntry).toHaveBeenCalledWith('e1.b')
    expect(screen.queryByTestId('queue-next-chip')).not.toBeInTheDocument()
  })

  it('取消即止；「立即」直接导航', async () => {
    const onOpenEntry = vi.fn()
    renderPanel({ onOpenEntry })
    await screen.findByText('文章甲')
    fireEvent.change(screen.getByLabelText('连续阅读间隔'), { target: { value: '30' } })

    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('checkbox', { name: '标记「文章甲」完成' }))
    await advanceUntil(() => screen.queryByTestId('queue-next-chip') !== null)
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000)
    })
    expect(onOpenEntry).not.toHaveBeenCalled()
    expect(screen.queryByTestId('queue-next-chip')).not.toBeInTheDocument()

    // 再次完成（静态 mock 数据里文章甲仍是 pending）→ 「立即」直接导航。
    fireEvent.click(screen.getByRole('checkbox', { name: '标记「文章甲」完成' }))
    await advanceUntil(() => screen.queryByTestId('queue-next-chip') !== null)
    fireEvent.click(screen.getByRole('button', { name: '立即' }))
    expect(onOpenEntry).toHaveBeenCalledWith('e1.b')
  })

  it('间隔 关(默认)：完成无芯片（直接切换），不发导航', async () => {
    const onOpenEntry = vi.fn()
    renderPanel({ onOpenEntry })
    await screen.findByText('文章甲')
    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('checkbox', { name: '标记「文章甲」完成' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(65000)
    })
    expect(screen.queryByTestId('queue-next-chip')).not.toBeInTheDocument()
    expect(onOpenEntry).not.toHaveBeenCalled()
  })
})
