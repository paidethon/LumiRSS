/** R18 测试 — OPML 导入自动发现并使用 RSSHub（前端面）。
 *
 * 覆盖：
 * - OpmlImportDialog「RSSHub 优化」模式：选文件 → plan（只读，只发
 *   plan 请求）→ 默认策略「优先已验证 RSSHub」→ 确认 → apply（默认
 *   不带 strategy 参数）→ server-confirmed 结果卡（计数/条目状态诚实
 *   说明）→ 再导入一份；
 * - 策略切换：manual 只勾选 manualChoice 项（autoReplace 无勾选框），
 *   未勾选时确认禁用，载荷携带 approved + chosen（计划内候选路由）；
 * - prefer_native：计划卡隐藏，apply 带 strategy=prefer_native；
 * - RSSHub 未配置 → 诚实警示；超大文件本地拦截（零请求）；
 * - SourceStatsDrawer 的 R18 替换映射区：原始地址/当前地址/撤销
 *   （revert POST + 诚实 note）、保留旧源的只读关联、无映射不渲染。
 * fetch 全部 mock，无真实网络。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OpmlImportDialog from '../components/OpmlImportDialog'
import SubscriptionsPage from '../components/pages/SubscriptionsPage'
import { useReaderUi } from '../store/reader-ui'

const REF = 's1.ZmVlZC83'
const SUBSCRIPTION = {
  subscriptionRef: REF,
  title: 'Tech Feed',
  feedUrl: 'https://tech.example/rss',
  category: null,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

interface FetchState {
  fn: ReturnType<typeof vi.fn>
  calls: { method: string; url: string }[]
}

function makeFetch(
  routes: Record<string, () => Response>,
  fallback?: () => Response,
): FetchState {
  const calls: { method: string; url: string }[] = []
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const pathOnly = url.split('?')[0] ?? url
    const handler = routes[`${method} ${url}`] ?? routes[`${method} ${pathOnly}`]
    if (handler === undefined) {
      if (fallback === undefined) {
        throw new Error(`unexpected fetch: ${method} ${url}`)
      }
      return fallback()
    }
    calls.push({ method, url })
    return handler()
  })
  return { fn, calls }
}

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function makeFile(content: string, name = 'subs.opml', size?: number): File {
  const file = new File([content], name, { type: 'text/xml' })
  if (size !== undefined) {
    Object.defineProperty(file, 'size', { value: size })
  }
  return file
}

function selectRsshubFile(file: File) {
  const input = document.getElementById('opml-rsshub-import-file') as HTMLInputElement
  expect(input).not.toBeNull()
  fireEvent.change(input, { target: { files: [file] } })
}

function candidate(overrides: Record<string, unknown>) {
  return {
    routePath: '/sspai/matrix',
    namespace: 'sspai',
    title: '少数派',
    params: {},
    missingParams: [],
    confidence: 'high',
    basis: '路径吻合',
    ambiguous: false,
    requires: null,
    needsCredentials: false,
    ...overrides,
  }
}

const PLAN_BODY = {
  rsshubConfigured: true,
  totalFeeds: 4,
  fileDuplicates: 0,
  invalidEntries: 0,
  counts: { autoReplace: 1, manualChoice: 1, needsCredentials: 1, keepNative: 1 },
  items: [
    {
      index: 0,
      title: 'Matrix',
      xmlUrl: 'https://sspai.com/matrix',
      htmlUrl: 'https://sspai.com',
      category: 'Tech',
      decision: 'autoReplace',
      chosenRoutePath: '/sspai/matrix',
      note: null,
      match: {
        kind: 'native',
        candidates: [candidate({})],
        autoRoutePath: '/sspai/matrix',
        note: null,
      },
    },
    {
      index: 1,
      title: '36kr 热榜',
      xmlUrl: 'https://36kr.com/hot-list',
      htmlUrl: null,
      category: null,
      decision: 'manualChoice',
      chosenRoutePath: null,
      note: '同域存在多条可解释该地址的路由，请人工选择。',
      match: {
        kind: 'native',
        candidates: [
          candidate({
            routePath: '/36kr/hot-list',
            namespace: '36kr',
            title: '资讯热榜',
            confidence: 'medium',
            ambiguous: true,
            basis: '同域多路由，需人工选择',
          }),
          candidate({
            routePath: '/36kr/:category',
            namespace: '36kr',
            title: '资讯',
            confidence: 'medium',
            ambiguous: true,
            basis: '同域多路由，需人工选择',
          }),
        ],
        autoRoutePath: null,
        note: '同域存在多条可解释该地址的路由，请人工选择。',
      },
    },
    {
      index: 2,
      title: '知乎动态',
      xmlUrl: 'https://www.zhihu.com/people/activities/x',
      htmlUrl: null,
      category: null,
      decision: 'needsCredentials',
      chosenRoutePath: null,
      note: '唯一候选路由需要 RSSHub 实例配置凭据，不会静默替换。',
      match: {
        kind: 'native',
        candidates: [
          candidate({
            routePath: '/zhihu/people/activities/:id',
            namespace: 'zhihu',
            title: '知乎用户动态',
            requires: { cookies: true },
            needsCredentials: true,
          }),
        ],
        autoRoutePath: null,
        note: '唯一候选路由需要 RSSHub 实例配置凭据，不会静默替换。',
      },
    },
    {
      index: 3,
      title: '博客',
      xmlUrl: 'https://blog.example.com/rss',
      htmlUrl: null,
      category: null,
      decision: 'keepNative',
      chosenRoutePath: null,
      note: '站点不在 RSSHub 路由覆盖范围内，保留原生订阅。',
      match: { kind: 'unknown', candidates: [], autoRoutePath: null, note: '站点不在覆盖范围。' },
    },
  ],
}

const MAPPING = {
  id: 'm1',
  originalUrl: 'https://sspai.com/matrix',
  rsshubUrl: 'http://rsshub:1200/sspai/matrix',
  namespace: 'sspai',
  routePath: '/sspai/matrix',
  strategy: 'prefer_rsshub',
  keptOldSource: false,
  status: 'active',
  createdAt: '2026-10-02T00:00:00Z',
  revertedAt: null,
}

const APPLY_BODY = {
  strategy: 'prefer_rsshub',
  replaced: [
    {
      originalUrl: 'https://sspai.com/matrix',
      title: 'Matrix',
      keptOldSource: false,
      rsshubUrl: 'http://rsshub:1200/sspai/matrix',
      validated: true,
      mapping: MAPPING,
    },
  ],
  addedNative: [
    { originalUrl: 'https://36kr.com/hot-list', title: '36kr 热榜', categoryLabel: null, categoryApplied: false },
    { originalUrl: 'https://www.zhihu.com/people/activities/x', title: '知乎动态', categoryLabel: null, categoryApplied: false },
    { originalUrl: 'https://blog.example.com/rss', title: '博客', categoryLabel: null, categoryApplied: false },
  ],
  keptOldSource: [],
  skipped: [],
  failed: [],
  mappings: [MAPPING],
  counts: { replaced: 1, addedNative: 3, keptOldSource: 0, skipped: 0, failed: 0 },
  entryStateNote:
    'FreshRSS 已读/收藏/批注状态绑定条目地址，无法跨源安全迁移：原地址已订阅的来源保留旧源并关联新源（绝不自动退订）。',
}

function openRsshubMode(routes: Record<string, () => Response>) {
  const fetchState = makeFetch(routes)
  vi.stubGlobal('fetch', fetchState.fn)
  render(withProviders(<OpmlImportDialog open onClose={() => {}} />))
  fireEvent.click(screen.getByRole('tab', { name: 'RSSHub 优化' }))
  return fetchState
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({
    section: 'subscriptions',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('R18 导入对话框（RSSHub 优化模式）', () => {
  it('默认优先已验证 RSSHub：plan 只读 → 确认才 apply（默认无 strategy 参数）→ 结果卡', async () => {
    const fetchState = openRsshubMode({
      'POST /api/v1/opml/import/rsshub-plan': () => jsonResponse(PLAN_BODY),
      'POST /api/v1/opml/import/rsshub-apply': () => jsonResponse(APPLY_BODY),
    })

    selectRsshubFile(makeFile('<opml><body/></opml>'))

    // plan 到达：摘要与逐项决策真实渲染；apply 尚未发生
    expect(await screen.findByTestId('rsshub-plan-summary')).toHaveTextContent(
      'RSSHub 匹配计划（4 项）',
    )
    expect(screen.getByText(/自动替换 1/)).toBeInTheDocument()
    expect(screen.getByText(/需授权 1/)).toBeInTheDocument()
    expect(screen.getByText('Matrix')).toBeInTheDocument()
    expect(screen.getByText('需授权')).toBeInTheDocument()
    expect(
      fetchState.calls.some((c) => c.url.includes('rsshub-apply')),
    ).toBe(false)

    // 默认策略：优先已验证 RSSHub（可访问名含帮助文案，用正则锚定）
    const preferred = screen.getByRole('radio', {
      name: /优先已验证 RSSHub/,
    }) as HTMLInputElement
    expect(preferred.checked).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: '确认导入' }))
    expect(await screen.findByTestId('rsshub-result')).toHaveTextContent(
      '替换 1 · 原生导入 3 · 跳过 0 · 失败 0',
    )
    // 条目状态诚实边界原文可见（不冒充可迁移）
    expect(screen.getByText(/无法跨源安全迁移/)).toBeInTheDocument()

    const applyCall = fetchState.calls.find((c) => c.url.includes('rsshub-apply'))
    expect(applyCall).toBeDefined()
    expect(applyCall!.url).toBe('/api/v1/opml/import/rsshub-apply')

    // 结果态：可再导入一份（重置回文件选择）
    fireEvent.click(screen.getByRole('button', { name: '再导入一份' }))
    expect(screen.getByText('选择 OPML 文件（RSSHub 优化）')).toBeInTheDocument()
  })

  it('manual：只勾选 manualChoice 项，载荷携带 approved + 计划内 chosen', async () => {
    const fetchState = openRsshubMode({
      'POST /api/v1/opml/import/rsshub-plan': () => jsonResponse(PLAN_BODY),
      'POST /api/v1/opml/import/rsshub-apply': () =>
        jsonResponse({ ...APPLY_BODY, strategy: 'manual', counts: { replaced: 0, addedNative: 4, keptOldSource: 0, skipped: 0, failed: 0 } }),
    })

    selectRsshubFile(makeFile('<opml><body/></opml>'))
    await screen.findByTestId('rsshub-plan-summary')

    fireEvent.click(screen.getByRole('radio', { name: /手动确认/ }))

    // manualChoice 项出现勾选框；autoReplace 项没有（manual 只做显式勾选）
    const box = screen.getByLabelText('替换 36kr 热榜') as HTMLInputElement
    expect(screen.queryByLabelText('替换 Matrix')).toBeNull()
    // 未勾选 → 确认禁用（无事可做，绝不强制替换）
    expect(screen.getByRole('button', { name: '确认导入' })).toBeDisabled()

    fireEvent.click(box)
    expect(box.checked).toBe(true)
    expect(screen.getByRole('button', { name: '确认导入' })).not.toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '确认导入' }))
    await screen.findByTestId('rsshub-result')

    const applyCall = fetchState.calls.find((c) => c.url.includes('rsshub-apply'))
    expect(applyCall).toBeDefined()
    const decoded = decodeURIComponent(applyCall!.url)
    expect(decoded).toContain('strategy=manual')
    expect(decoded).toContain('approved=1')
    // chosen = 计划内首选候选路由（候选依据在计划卡可见）
    expect(decoded).toContain('chosen=1|/36kr/hot-list')
  })

  it('prefer_native：计划卡隐藏，apply 带 strategy=prefer_native', async () => {
    const fetchState = openRsshubMode({
      'POST /api/v1/opml/import/rsshub-plan': () => jsonResponse(PLAN_BODY),
      'POST /api/v1/opml/import/rsshub-apply': () =>
        jsonResponse({ ...APPLY_BODY, strategy: 'prefer_native' }),
    })

    selectRsshubFile(makeFile('<opml><body/></opml>'))
    await screen.findByTestId('rsshub-plan-summary')

    fireEvent.click(screen.getByRole('radio', { name: /优先原生/ }))
    expect(screen.queryByTestId('rsshub-plan-summary')).toBeNull()
    expect(screen.getByRole('button', { name: '确认导入' })).not.toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '确认导入' }))
    await screen.findByTestId('rsshub-result')
    const applyCall = fetchState.calls.find((c) => c.url.includes('rsshub-apply'))
    expect(applyCall!.url).toBe('/api/v1/opml/import/rsshub-apply?strategy=prefer_native')
  })

  it('RSSHub 未配置 → 诚实警示（只能原生导入）', async () => {
    openRsshubMode({
      'POST /api/v1/opml/import/rsshub-plan': () =>
        jsonResponse({ ...PLAN_BODY, rsshubConfigured: false }),
    })
    selectRsshubFile(makeFile('<opml><body/></opml>'))
    expect(await screen.findByRole('alert')).toHaveTextContent('RSSHub 未配置')
  })

  it('超大文件本地拦截：零请求', async () => {
    const fetchState = openRsshubMode({})
    selectRsshubFile(makeFile('<opml/>', 'big.opml', 2 * 1024 * 1024 + 1))
    expect(await screen.findByText('OPML 文件超过 2 MiB 上限。')).toBeInTheDocument()
    expect(fetchState.fn).not.toHaveBeenCalled()
  })
})

// ---- SourceStatsDrawer：R18 替换映射区 --------------------------------------

const TODAY = new Date().toISOString().slice(0, 10)

function volumePayload() {
  return {
    days: 30,
    since: '2026-09-02T00:00:00Z',
    basis: 'published_at（search_entries 派生投影，可重建）',
    generatedAt: '2026-10-02T00:00:00Z',
    items: [
      {
        feedUrl: 'http://rsshub:1200/sspai/matrix',
        title: 'Matrix',
        publishedCount: 5,
        lastPublishedAt: `${TODAY}T08:00:00Z`,
        lastSyncedAt: `${TODAY}T09:00:00Z`,
        collectionTiming: null,
        daily: [{ date: TODAY, count: 5 }],
      },
    ],
  }
}

async function openStatsFor(
  feedUrl: string,
  routes: Record<string, () => Response>,
) {
  const subscription = { ...SUBSCRIPTION, feedUrl }
  // 订阅页会带出若干与本测试无关的查询（条目等）——宽松兜底返回空对象，
  // 断言只锚定真实路由的可见 UI。
  const fetchState = makeFetch(
    {
      'GET /api/v1/subscriptions': () => jsonResponse([subscription]),
      'GET /api/v1/categories': () => jsonResponse([]),
      'GET /api/v1/sources/aliases': () => jsonResponse({ items: [] }),
      'GET /api/v1/feeds': () => jsonResponse([]),
      'GET /api/v1/sources/volume?days=30&daily=true': () => jsonResponse(volumePayload()),
      'GET /api/v1/opml/rsshub-mappings': () => jsonResponse({ items: [] }),
      ...routes,
    },
    () => jsonResponse({}),
  )
  vi.stubGlobal('fetch', fetchState.fn)
  render(withProviders(<SubscriptionsPage />))
  fireEvent.click(await screen.findByRole('button', { name: '「Tech Feed」的操作' }))
  fireEvent.click(await screen.findByRole('menuitem', { name: '统计与工具' }))
  return fetchState
}

describe('R18 来源详情替换映射区', () => {
  it('RSSHub 替换源：显示原始地址/当前地址，撤销发 revert 并展示诚实 note', async () => {
    const fetchState = await openStatsFor('http://rsshub:1200/sspai/matrix', {
      'GET /api/v1/opml/rsshub-mappings': () =>
        jsonResponse({ items: [MAPPING] }),
      'POST /api/v1/opml/rsshub-mappings/m1/revert': () =>
        jsonResponse({
          mapping: { ...MAPPING, status: 'reverted', revertedAt: '2026-10-02T01:00:00Z' },
          originalSubscribed: true,
          rsshubSourceRemoved: false,
          note: '已恢复订阅原始地址；RSSHub 来源未自动退订，可在来源管理中手动处理。',
        }),
    })

    await screen.findByTestId('source-volume-chart')
    expect(await screen.findByText('RSSHub 替换映射')).toBeInTheDocument()
    expect(screen.getByText('https://sspai.com/matrix')).toBeInTheDocument()
    expect(screen.getByText(/本订阅/)).toBeInTheDocument()
    // 撤销前置说明：RSSHub 源不会被自动退订（诚实边界）
    expect(screen.getByText(/不会被自动退订/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '恢复原始地址' }))
    expect(await screen.findByText(/已恢复订阅原始地址/)).toBeInTheDocument()
    expect(
      fetchState.calls.some(
        (c) => c.method === 'POST' && c.url === '/api/v1/opml/rsshub-mappings/m1/revert',
      ),
    ).toBe(true)
  })

  it('保留旧源的原始订阅：只读关联 RSSHub 源，无撤销按钮', async () => {
    await openStatsFor('https://sspai.com/matrix', {
      'GET /api/v1/opml/rsshub-mappings': () =>
        jsonResponse({
          items: [{ ...MAPPING, keptOldSource: true }],
        }),
    })

    expect(await screen.findByText('RSSHub 替换映射')).toBeInTheDocument()
    expect(screen.getByText(/已关联 RSSHub 源/)).toBeInTheDocument()
    expect(screen.getByText(/保留的原始源/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '恢复原始地址' })).toBeNull()
  })

  it('无映射的订阅：映射区不渲染（不制造噪音）', async () => {
    await openStatsFor('http://rsshub:1200/sspai/matrix', {})
    await screen.findByTestId('source-volume-chart')
    await waitFor(() => {
      expect(screen.queryByText('RSSHub 替换映射')).toBeNull()
    })
  })
})
