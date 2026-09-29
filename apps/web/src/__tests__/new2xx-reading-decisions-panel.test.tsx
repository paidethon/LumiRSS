/** NEW-221..230 阅读决策面板 —— 入口测试：十组 section 真实挂载 +
 * 分时段队列的真实交互（创建时段 → 列表出现）。
 *
 * 全部走 fetch mock（无网络）；断言的是用户可见行为：标题、列表、
 * POST 请求体，而不是内部状态。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingDecisionsPanel } from '../components/new2xx/ReadingDecisionsPanel'

let slots: Array<Record<string, unknown>>

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  const json = (data: unknown, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(data), { status }))

  if (method === 'GET' && url.includes('/queue/slots') && !url.includes('/queue/slots/')) {
    return json({ slots })
  }
  if (method === 'POST' && url.includes('/queue/slots')) {
    const body = JSON.parse(String(init?.body ?? '{}')) as { name: string }
    const slot = {
      id: `slot-${slots.length + 1}`,
      name: body.name,
      position: slots.length + 1,
      createdAt: '2026-09-29T08:00:00Z',
      lastOpenedAt: null,
      pendingCount: 0,
      doneCount: 0,
    }
    slots.push(slot)
    return json(slot, 201)
  }
  if (method === 'GET' && url.includes('/queue/today')) {
    return json({
      queueDate: '2026-09-29',
      items: [
        {
          id: 'rq-1',
          itemRef: 'rss:e1.a',
          addedAt: '2026-09-29T08:00:00Z',
          position: 1,
          queueDate: '2026-09-29',
          source: 'budget',
          status: 'pending',
          segment: null,
          title: '文章甲',
          estimateMinutes: 2,
        },
      ],
    })
  }
  if (method === 'GET' && url.includes('/queue/workload/speed')) {
    return json({
      charsPerMinute: 400,
      customized: false,
      updatedAt: null,
      note: '默认值，可在下方校正。',
    })
  }
  if (method === 'GET' && url.includes('/reading/reminders')) {
    return json({ items: [], channel: 'in-app', note: '仅在应用内提示。' })
  }
  if (method === 'GET' && url.includes('/queue/capacity/pending')) {
    return json({ capacity: null, enabled: false, queueCount: 0, items: [] })
  }
  if (method === 'GET' && url.includes('/queue/capacity')) {
    return json({ capacity: null, enabled: false, note: null })
  }
  if (method === 'GET' && url.includes('/interruption-notes/all')) {
    return json({ items: [] })
  }
  if (method === 'GET' && url.includes('/reading/pacts')) {
    return json({
      items: [],
      note: '双方独立确认；对方私人阅读轨迹不可见。',
      counterpartVisibility: 'unavailable-cross-user',
    })
  }
  if (method === 'GET' && url.includes('/queue/topics/report')) {
    return json({ topics: [], duplicatedTopics: [], advisory: true, note: '仅建议。' })
  }
  if (method === 'GET' && url.includes('/queue/topics')) {
    return json({ itemRef: 'rss:e1.a', topics: [] })
  }
  if (method === 'GET' && url.includes('/queue/prereqs')) {
    return json({ itemRef: 'rss:e1.a', prereqs: [], unmetCount: 0, advisory: true, note: '不阻止跳读。' })
  }
  if (method === 'GET' && url.includes('/reading/section-plans')) {
    return json({
      id: 'plan-1',
      itemRef: 'rss:e1.a',
      sections: [],
      progress: { totalSections: 0, doneSections: 0, pendingSections: 0 },
    })
  }
  if (method === 'GET' && url.includes('/interruption-notes')) {
    return json({ itemRef: 'rss:e1.a', note: null, archivedCount: 0 })
  }
  return json({ error: { type: 'unknown_error', message: `未mock的请求 ${method} ${url}` } }, 500)
})

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ReadingDecisionsPanel onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  slots = [
    {
      id: 'slot-1',
      name: '通勤',
      position: 1,
      createdAt: '2026-09-29T07:00:00Z',
      lastOpenedAt: null,
      pendingCount: 2,
      doneCount: 1,
    },
  ]
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockClear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('阅读决策面板（NEW-221..230）', () => {
  it('默认渲染分时段队列，创建时段真实 POST 并出现在列表', async () => {
    renderPanel()

    // 初始列表来自 GET /queue/slots（slot 名会同时出现在列表与目标时段
    // option 里，因此用 span 选择器收窄到列表行）
    expect(await screen.findByText('通勤', { selector: 'span' })).toBeTruthy()
    expect(screen.getByText('待读 2')).toBeTruthy()
    expect(screen.getByText('完成 1')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('新时段名'), { target: { value: '晚间' } })
    fireEvent.click(screen.getByRole('button', { name: '创建时段' }))

    await waitFor(() => {
      expect(slots.map((slot) => slot.name)).toContain('晚间')
    })
    const createCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/api/v1/queue/slots') && (init?.method ?? 'GET') === 'POST',
    )
    expect(createCall).toBeTruthy()
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({ name: '晚间' })
    expect(await screen.findByText('晚间', { selector: 'span' })).toBeTruthy()
  })

  it('十个分组 tab 依次渲染各自的 section（真实挂载面）', async () => {
    renderPanel()
    await screen.findByText('分时段阅读队列')

    const expectations: Array<[string, string]> = [
      ['依赖', '队列依赖关系'],
      ['工作量', '队列工作量预览'],
      ['预约', '阅读预约清单'],
      ['积压向导', '积压处理向导'],
      ['容量', '队列容量上限'],
      ['章节计划', '章节级阅读计划'],
      ['中断便签', '阅读中断便签'],
      ['约定卡', '阅读约定卡'],
      ['主题', '队列重复主题提醒'],
    ]
    for (const [tab, title] of expectations) {
      fireEvent.click(screen.getByRole('tab', { name: tab }))
      expect(await screen.findByRole('heading', { name: title })).toBeTruthy()
    }

    // 回到分时段：缓存恢复，不重复请求也能渲染
    fireEvent.click(screen.getByRole('tab', { name: '分时段' }))
    expect(await screen.findByText('分时段阅读队列')).toBeTruthy()
  })
})
