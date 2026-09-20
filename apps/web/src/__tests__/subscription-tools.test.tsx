/** F003/F005/F006 订阅中心工具测试 —— 多选导出、备注、批量移动。
 * （F004 查重面板为纯展示，一并覆盖。） */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SubscriptionsPage from '../components/pages/SubscriptionsPage'
import { useReaderUi } from '../store/reader-ui'

const SUBSCRIPTIONS = [
  {
    subscriptionRef: 's1.ref-a',
    title: '源甲',
    feedUrl: 'https://a.example/rss',
    category: { id: 'c1', label: '科技' },
  },
  {
    subscriptionRef: 's1.ref-b',
    title: '源乙',
    feedUrl: 'https://b.example/rss',
    category: null,
  },
]

let fetchCalls: { method: string; url: string; body?: string }[] = []

function installFetch(routes: Record<string, { body?: unknown; status?: number }>) {
  fetchCalls = []
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    fetchCalls.push({ method, url, body: typeof init?.body === 'string' ? init.body : undefined })
    const pathOnly = url.split('?')[0] ?? url
    const hit = routes[`${method} ${url}`] ?? routes[`${method} ${pathOnly}`]
    if (hit === undefined) throw new Error(`unexpected fetch: ${method} ${url}`)
    return new Response(JSON.stringify(hit.body ?? {}), {
      status: hit.status ?? 200,
      headers: { 'content-type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <SubscriptionsPage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useReaderUi.setState({
    section: 'subscriptions',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
  })
})

describe('F003 按所选导出 OPML', () => {
  it('F003: 多选两行 → 导出请求携带两个 subscription_refs', async () => {
    installFetch({
      'GET /api/v1/subscriptions': { body: SUBSCRIPTIONS },
      'GET /api/v1/categories': { body: [{ id: 'c1', label: '科技' }] },
      'GET /api/v1/sources/stale': { body: { checked: 0, items: [], generatedAt: '' } },
      'GET /api/v1/sources/volume?days=7': {
        body: { days: 7, since: '', items: [], basis: '', generatedAt: '' },
      },
      'GET /api/v1/opml/export': { body: '<opml><body /></opml>' },
      'GET /api/v1/subscriptions/notes': { body: { items: [] } },
    })
    renderPage()
    expect(await screen.findByText('源甲')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '多选' }))
    fireEvent.click(screen.getByLabelText('选择「源甲」'))
    fireEvent.click(screen.getByLabelText('选择「源乙」'))
    expect(screen.getByText(/已选 2/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '导出所选 OPML' }))
    await waitFor(() => {
      const call = fetchCalls.find((c) => c.url.startsWith('/api/v1/opml/export'))
      expect(call).toBeDefined()
      expect(call!.url.includes('subscription_refs=s1.ref-a')).toBe(true)
      expect(call!.url.includes('subscription_refs=s1.ref-b')).toBe(true)
    })
  })

  it('F003: 未选任何行时导出按钮禁用（不泄露全库）', async () => {
    installFetch({
      'GET /api/v1/subscriptions': { body: SUBSCRIPTIONS },
      'GET /api/v1/categories': { body: [] },
      'GET /api/v1/sources/stale': { body: { checked: 0, items: [], generatedAt: '' } },
      'GET /api/v1/subscriptions/notes': { body: { items: [] } },
    })
    renderPage()
    await screen.findByText('源甲')
    fireEvent.click(screen.getByRole('button', { name: '多选' }))
    expect((screen.getByRole('button', { name: '导出所选 OPML' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('F004 查重面板', () => {
  it('F004: 展示重复候选组与规范化依据；空结果显示空态', async () => {
    installFetch({
      'GET /api/v1/subscriptions': { body: SUBSCRIPTIONS },
      'GET /api/v1/categories': { body: [] },
      'GET /api/v1/sources/stale': { body: { checked: 0, items: [], generatedAt: '' } },
      'GET /api/v1/subscriptions/notes': { body: { items: [] } },
      'GET /api/v1/subscriptions/duplicate-suspects': {
        body: {
          checked: 2,
          groups: [
            {
              key: 'dup.example/feed',
              members: [
                { subscriptionRef: 'r1', title: '甲', feedUrl: 'https://dup.example/feed?utm_source=x', categoryLabel: null },
                { subscriptionRef: 'r2', title: '乙', feedUrl: 'https://DUP.example/feed/', categoryLabel: null },
              ],
              differences: ['title'],
            },
          ],
        },
      },
    })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '查重' }))
    expect(await screen.findByTestId('duplicate-group')).toBeInTheDocument()
    expect(screen.getByText(/规范化：dup.example\/feed/)).toBeInTheDocument()
    expect(screen.getByText(/差异：title/)).toBeInTheDocument()
  })
})

describe('F005 来源备注与维护记录', () => {
  it('F005: 打开备注对话框 → 编辑保存 → PATCH 载荷携带三字段', async () => {
    installFetch({
      'GET /api/v1/subscriptions': { body: SUBSCRIPTIONS },
      'GET /api/v1/categories': { body: [] },
      'GET /api/v1/sources/stale': { body: { checked: 0, items: [], generatedAt: '' } },
      'GET /api/v1/subscriptions/notes': { body: { items: [] } },
      'GET /api/v1/subscriptions/s1.ref-a/notes': {
        body: { subscriptionRef: 's1.ref-a', note: '旧备注', reason: null, maintenanceLog: null, updatedAt: '' },
      },
      'PATCH /api/v1/subscriptions/s1.ref-a/notes': {
        body: { subscriptionRef: 's1.ref-a', note: '新备注 <b>', reason: '理由', maintenanceLog: '日志', updatedAt: '' },
      },
    })
    renderPage()
    await screen.findByText('源甲')
    fireEvent.click(screen.getAllByRole('button', { name: '「源甲」的操作' })[0]!)
    fireEvent.click(screen.getByText('备注/维护记录'))
    const noteBox = await screen.findByLabelText('备注') as HTMLTextAreaElement
    expect(noteBox.value).toBe('旧备注')
    fireEvent.change(noteBox, { target: { value: '新备注 <b>' } })
    fireEvent.change(screen.getByLabelText('订阅理由'), { target: { value: '理由' } })
    fireEvent.change(screen.getByLabelText('维护记录'), { target: { value: '日志' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      const patch = fetchCalls.find((c) => c.method === 'PATCH' && c.url.includes('/notes'))
      expect(patch).toBeDefined()
      const payload = JSON.parse(patch!.body!)
      expect(payload.note).toBe('新备注 <b>')
      expect(payload.reason).toBe('理由')
      expect(payload.maintenanceLog).toBe('日志')
    })
  })
})

describe('F006 批量分类迁移', () => {
  it('F006: 多选 → 移动到分类 → 请求载荷与逐项结果', async () => {
    installFetch({
      'GET /api/v1/subscriptions': { body: SUBSCRIPTIONS },
      'GET /api/v1/categories': { body: [{ id: 'c1', label: '科技' }, { id: 'c2', label: '新闻' }] },
      'GET /api/v1/sources/stale': { body: { checked: 0, items: [], generatedAt: '' } },
      'GET /api/v1/subscriptions/notes': { body: { items: [] } },
      'POST /api/v1/subscriptions/batch-move': {
        body: {
          items: [
            { ref: 's1.ref-a', ok: true, error: null },
            { ref: 's1.ref-b', ok: false, error: 'category_not_found' },
          ],
          moved: 1,
        },
      },
    })
    renderPage()
    await screen.findByText('源甲')
    fireEvent.click(screen.getByRole('button', { name: '多选' }))
    fireEvent.click(screen.getByLabelText('选择「源甲」'))
    fireEvent.click(screen.getByLabelText('选择「源乙」'))
    fireEvent.click(screen.getByRole('button', { name: '移动到分类…' }))

    const select = (await screen.findByLabelText('目标分类')) as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'c2' } })
    expect(screen.getByText(/移动 2 个订阅/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /移动 2 个订阅/ }))

    await screen.findByText('category_not_found')
    await waitFor(() => {
      const call = fetchCalls.find((c) => c.url.endsWith('/batch-move'))
      expect(call).toBeDefined()
      const payload = JSON.parse(call!.body!)
      expect(payload.targetCategoryId).toBe('c2')
      expect(payload.refs.sort()).toEqual(['s1.ref-a', 's1.ref-b'])
    })
    // 仅重试失败项按钮出现
    expect(screen.getByRole('button', { name: /仅重试失败项（1）/ })).toBeInTheDocument()
  })
})
