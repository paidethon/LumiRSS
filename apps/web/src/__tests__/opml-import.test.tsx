/** Gate 4 测试 — 0013 OPML 导入/导出 + FreshRSS 状态/逃生入口。
 *
 * 覆盖：
 * - OpmlImportDialog（订阅页外壳）：选文件 → 预览（无写入请求）→
 *   人工确认 → import → server-confirmed 结果 → invalidate → 订阅列表刷新；
 * - 超大文件本地拦截（不发请求）；opml_invalid 诚实错误文案；
 *   全部重复 → 确认禁用（无事可做）；
 * - SourcesSettingsSection（设置外壳）：OPML 导出下载、FreshRSS 状态
 *   （成功/连接错误/凭据错误）、escape hatch（有 url 渲染链接 / null
 *   不渲染链接 + 诚实说明）。
 * fetch 全部 mock，无真实网络。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OpmlImportDialog from '../components/OpmlImportDialog'
import { SourcesSettingsSection } from '../components/settings/SourcesSettingsSection'
import SubscriptionsPage from '../components/pages/SubscriptionsPage'
import { useReaderUi } from '../store/reader-ui'

const SUBSCRIPTIONS = [
  {
    subscriptionRef: 's1.ZmVlZC83',
    title: 'Existing Feed',
    feedUrl: 'https://existing.example/rss',
    category: null,
  },
]

const PREVIEW_BODY = {
  totalFeeds: 3,
  newFeeds: 2,
  duplicates: 1,
  invalidEntries: 0,
  categories: [{ label: 'Tech', feedCount: 2 }],
}

const IMPORT_BODY = {
  added: [
    { feedUrl: 'https://a.example/rss', title: 'Feed A', categoryLabel: 'Tech', categoryApplied: true },
    { feedUrl: 'https://b.example/rss', title: 'Feed B', categoryLabel: null, categoryApplied: false },
  ],
  duplicates: [{ feedUrl: 'https://existing.example/rss', title: 'Existing Feed' }],
  failed: [{ feedUrl: 'https://broken.example/rss', title: 'Broken Feed', error: 'feed_rejected' }],
  categoriesCreated: ['Tech'],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

interface FetchState {
  fn: ReturnType<typeof vi.fn>
  calls: { method: string; url: string; body?: unknown }[]
}

function makeFetch(routes: Record<string, () => Response>): FetchState {
  const calls: { method: string; url: string; body?: unknown }[] = []
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const handler = routes[`${method} ${url}`]
    if (handler === undefined) {
      throw new Error(`unexpected fetch: ${method} ${url}`)
    }
    calls.push({ method, url, body: init?.body })
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

function selectFile(file: File) {
  const input = document.getElementById('opml-import-file') as HTMLInputElement
  expect(input).not.toBeNull()
  fireEvent.change(input, { target: { files: [file] } })
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

describe('OpmlImportDialog（订阅页外壳）', () => {
  it('严格 preview-before-mutation：选文件只发预览请求，确认后才 import', async () => {
    const fetchState = makeFetch({
      'POST /api/v1/opml/import/preview': () => jsonResponse(PREVIEW_BODY),
      'POST /api/v1/opml/import': () => jsonResponse(IMPORT_BODY),
      'GET /api/v1/subscriptions': () => jsonResponse(SUBSCRIPTIONS),
      'GET /api/v1/categories': () => jsonResponse([]),
      'GET /api/v1/feeds': () => jsonResponse(SUBSCRIPTIONS),
      'GET /api/v1/entries': () => jsonResponse({ items: [], nextCursor: null }),
    })
    vi.stubGlobal('fetch', fetchState.fn)
    render(withProviders(<OpmlImportDialog open onClose={() => {}} />))

    selectFile(makeFile('<opml><body/></opml>'))

    // 预览出现：数量与分类真实展示
    expect(await screen.findByText('导入 OPML')).toBeInTheDocument()
    await waitFor(() => {
      expect(fetchState.calls.some((c) => c.url === '/api/v1/opml/import/preview')).toBe(true)
    })
    expect(fetchState.calls.some((c) => c.url === '/api/v1/opml/import')).toBe(false)
    // 分类真实展示（label + 数量；文本为「分类（N）：Label（M）」整段渲染）
    expect(await screen.findByText('分类（1）：Tech（2）')).toBeInTheDocument()
    // 确认按钮就绪（有 2 个新源可导入）
    expect(screen.getByRole('button', { name: '确认导入' })).not.toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '确认导入' }))
    await waitFor(() => {
      expect(fetchState.calls.some((c) => c.url === '/api/v1/opml/import')).toBe(true)
    })
    // server-confirmed 结果如实展示（added / failed / 新建分类）
    expect(await screen.findByText(/已导入 2 个订阅源/)).toBeInTheDocument()
    expect(screen.getByText(/失败 1 个/)).toBeInTheDocument()
    expect(screen.getByText(/新建分类：Tech/)).toBeInTheDocument()
    expect(screen.getByText('FreshRSS 无法添加该源（地址无效或不可达）')).toBeInTheDocument()
  })

  it('导入成功后 invalidate → subscriptions 重新拉取', async () => {
    const fetchState = makeFetch({
      'POST /api/v1/opml/import/preview': () => jsonResponse(PREVIEW_BODY),
      'POST /api/v1/opml/import': () => jsonResponse(IMPORT_BODY),
      'GET /api/v1/subscriptions': () => jsonResponse(SUBSCRIPTIONS),
      'GET /api/v1/categories': () => jsonResponse([]),
      'GET /api/v1/feeds': () => jsonResponse(SUBSCRIPTIONS),
      'GET /api/v1/entries': () => jsonResponse({ items: [], nextCursor: null }),
    })
    vi.stubGlobal('fetch', fetchState.fn)
    // 预挂载 subscriptions query（导入后 invalidate 需要已有 observer）
    render(
      withProviders(
        <>
          <SubscriptionsPage />
          <OpmlImportDialog open onClose={() => {}} />
        </>,
      ),
    )
    await screen.findByText('Existing Feed')

    selectFile(makeFile('<opml><body/></opml>'))
    await screen.findByText('分类（1）：Tech（2）')
    const before = fetchState.calls.filter((c) => c.url === '/api/v1/subscriptions').length
    fireEvent.click(screen.getByRole('button', { name: '确认导入' }))
    await screen.findByText(/已导入 2 个订阅源/)
    // invalidate 生效：subscriptions 至少被重新拉取一次
    await waitFor(() => {
      const after = fetchState.calls.filter((c) => c.url === '/api/v1/subscriptions').length
      expect(after).toBeGreaterThan(before)
    })
  })

  it('超大文件：本地拦截，不发任何请求', async () => {
    const fetchState = makeFetch({})
    vi.stubGlobal('fetch', fetchState.fn)
    render(withProviders(<OpmlImportDialog open onClose={() => {}} />))

    selectFile(makeFile('<opml/>', 'big.opml', 2 * 1024 * 1024 + 1))

    expect(await screen.findByText('OPML 文件超过 2 MiB 上限。')).toBeInTheDocument()
    expect(fetchState.fn).not.toHaveBeenCalled()
  })

  it('opml_invalid → 诚实错误文案，确认保持禁用', async () => {
    const fetchState = makeFetch({
      'POST /api/v1/opml/import/preview': () =>
        jsonResponse({ error: { type: 'opml_invalid', message: 'bad' } }, 400),
    })
    vi.stubGlobal('fetch', fetchState.fn)
    render(withProviders(<OpmlImportDialog open onClose={() => {}} />))

    selectFile(makeFile('not xml'))
    expect(
      await screen.findByText('文件不是有效的 OPML（无法解析或缺少正文）。'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认导入' })).toBeDisabled()
  })

  it('全部重复 → 确认禁用（无事可做，绝不强制导入）', async () => {
    const allDuplicates = { ...PREVIEW_BODY, newFeeds: 0, duplicates: 3 }
    const fetchState = makeFetch({
      'POST /api/v1/opml/import/preview': () => jsonResponse(allDuplicates),
    })
    vi.stubGlobal('fetch', fetchState.fn)
    render(withProviders(<OpmlImportDialog open onClose={() => {}} />))

    selectFile(makeFile('<opml><body/></opml>'))
    await waitFor(() => {
      expect(fetchState.fn).toHaveBeenCalled()
    })
    expect(screen.getByRole('button', { name: '确认导入' })).toBeDisabled()
  })
})

describe('SourcesSettingsSection（设置外壳）', () => {
  const OPERATIONS_OK = {
    lumi: { status: 'healthy', version: '0.1.0' },
    sqlite: { status: 'healthy' },
    freshrss: { status: 'healthy', configured: true, latencyMs: 5, lastCheckedAt: null, error: null },
    rsshub: { status: 'unconfigured', configured: false, latencyMs: null, lastCheckedAt: null, error: null, restartRequired: false, pendingConfigCount: 0 },
    backup: { webdavConfigured: false, lastBackup: null },
  }
  const baseRoutes = {
    'GET /api/v1/subscriptions': () => jsonResponse(SUBSCRIPTIONS),
    'GET /api/v1/freshrss-ui': () => jsonResponse({ url: null }),
    'GET /api/v1/operations/status': () => jsonResponse(OPERATIONS_OK),
  }

  it('OPML 导出：请求 /api/v1/opml/export 并触发下载', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const opmlResponse = new Response('<?xml version="1.0"?><opml/>', {
      status: 200,
      headers: { 'content-type': 'text/x-opml' },
    })
    const fetchState = makeFetch({
      ...baseRoutes,
      'GET /api/v1/opml/export': () => opmlResponse,
    })
    vi.stubGlobal('fetch', fetchState.fn)
    const createObjectURL = vi.fn(() => 'blob:opml-test')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL }))

    render(withProviders(<SourcesSettingsSection />))
    fireEvent.click(await screen.findByRole('button', { name: '导出 OPML' }))

    await waitFor(() => {
      expect(fetchState.calls.some((c) => c.url === '/api/v1/opml/export')).toBe(true)
    })
    await waitFor(() => {
      expect(createObjectURL).toHaveBeenCalled()
    })
    expect(click).toHaveBeenCalled()
    expect(await screen.findByText('已开始下载')).toBeInTheDocument()
  })

  it('导出失败（FreshRSS 不可达）→ 诚实错误文案', async () => {
    const fetchState = makeFetch({
      ...baseRoutes,
      'GET /api/v1/opml/export': () =>
        jsonResponse({ error: { type: 'connection_error', message: 'down' } }, 502),
    })
    vi.stubGlobal('fetch', fetchState.fn)
    render(withProviders(<SourcesSettingsSection />))
    fireEvent.click(await screen.findByRole('button', { name: '导出 OPML' }))
    expect(
      await screen.findByText('无法连接 FreshRSS，请确认服务正在运行。'),
    ).toBeInTheDocument()
  })

  it('FreshRSS 状态：连接正常时显示订阅数（真实请求结果）', async () => {
    const fetchState = makeFetch({ ...baseRoutes })
    vi.stubGlobal('fetch', fetchState.fn)
    render(withProviders(<SourcesSettingsSection />))
    expect(await screen.findByText('服务正常，当前 1 个订阅源')).toBeInTheDocument()
    // 未配置 public URL → 不渲染外链；Lumi 内管理入口（订阅中心）始终可用
    expect(screen.queryByText('高级：在 FreshRSS 中管理')).toBeNull()
    expect(screen.getByRole('button', { name: '打开订阅中心' })).toBeInTheDocument()
  })

  it('FreshRSS 连接错误：只报告真实错误（authentication_error 文案）', async () => {
    const fetchState = makeFetch({
      'GET /api/v1/subscriptions': () =>
        jsonResponse({ error: { type: 'authentication_error', message: 'bad creds' } }, 502),
      'GET /api/v1/freshrss-ui': () => jsonResponse({ url: null }),
    })
    vi.stubGlobal('fetch', fetchState.fn)
    render(withProviders(<SourcesSettingsSection />))
    expect(
      await screen.findByText(/FreshRSS 拒绝了凭据（API 密码可能已变更）/),
    ).toBeInTheDocument()
    // 不编造任何「健康度 / 最后抓取时间」类伪指标
    expect(screen.queryByText(/健康/)).toBeNull()
    expect(screen.queryByText(/最后/)).toBeNull()
  })

  it('escape hatch：配置了 public URL → 渲染外链（noopener noreferrer）', async () => {
    const fetchState = makeFetch({
      'GET /api/v1/subscriptions': () => jsonResponse(SUBSCRIPTIONS),
      'GET /api/v1/freshrss-ui': () => jsonResponse({ url: 'https://rss.example.com' }),
    })
    vi.stubGlobal('fetch', fetchState.fn)
    render(withProviders(<SourcesSettingsSection />))
    const link = await screen.findByRole('link', { name: /在 FreshRSS 中管理/ })
    expect(link).toHaveAttribute('href', 'https://rss.example.com')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })
})
