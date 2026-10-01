/** API 来源空态治理 / 分步向导 / 详情抽屉结构 / 去开发编号 断言。
 *
 * - 空态：只有一句说明 + 「添加 API 来源」主按钮 + 可折叠帮助；
 *   全部高级接入工具不可见；
 * - 有源：列表行展示名称/状态/更新频率/最近抓取；「接入中心」出现；
 *   详情抽屉五个 tab（内容/抓取/字段/日志/高级）；
 * - 渲染输出不含开发编号（/NEW-\d/ grep 断言）；
 * - 向导：地址与认证 → 预览 JSON → 字段映射 → 有界试抓 → 保存并订阅；
 *   非法 JSON 有明确提示。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { ApiSource } from '../api/client'
import { ApiSourcesSection } from '../components/settings/ApiSourcesSection'
import { CreateApiSourceWizard } from '../components/new301/CreateApiSourceWizard'

const mocks = vi.hoisted(() => ({
  listApiSources: vi.fn(),
  createApiSource: vi.fn(),
  updateApiSource: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listApiSources: mocks.listApiSources,
    createApiSource: mocks.createApiSource,
    updateApiSource: mocks.updateApiSource,
  }
})

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const fetchCalls: { url: string }[] = []
let routes: { match: (url: string) => boolean; body: unknown }[] = []

beforeEach(() => {
  vi.clearAllMocks()
  fetchCalls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    void init
    const url = typeof input === 'string' ? input : input.toString()
    fetchCalls.push({ url })
    for (const route of routes) {
      if (route.match(url)) return jsonResponse(route.body)
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch
  // 详情抽屉各面板的默认空数据
  routes.push(
    { match: (url) => url.includes('/schema-pause'), body: { writePaused: false, pauseReason: null, drift: null } },
    { match: (url) => url.includes('/intake-quota'), body: { configured: false, used: 0, pending: 0, remaining: null, dayKey: 'd', windowReset: 'w', honestyNote: '未配置每日上限。', sourceUuid: 'src-1', maxItemsPerDay: null } },
    { match: (url) => url.includes('/mapping-samples'), body: { items: [] } },
    { match: (url) => url.includes('/pagination-probe'), body: { probedAt: 'now', stopReason: 'single', pageCount: 0, itemCount: 0, duplicatePages: 0, gapPages: 0, pages: [] } },
    { match: (url) => url.includes('/webhooks/dead-letters'), body: { items: [] } },
  )
  mocks.updateApiSource.mockResolvedValue(apiSourceFixture())
})

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function apiSourceFixture(over: Partial<ApiSource> = {}): ApiSource {
  return {
    uuid: 'src-1',
    name: 'Hacker News API',
    endpoint: 'https://hacker-news.firebaseio.com/v0/item.json',
    itemsExpr: 'items',
    fieldMap: { id: 'id', title: 'title', url: 'url', published: 'time', body: 'text' },
    enabled: true,
    confirmedSchema: true,
    createdAt: '2026-09-01T08:00:00Z',
    lastStatus: 'ok',
    lastError: null,
    lastSuccessAt: '2026-09-11T08:00:00Z',
    maxRunsPerHour: 4,
    respectRetryAfter: true,
    nextAllowedRun: null,
    ...over,
  }
}

// ---- 空态治理 ----

describe('API 来源空态治理', () => {
  it('无源：一句说明 + 添加主按钮 + 可折叠帮助；高级工具与接入中心不可见', async () => {
    mocks.listApiSources.mockResolvedValue({ items: [] })
    const container = render(withProviders(<ApiSourcesSection />)).container
    expect(await screen.findByText('连接 JSON API，自动生成订阅。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /添加 API 来源/ })).toBeInTheDocument()

    // 次级帮助默认折叠，点击展开
    expect(screen.queryByText(/任意返回 JSON 列表的 HTTP API/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '了解支持的 API' }))
    expect(screen.getByText(/任意返回 JSON 列表的 HTTP API/)).toBeInTheDocument()
    expect(screen.getByText(/支持页码与游标两种分页/)).toBeInTheDocument()

    // 十个高级工具入口全部不可见；接入中心不出现
    expect(screen.queryByText('接入中心')).toBeNull()
    expect(screen.queryByText(/字段映射/)).toBeNull()
    expect(screen.queryByText(/试抓页数上限/)).toBeNull()
    expect(screen.queryByText(/Webhook 收件箱/)).toBeNull()
    expect(screen.queryByText(/签名密钥轮换/)).toBeNull()
    // 渲染输出无开发编号
    expect(/NEW-\d/.test(container.textContent ?? '')).toBe(false)
  })
})

// ---- 有源列表 + 详情抽屉 ----

describe('API 来源列表与详情抽屉', () => {
  it('行展示名称/host/更新频率/最近抓取；接入中心出现（默认折叠）', async () => {
    mocks.listApiSources.mockResolvedValue({ items: [apiSourceFixture()] })
    const container = render(withProviders(<ApiSourcesSection />)).container
    expect(await screen.findByText('Hacker News API')).toBeInTheDocument()
    expect(screen.getByText('hacker-news.firebaseio.com')).toBeInTheDocument()
    expect(screen.getByText(/更新频率 ≤4 次\/小时/)).toBeInTheDocument()
    expect(screen.getByText(/最近抓取：/)).toBeInTheDocument()

    const centerEntry = screen.getByText('接入中心')
    // 折叠态：子面板未挂载，零请求
    expect(fetchCalls.filter((call) => call.url.includes('/webhooks/'))).toHaveLength(0)
    fireEvent.click(centerEntry)
    await waitFor(() => {
      expect(fetchCalls.some((call) => call.url.includes('/webhooks/dead-letters'))).toBe(true)
    })
    expect(/NEW-\d/.test(container.textContent ?? '')).toBe(false)
  })

  it('点击行打开详情抽屉：五个 tab（内容/抓取/字段/日志/高级）', async () => {
    mocks.listApiSources.mockResolvedValue({ items: [apiSourceFixture()] })
    render(withProviders(<ApiSourcesSection />))
    fireEvent.click(await screen.findByRole('button', { name: '查看 Hacker News API 详情' }))

    const drawer = await screen.findByRole('dialog', { name: '来源详情：Hacker News API' })
    const tablist = within(drawer).getByRole('tablist', { name: '来源详情分区' })
    for (const label of ['内容', '抓取', '字段', '日志', '高级']) {
      expect(within(tablist).getByRole('tab', { name: label })).toBeInTheDocument()
    }

    // 内容 tab：概要 + 启用开关
    expect(within(drawer).getAllByText('≤ 4 次 / 小时').length).toBeGreaterThan(0)

    // 抓取 tab：分页设置 / 受限试抓 / 变更预警 / 每日上限 / 预算
    fireEvent.click(within(tablist).getByRole('tab', { name: '抓取' }))
    expect(within(drawer).getByText('分页设置')).toBeInTheDocument()
    expect(within(drawer).getByText('受限试抓（≤5 页）')).toBeInTheDocument()
    expect(within(drawer).getByText('抓取变更预警')).toBeInTheDocument()
    expect(within(drawer).getByText('每日上限')).toBeInTheDocument()

    // 字段 tab
    fireEvent.click(within(tablist).getByRole('tab', { name: '字段' }))
    expect(within(drawer).getByText('字段映射')).toBeInTheDocument()
    expect(within(drawer).getByText('样本试映射')).toBeInTheDocument()

    // 高级 tab：凭据轮换（write-only 掩码）+ 签名密钥 + 配置转移
    fireEvent.click(within(tablist).getByRole('tab', { name: '高级' }))
    fireEvent.click(within(drawer).getByRole('button', { name: '测试并轮换凭据' }))
    const credentialInput = within(drawer).getByLabelText('新凭据（16–128 位字母/数字/连字符/下划线）')
    expect(credentialInput.getAttribute('type')).toBe('password')
    expect(within(drawer).getByText('签名密钥轮换（管理员）')).toBeInTheDocument()
    expect(within(drawer).getByText('配置转移（不含秘密）')).toBeInTheDocument()
  })
})

// ---- 分步向导 ----

function openWizardAndFillAddress(): void {
  render(withProviders(<CreateApiSourceWizard open onClose={() => {}} />))
  fireEvent.change(screen.getByLabelText('名称'), { target: { value: '新来源' } })
  fireEvent.change(screen.getByLabelText('Endpoint'), {
    target: { value: 'https://api.example.com/v1/items' },
  })
}

describe('新增 API 来源分步向导', () => {
  it('五步顺序推进；最终保存并订阅调用 createApiSource', async () => {
    mocks.createApiSource.mockResolvedValue(
      apiSourceFixture({ uuid: 'src-new', name: '新来源', atomPath: '/feeds/api-sources/src-new.atom?secret=one-time' }),
    )
    openWizardAndFillAddress()
    expect(screen.getByText('1. 地址与认证')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '下一步' }))
    expect(screen.getByText('2. 预览 JSON')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('items 表达式（JMESPath）'), {
      target: { value: 'items' },
    })

    fireEvent.click(screen.getByRole('button', { name: '下一步' }))
    expect(screen.getByText('3. 字段映射')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('id 表达式'), { target: { value: 'id' } })
    fireEvent.change(screen.getByLabelText('title 表达式'), { target: { value: 'name' } })

    fireEvent.click(screen.getByRole('button', { name: '下一步' }))
    expect(screen.getByText('4. 有界试抓')).toBeInTheDocument()
    expect(screen.getByLabelText('分页模式')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '下一步' }))
    expect(screen.getByText('5. 保存并订阅')).toBeInTheDocument()
    expect(screen.getByText(/列表表达式/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '保存并订阅' }))
    await waitFor(() =>
      expect(mocks.createApiSource).toHaveBeenCalledWith(
        expect.objectContaining({
          name: '新来源',
          endpoint: 'https://api.example.com/v1/items',
          itemsExpr: 'items',
        }),
      ),
    )
    // 一次性成功面板
    expect(await screen.findByText('/feeds/api-sources/src-new.atom?secret=one-time')).toBeInTheDocument()
    expect(screen.getByText(/此地址仅显示一次/)).toBeInTheDocument()
  })

  it('地址非法时第一步不放行并给出提示', () => {
    render(withProviders(<CreateApiSourceWizard open onClose={() => {}} />))
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: 'X' } })
    fireEvent.change(screen.getByLabelText('Endpoint'), { target: { value: 'not-a-url' } })
    expect(screen.getByText('地址需为 http(s) 完整 URL。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下一步' })).toHaveProperty('disabled', true)
  })

  it('第 2 步样例预览：非法 JSON 有明确提示（不发起请求）', () => {
    openWizardAndFillAddress()
    fireEvent.click(screen.getByRole('button', { name: '下一步' }))
    fireEvent.change(screen.getByLabelText('items 表达式（JMESPath）'), {
      target: { value: 'items' },
    })
    fireEvent.click(screen.getByRole('tab', { name: '用样例预览' }))
    fireEvent.change(screen.getByLabelText('粘贴一段上游会返回的 JSON 样例'), {
      target: { value: '{not-json' },
    })
    expect(screen.getByText('不是合法 JSON，请检查后重试。')).toBeInTheDocument()
    expect(
      fetchCalls.filter((call) => call.url.includes('preview-sample')),
    ).toHaveLength(0)
  })
})
