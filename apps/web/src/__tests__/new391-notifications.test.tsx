/** NEW-391..394 通知收件箱/聚合/静默/撤销 — Web 入口测试。
 * 环境jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF：
 * services/bff/tests/test_new391..394_*.py）。 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  AggregationRulesPanel,
  NotificationCenterPanel,
} from '../components/new391/NotificationCenterPanel'
import { QuietHoursPanel } from '../components/new391/QuietHoursPanel'

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

const calls: { url: string; init?: RequestInit }[] = []
let routes: {
  match: (url: string, init?: RequestInit) => boolean
  respond: (url: string, init?: RequestInit) => Response
}[] = []

function mockRoute(
  matcher: (url: string, init?: RequestInit) => boolean,
  responder: (url: string, init?: RequestInit) => Response,
): void {
  routes.push({ match: matcher, respond: responder })
}

beforeEach(() => {
  calls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    calls.push({ url, init })
    for (const route of routes) {
      if (route.match(url, init)) return route.respond(url, init)
    }
    return jsonResponse({ error: { type: 'not_mocked', message: url } }, 404)
  }) as typeof fetch
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('NEW-391 通知收件箱', () => {
  it('无事件时诚实显示空态，不编造通知', async () => {
    mockRoute(
      (url) => url === '/api/v1/notifications',
      () => jsonResponse({ items: [], counts: {}, unread: 0 }),
    )
    renderWithQuery(<NotificationCenterPanel />)
    await waitFor(() => {
      expect(screen.getByText(/没有真实事件就没有通知行/)).toBeInTheDocument()
    })
  })

  it('NEW-394：已撤销动作的通知不渲染可执行按钮，只显示失效原因', async () => {
    mockRoute(
      (url) => url === '/api/v1/notifications',
      () =>
        jsonResponse({
          items: [
            {
              id: '7',
              kind: 'task_failed',
              source: 'digest',
              title: '日报失败',
              body: '',
              ref: 'digest:1',
              actionable: false,
              invalidReason: '原事件已撤销：日报配置已删除。',
              revokedAt: 'TP',
              occurredAt: 'TP',
              createdAt: 'TP',
              readAt: null,
            },
            {
              id: '8',
              kind: 'task_completed',
              source: 'backup',
              title: '备份完成',
              body: '',
              ref: 'backup:9',
              actionable: true,
              invalidReason: null,
              revokedAt: null,
              occurredAt: 'TP',
              createdAt: 'TP',
              readAt: null,
            },
          ],
          counts: {},
          unread: 2,
        }),
    )
    renderWithQuery(<NotificationCenterPanel />)
    await waitFor(() => {
      expect(screen.getByText('日报失败')).toBeInTheDocument()
    })
    // 失效原因可见；该条目没有「标记已读」动作（不可执行按钮不存在）
    expect(screen.getByText(/动作已失效：原事件已撤销/)).toBeInTheDocument()
    const item = screen
      .getByText('日报失败')
      .closest('[data-n391-notification="7"]')
    expect(item).not.toBeNull()
    expect(item!.querySelector('button')?.textContent).not.toContain('标记已读')
    // 未撤销条目仍有已读按钮
    const okItem = screen.getByText('备份完成').closest('[data-n391-notification="8"]')
    expect(okItem!.textContent).toContain('标记已读')
  })

  it('标记已读与全部已读走集合语义端点', async () => {
    mockRoute(
      (url) => url === '/api/v1/notifications',
      () =>
        jsonResponse({
          items: [
            {
              id: '8',
              kind: 'task_completed',
              source: 'backup',
              title: '备份完成',
              body: '',
              ref: '',
              actionable: true,
              invalidReason: null,
              revokedAt: null,
              occurredAt: 'TP',
              createdAt: 'TP',
              readAt: null,
            },
          ],
          counts: {},
          unread: 1,
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/notifications/read-all' && init?.method === 'POST',
      () => jsonResponse({ marked: 1 }),
    )
    renderWithQuery(<NotificationCenterPanel />)
    const readAll = await screen.findByRole('button', { name: '全部已读' })
    fireEvent.click(readAll)
    await waitFor(() => {
      expect(
        calls.some((call) => call.url === '/api/v1/notifications/read-all'),
      ).toBe(true)
    })
  })

  it('按类型过滤改变请求参数', async () => {
    mockRoute(
      (url) => url === '/api/v1/notifications',
      () => jsonResponse({ items: [], counts: {}, unread: 0 }),
    )
    renderWithQuery(<NotificationCenterPanel />)
    fireEvent.click(await screen.findByRole('button', { name: '任务失败' }))
    await waitFor(() => {
      expect(calls.some((call) => call.url === '/api/v1/notifications?kind=task_failed')).toBe(
        true,
      )
    })
  })
})

describe('NEW-392 聚合规则', () => {
  it('创建规则 + 分组摘要展开即逐条原始事件', async () => {
    mockRoute(
      (url) => url === '/api/v1/notifications/aggregation-rules',
      (init) =>
        init?.method === 'POST'
          ? jsonResponse({
              id: 'r1', kind: 'task_failed', source: 'digest', label: '日报',
              enabled: true, createdAt: 'TP',
            }, 201)
          : jsonResponse({ rules: [] }),
    )
    mockRoute(
      (url) => url === '/api/v1/notifications/grouped',
      () =>
        jsonResponse({
          groups: [
            {
              kind: 'task_failed',
              source: 'digest',
              total: 2,
              unread: 1,
              items: [
                { id: '1', title: '日报失败 1' },
                { id: '2', title: '日报失败 2' },
              ],
            },
          ],
          flat: [],
          ruleCount: 1,
        }),
    )
    renderWithQuery(<AggregationRulesPanel />)
    fireEvent.change(await screen.findByLabelText('来源（精确匹配）'), {
      target: { value: 'digest' },
    })
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }))
    await waitFor(() => {
      expect(
        calls.some(
          (call) =>
            call.url === '/api/v1/notifications/aggregation-rules' &&
            call.init?.method === 'POST',
        ),
      ).toBe(true)
    })
    // 分组摘要可展开；展开即逐条原始事件（数据未被合并）
    const expand = screen
      .getAllByRole('button')
      .find(
        (button) =>
          button.closest('[data-n391-subsection]') !== null &&
          button.textContent!.includes('聚合：任务失败 × digest'),
      )
    expect(expand).toBeDefined()
    fireEvent.click(expand!)
    await waitFor(() => {
      expect(screen.getByText('日报失败 1')).toBeInTheDocument()
      expect(screen.getByText('日报失败 2')).toBeInTheDocument()
    })
  })
})

describe('NEW-393 静默时段', () => {
  it('保存静默设置 PUT 窗口+时区；汇总显示真实计数', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/notifications/quiet-hours' && init?.method === 'PUT',
      () =>
        jsonResponse({
          enabled: true, startHHMM: '22:00', endHHMM: '08:00',
          timeZone: 'Asia/Shanghai', updatedAt: 'TP',
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/notifications/quiet-summary',
      () =>
        jsonResponse({
          enabled: true, inQuiet: false, quietEndsAt: null, windowStart: null,
          unreadTotal: 3, unreadDuringWindow: 2,
          byKind: { task_failed: 2, share_event: 1 },
          note: '当前不在静默时段；汇总为最近静默窗口以来的未读事件。',
        }),
    )
    renderWithQuery(<QuietHoursPanel />)
    fireEvent.click(await screen.findByRole('button', { name: '保存静默设置' }))
    await waitFor(() => {
      const put = calls.find(
        (call) =>
          call.url === '/api/v1/notifications/quiet-hours' &&
          call.init?.method === 'PUT',
      )
      expect(put).toBeDefined()
      expect(JSON.parse(String(put!.init?.body))).toEqual({
        startHHMM: '22:00',
        endHHMM: '08:00',
        timeZone: 'Asia/Shanghai',
        enabled: true,
      })
    })
    await waitFor(() => {
      expect(screen.getByText(/窗口内未读 2 条/)).toBeInTheDocument()
      expect(screen.getByText(/未读共 3 条/)).toBeInTheDocument()
    })
  })
})
