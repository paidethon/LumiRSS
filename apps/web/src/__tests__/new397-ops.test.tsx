/** NEW-397/398/400 状态页/处理单/使用清理 — Web 入口测试（无虚构可用率、
 * 逐步记录、脱敏材料、本人关闭；服务真源在 BFF tests）。 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ServiceStatusPanel } from '../components/new391/ServiceStatusPanel'
import { RunbookPanel } from '../components/new391/RunbookPanel'
import { ModuleCleanupPanel } from '../components/new391/ModuleCleanupPanel'

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

describe('NEW-397 服务状态页', () => {
  it('未检测如实显示；立即检测发 POST；页面绝不出现可用率/百分比', async () => {
    mockRoute(
      (url) => url === '/api/v1/status/services',
      () =>
        jsonResponse({
          surfaces: [
            { key: 'control_db', label: 'Lumi 控制库', status: 'unknown', detail: '', checkedAt: null, history: [] },
            { key: 'freshrss', label: 'FreshRSS 配置', status: 'unconfigured', detail: '未配置：FRESHRSS_BASE_URL。', checkedAt: 'TP', history: [] },
          ],
          notes: ['本页只报告本地真实检测结果，不提供可用率百分比。'],
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/status/services/check' && init?.method === 'POST',
      () =>
        jsonResponse({
          surfaces: [
            { key: 'control_db', label: 'Lumi 控制库', status: 'ok', detail: '控制库可读写。', checkedAt: 'TP2', history: [] },
          ],
          notes: [],
        }),
    )
    renderWithQuery(<ServiceStatusPanel />)
    expect(await screen.findByText('未检测')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '立即检测' }))
    await waitFor(() => {
      expect(
        calls.some((call) => call.url === '/api/v1/status/services/check'),
      ).toBe(true)
    })
    expect(screen.getAllByText('本页只报告本地真实检测结果，不提供可用率百分比。').length).toBeGreaterThan(0)
    expect(screen.queryByText(/可用率.*\d+%/)).toBeNull()
  })
})

describe('NEW-398 处理单', () => {
  it('列出验证过的处理单；开单并逐步记录；升级显示脱敏材料', async () => {
    mockRoute(
      (url) => url === '/api/v1/support/runbooks',
      () =>
        jsonResponse({
          runbooks: [
            {
              code: 'connection_error',
              title: '无法连接 FreshRSS（connection_error）',
              verified: 'v',
              steps: [
                { index: 1, title: '打开管理台系统面板确认服务检测', detail: 'd1' },
                { index: 2, title: '核对环境变量', detail: 'd2' },
              ],
            },
          ],
        }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/support/runbooks/connection_error/sessions' &&
        init?.method === 'POST',
      () =>
        jsonResponse({
          id: 's1', code: 'connection_error',
          title: '无法连接 FreshRSS（connection_error）', status: 'open',
          steps: [
            { index: 1, title: '打开管理台系统面板确认服务检测', detail: 'd1' },
            { index: 2, title: '核对环境变量', detail: 'd2' },
          ],
          outcomes: [], escalatedNote: '', material: null,
        }, 201),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/support/runbooks/sessions/s1/steps' && init?.method === 'POST',
      () => jsonResponse({ sessionId: 's1', stepIndex: 1, outcome: 'tried', recordedAt: 'TP' }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/support/runbooks/sessions/s1/escalate' && init?.method === 'POST',
      () =>
        jsonResponse({
          id: 's1', status: 'escalated',
          material: {
            code: 'connection_error', version: '2.0.1',
            steps: [{ stepIndex: 1, outcome: 'tried' }],
            userNote: '还是不行', generatedAt: 'TP',
          },
        }),
    )
    renderWithQuery(<RunbookPanel />)
    fireEvent.click(
      await screen.findByRole('button', { name: '开始处理' }),
    )
    expect(await screen.findByText('1. 打开管理台系统面板确认服务检测')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: '记录「试过这步」' })[0]!)
    await waitFor(() => {
      expect(
        calls.some((call) => call.url === '/api/v1/support/runbooks/sessions/s1/steps'),
      ).toBe(true)
    })
    fireEvent.click(
      await screen.findByRole('button', { name: '没解决，升级为求助材料' }),
    )
    fireEvent.change(await screen.findByLabelText(/求助备注/), {
      target: { value: '还是不行' },
    })
    fireEvent.click(
      await screen.findByRole('button', { name: '生成脱敏求助材料' }),
    )
    await waitFor(
      () => {
        expect(screen.queryByText(/求助材料已生成（脱敏）/)).not.toBeNull()
      },
      { timeout: 4000 },
    )
    expect(screen.getByText(/错误码 connection_error · 版本 2\.0\.1/)).toBeInTheDocument()
  })
})

describe('NEW-400 使用清理', () => {
  it('模块计数实时显示；本人关闭需选择数据去留', async () => {
    mockRoute(
      (url) => url === '/api/v1/settings/module-cleanup',
      () =>
        jsonResponse({
          modules: [
            {
              key: 'notification_aggregation',
              label: '通知聚合规则',
              description: '同来源通知合并摘要；关闭后回到平铺视图。',
              enabledCount: 2,
              closure: null,
            },
          ],
          note: '清理只由你本人关闭，绝不根据行为推断自动关闭；启用中的计数实时来自各功能自己的数据。',
        }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/settings/module-cleanup/notification_aggregation/close' &&
        init?.method === 'POST',
      () =>
        jsonResponse({
          moduleId: 'notification_aggregation', retention: 'keep',
          detail: '规则已停用，数据保留。', closedAt: 'TP', closureId: 'c1',
        }),
    )
    renderWithQuery(<ModuleCleanupPanel />)
    expect(await screen.findByText('启用中 2 项')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '我不再需要这个功能' }))
    fireEvent.click(await screen.findByRole('button', { name: '关闭并保留数据' }))
    await waitFor(() => {
      const post = calls.find((call) => call.url.endsWith('/close'))
      expect(post).toBeDefined()
      expect(JSON.parse(String(post!.init?.body))).toEqual({ retention: 'keep' })
    })
  })
})
