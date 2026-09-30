/** NEW-371..380 运行治理中心 — Web 入口测试（折叠零请求 / 展开主路径 /
 * step-up 403 事件 / 诚实边界文案）。环境：jsdom；fetch 按 URL 匹配
 * mock（服务真源在 BFF：services/bff/tests/test_new37*.py..test_new380*.py）。 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { AdminOpsCenter } from '../components/new371/AdminOpsCenter'
import { onStepUpRequired, type StepUpScope } from '../lib/step-up'

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

const fetchCalls: { url: string; init?: RequestInit }[] = []
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


function unprobedGraph(): Response {
  return jsonResponse({
    features: [
      {
        key: 'native_rss',
        label: '原生 RSS/Atom 订阅',
        deps: [{ key: 'sqlite', kind: 'Lumi SQLite 控制库', status: 'unknown', detail: '', probedAt: null }],
        ready: false,
      },
    ],
    notes: ['未探测的依赖如实标 unknown。'],
  })
}

function probedGraph(): Response {
  return jsonResponse({
    features: [
      {
        key: 'native_rss',
        label: '原生 RSS/Atom 订阅',
        deps: [
          { key: 'sqlite', kind: 'Lumi SQLite 控制库', status: 'configured', detail: '控制库文件存在。', probedAt: 'TP' },
        ],
        ready: true,
      },
    ],
    probedAt: 'TP',
    notes: [],
  })
}

function callsTo(prefix: string): number {
  return fetchCalls.filter((call) => call.url.startsWith(prefix)).length
}

function expand(subsectionId: string): void {
  const toggles = screen
    .getAllByRole('button')
    .filter((button) => {
      const host = button.closest('[data-n371-subsection]')
      return host !== null && host.getAttribute('data-n371-subsection') === subsectionId
    })
  expect(toggles.length).toBeGreaterThan(0)
  fireEvent.click(toggles[0])
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    fetchCalls.push({ url, init })
    for (const route of routes) {
      if (route.match(url, init)) return route.respond(url, init)
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch
})

afterEach(() => {
  cleanup()
  routes = []
})

describe('NEW-371..380 运行治理中心（Web 入口）', () => {
  it('折叠态零请求；十个子区都在', () => {
    renderWithQuery(<AdminOpsCenter />)
    expect(callsTo('/api/v1/')).toBe(0)
    for (const label of [
      '后台任务日历',
      '任务优先级',
      '维护通知演练',
      '用户资源账单',
      '配额变更批次',
      '实例配置草案',
      '后台任务阻塞定位',
      '实例功能依赖图',
      '用户问题工单',
      '运维交接摘要',
    ]) {
      expect(screen.getByText(label)).toBeTruthy()
    }
  })

  it('展开任务日历：渲染七个任务档 + 无 shell 诚实边界；暂停 403 step_up_required 触发提权事件', async () => {
    const scopes: (StepUpScope | undefined)[] = []
    onStepUpRequired((scope) => scopes.push(scope))
    mockRoute(
      (url) => url === '/api/v1/admin/task-calendar',
      () =>
        jsonResponse({
          kinds: [
            {
              kind: 'search_sync',
              label: '搜索投影同步（逐账户）',
              intervalSeconds: 0,
              scheduled: false,
              slotState: 'not_scheduled',
              plannedNext: null,
              pause: { active: false, reason: '', impact: '', createdAt: '' },
              pauseEnforced: false,
              enforcedBy: 'loop',
              impact: null,
            },
          ],
          recentRuns: [],
          ownScopeResults: [],
          notes: ['间隔型任务的运行相位未知（plannedNext 为 null 是诚实值）。'],
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/admin/task-calendar/search_sync/pause',
      () =>
        jsonResponse(
          {
            error: {
              type: 'step_up_required',
              message: '需要临时提权',
              operation: 'task_kind_pause',
              targetUserId: 'u-owner',
            },
          },
          403,
        ),
    )
    renderWithQuery(<AdminOpsCenter />)
    expect(callsTo('/api/v1/')).toBe(0)
    expand('n371-calendar')
    await waitFor(() => expect(screen.getAllByText('搜索投影同步（逐账户）').length).toBeGreaterThan(0))
    expect(screen.getByText('间隔型任务的运行相位未知（plannedNext 为 null 是诚实值）。')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('暂停原因'), { target: { value: '维护' } })
    fireEvent.change(screen.getByLabelText('影响说明（必填）'), { target: { value: '投影暂停' } })
    fireEvent.click(screen.getByText('登记暂停（需临时提权）'))
    await waitFor(() =>
      expect(screen.getByText('该操作需要临时提权验证（输入管理员密码后再试一次）。')).toBeTruthy(),
    )
    expect(scopes.at(-1)?.operation).toBe('task_kind_pause')
  })

  it('展开阻塞定位：计数与安全处置如实呈现（锁类无强制解锁入口）', async () => {
    mockRoute(
      (url) => url === '/api/v1/admin/task-blockers',
      () =>
        jsonResponse({
          blockers: [
            {
              category: 'lock',
              userId: 'u1',
              scopeKind: 'digest',
              expiresAt: 'T1',
              safeAction: '等待租约过期；无强制解锁入口。',
            },
          ],
          counts: { quota: 0, rate_limit: 0, lock: 1, dependency: 0 },
          safeActions: {},
          diagnosedAt: 'T0',
          notes: ['lock 类没有强制解锁入口。'],
        }),
    )
    renderWithQuery(<AdminOpsCenter />)
    expand('n377-blockers')
    await waitFor(() => expect(screen.getByText(/锁 1/)).toBeTruthy())
    expect(screen.getByText(/等待租约过期；无强制解锁入口。/)).toBeTruthy()
  })

  it('我的资源账单：只有计数与字节，带诚实边界说明', async () => {
    mockRoute(
      (url) => url === '/api/v1/account/resource-bill',
      () =>
        jsonResponse({
          userId: 'u-self',
          counts: { feeds: 3, entriesIndexed: 120, libraryItems: 4, clips: 1, assets: 2 },
          storage: { databaseBytes: 10, assetBytes: 20, totalBytes: 30 },
          compute: { aiCallsToday: 5, recentBackupSeconds: 1.5 },
          computedAt: 'T0',
          contentNote: '账单只有计数与字节，绝无文章内容；FreshRSS 侧抓取消耗不经过 Lumi，无法统计。',
        }),
    )
    renderWithQuery(<AdminOpsCenter />)
    expand('n374-bill')
    fireEvent.click(screen.getByText('我的资源账单（与查阅同一口径）'))
    await waitFor(() => expect(screen.getByText(/磁盘合计 30 字节/)).toBeTruthy())
    expect(screen.getByText(/绝无文章内容/)).toBeTruthy()
  })

  it('配置草案：形成草案展示差异与生效条件；应用 403 step_up_required 透传作用域', async () => {
    const scopes: (StepUpScope | undefined)[] = []
    onStepUpRequired((scope) => scopes.push(scope))
    mockRoute(
      (url) => url === '/api/v1/admin/config-drafts',
      (_url, init) => {
        if (init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as { value: string }
          return jsonResponse({
            draftId: 'd1',
            key: 'allow_public_registration',
            currentValue: '0',
            draftValue: body.value,
            validation: { ok: true, checks: ['布尔校验'] },
            effectiveNotes: ['立即生效：新注册请求按新值判定。'],
            status: 'draft',
            differs: body.value !== '0',
          })
        }
        return jsonResponse({ keys: [{ key: 'allow_public_registration', type: 'bool', label: '公开注册开关' }] })
      },
    )
    mockRoute(
      (url) => url === '/api/v1/admin/config-drafts/d1/apply',
      () =>
        jsonResponse(
          {
            error: {
              type: 'step_up_required',
              message: '需要临时提权',
              operation: 'config_draft_apply',
              targetUserId: 'u-owner',
            },
          },
          403,
        ),
    )
    renderWithQuery(<AdminOpsCenter />)
    expand('n376-config-draft')
    fireEvent.change(screen.getByLabelText('拟变更值（布尔键填 0 或 1）'), { target: { value: '1' } })
    fireEvent.click(screen.getByText('形成草案'))
    await waitFor(() => expect(screen.getByText(/当前 0 → 草案 1/)).toBeTruthy())
    expect(screen.getByText(/生效条件：立即生效/)).toBeTruthy()

    fireEvent.click(screen.getByText('应用（需临时提权）'))
    await waitFor(() =>
      expect(screen.getByText('该操作需要临时提权验证（输入管理员密码后再试一次）。')).toBeTruthy(),
    )
    expect(scopes.at(-1)?.operation).toBe('config_draft_apply')
  })

  it('交接摘要：生成展示未完成项与脱敏声明；确认后导出成功', async () => {
    mockRoute(
      (url) => url === '/api/v1/admin/handoff-summaries',
      (_url, init) => {
        if (init?.method === 'POST') {
          return jsonResponse({
            summaryId: 'h1',
            confirmed: false,
            payload: {
              generatedAt: 'T0',
              schemaVersion: 303,
              deploy: { available: false, reason: null, imageTag: null },
              openItems: {
                tickets: [{ id: 't1', subject: 's', status: 'open' }],
                taskPauses: [],
                quotaBatchesDraft: [],
                configDrafts: [],
                maintenanceWindows: [],
                dependencyGaps: [],
                recentBlockers: [],
              },
              secretsInventory: [],
              redactionNote: '本清单脱敏生成：秘密只有状态位。',
            },
          })
        }
        return jsonResponse({ items: [] })
      },
    )
    mockRoute(
      (url) => url === '/api/v1/admin/handoff-summaries/h1/confirm',
      () => jsonResponse({ summaryId: 'h1', confirmed: true }),
    )
    mockRoute(
      (url) => url === '/api/v1/admin/handoff-summaries/h1/export',
      () =>
        jsonResponse({
          summaryId: 'h1',
          exportedAt: 'T9',
          payload: {},
          redactionNote: '脱敏导出。',
        }),
    )
    renderWithQuery(<AdminOpsCenter />)
    expand('n380-handoff')
    fireEvent.click(screen.getByText('生成脱敏交接清单'))
    await waitFor(() => expect(screen.getByText(/未完成项：工单 1/)).toBeTruthy())
    expect(screen.getByText(/秘密只有状态位/)).toBeTruthy()

    fireEvent.click(screen.getByText('确认（需临时提权）'))
    await waitFor(() => expect(screen.getByText('已确认（对清单内容负责）。')).toBeTruthy())
    fireEvent.click(screen.getByText('导出'))
    await waitFor(() => expect(screen.getByText(/已导出（T9）/)).toBeTruthy())
  })

  it('功能依赖图：未探测如实 unknown，探测后展示实际探测时间', async () => {
    let probed = false
    mockRoute(
      (url) => url === '/api/v1/admin/feature-dependencies',
      () => (probed ? probedGraph() : unprobedGraph()),
    )
    mockRoute(
      (url) => url === '/api/v1/admin/feature-dependencies/probe',
      () => probedGraph(),
    )
    renderWithQuery(<AdminOpsCenter />)
    expand('n378-feature-deps')
    await waitFor(() => expect(screen.getByText('原生 RSS/Atom 订阅')).toBeTruthy())
    await waitFor(() => expect(screen.getByText(/未探测$/)).toBeTruthy())
    probed = true
    fireEvent.click(screen.getByText('运行本地探测（零网络）'))
    await waitFor(() => expect(screen.getByText(/已配置（探测于 TP）/)).toBeTruthy())
  })
})
