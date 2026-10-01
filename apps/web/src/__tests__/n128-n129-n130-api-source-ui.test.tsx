/** N128/N129/N130 — Web UI 测试（API 来源：样例预览 / 预算块 / 轮换面板）。
 *
 * - N129：详情抽屉「抓取」tab 的预算块渲染（每小时运行预算 + 下次允许
 *   运行时间 + 「遇限流将等待，不使用替代密钥规避」文案）；
 * - N128：新增向导第 2 步「用样例预览」—— 粘贴 JSON → 结构候选下拉 →
 *   预览调用 previewApiSourceSample 并渲染 sampleMode 结果；
 * - N130：详情抽屉「高级」的轮换（write-only 掩码输入）—— 预演结果
 *   （脱敏）与轮换成功 note 渲染。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { ApiSource } from '../api/client'
import { ApiError } from '../api/client'
import { ApiSourcesSection } from '../components/settings/ApiSourcesSection'

const mocks = vi.hoisted(() => ({
  listApiSources: vi.fn(),
  updateApiSource: vi.fn(),
  previewApiSourceSample: vi.fn(),
  rotateApiSourceCredential: vi.fn(),
  testApiSourceCredential: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listApiSources: mocks.listApiSources,
    updateApiSource: mocks.updateApiSource,
    previewApiSourceSample: mocks.previewApiSourceSample,
    rotateApiSourceCredential: mocks.rotateApiSourceCredential,
    testApiSourceCredential: mocks.testApiSourceCredential,
  }
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
    confirmedSchema: false,
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

// 详情抽屉各面板会立即发起的请求（new301 模块走全局 fetch）。
beforeEach(() => {
  vi.clearAllMocks()
  mocks.updateApiSource.mockResolvedValue(apiSourceFixture())
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    void init
    const url = typeof input === 'string' ? input : input.toString()
    const body = url.includes('/mapping-samples')
      ? { items: [] }
      : url.includes('/schema-pause')
        ? { writePaused: false, pauseReason: null, drift: null }
        : url.includes('/intake-quota')
          ? { configured: false, used: 0, pending: 0, remaining: null, dayKey: 'd', windowReset: 'w', honestyNote: '未配置每日上限。', sourceUuid: 'src-1', maxItemsPerDay: null }
          : url.includes('/webhooks/dead-letters')
            ? { items: [] }
            : { probedAt: 'now', stopReason: 'single', pageCount: 0, itemCount: 0, duplicatePages: 0, gapPages: 0, pages: [] }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }) as typeof fetch
})

/** 打开来源详情抽屉并切换到指定 tab。 */
async function openDetailTab(tab: '抓取' | '字段' | '日志' | '高级'): Promise<HTMLElement> {
  mocks.listApiSources.mockResolvedValue({ items: [apiSourceFixture()] })
  render(withProviders(<ApiSourcesSection />))
  fireEvent.click(await screen.findByRole('button', { name: '查看 Hacker News API 详情' }))
  const drawer = await screen.findByRole('dialog', { name: '来源详情：Hacker News API' })
  fireEvent.click(within(drawer).getByRole('tab', { name: tab }))
  return drawer
}

describe('N129 限额友好预算块（详情抽屉 · 抓取）', () => {
  it('展开后渲染每小时运行预算 + 下次允许运行 + 限流等待文案', async () => {
    const drawer = await openDetailTab('抓取')
    fireEvent.click(within(drawer).getByText('每小时运行预算'))
    expect(
      await within(drawer).findByLabelText('每小时运行预算 Hacker News API'),
    ).toBeTruthy()
    expect(within(drawer).getByText(/下次允许运行：/)).toBeTruthy()
    expect(within(drawer).getByText(/遇限流将等待，不使用替代密钥规避/)).toBeTruthy()
  })

  it('调整预算 → PATCH maxRunsPerHour', async () => {
    const drawer = await openDetailTab('抓取')
    fireEvent.click(within(drawer).getByText('每小时运行预算'))
    const select = await within(drawer).findByLabelText('每小时运行预算 Hacker News API')
    fireEvent.change(select, { target: { value: '12' } })
    await waitFor(() =>
      expect(mocks.updateApiSource).toHaveBeenCalledWith('src-1', { maxRunsPerHour: 12 }),
    )
  })
})

describe('N128 用样例预览（向导第 2 步）', () => {
  it('粘贴样例 → 结构下拉候选 → 预览调用 previewApiSourceSample 并渲染样例结果', async () => {
    mocks.listApiSources.mockResolvedValue({ items: [] })
    mocks.previewApiSourceSample.mockResolvedValue({
      items: [{ id: 7, title: 'v1.0' }],
      totalAvailable: 2,
      atomPreview: [
        {
          id: 'urn:lumirss:apisource:preview:abc',
          title: 'v1.0',
          link: 'https://example.com/r/7',
          published: '2026-09-01T00:00:00+00:00',
          updated: '2026-09-01T00:00:00+00:00',
          contentExcerpt: '',
        },
      ],
      sampleMode: true,
    })
    render(withProviders(<ApiSourcesSection />))
    fireEvent.click(await screen.findByRole('button', { name: /添加 API 来源/ }))
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '新来源' } })
    fireEvent.change(screen.getByLabelText('Endpoint'), {
      target: { value: 'https://api.example.com/items' },
    })
    fireEvent.click(screen.getByRole('button', { name: '下一步' }))
    fireEvent.change(screen.getByLabelText('items 表达式（JMESPath）'), {
      target: { value: '[*]' },
    })
    fireEvent.click(screen.getByRole('tab', { name: '用样例预览' }))
    const sampleJson = screen.getByLabelText('粘贴一段上游会返回的 JSON 样例')
    fireEvent.change(sampleJson, {
      target: {
        value: JSON.stringify([
          { id: 7, name: 'v1.0', html_url: 'https://example.com/r/7' },
        ]),
      },
    })
    // items 候选由样例结构生成（根数组 → [*]）
    const itemsSelect = screen.getByLabelText('items 表达式（由样例结构生成）')
    expect((itemsSelect as HTMLSelectElement).textContent).toContain('[*]')
    fireEvent.change(itemsSelect, { target: { value: '[*]' } })
    // 字段下拉候选来自样例真实键
    expect((screen.getByLabelText('id 字段（样例键）') as HTMLSelectElement).textContent).toContain(
      'id',
    )
    fireEvent.change(screen.getByLabelText('id 字段（样例键）'), { target: { value: 'id' } })
    fireEvent.change(screen.getByLabelText('title 字段（样例键）'), {
      target: { value: 'name' },
    })
    fireEvent.click(screen.getByRole('button', { name: /用样例预览/ }))
    await waitFor(() => expect(mocks.previewApiSourceSample).toHaveBeenCalled())
    expect(mocks.previewApiSourceSample).toHaveBeenCalledWith(
      {
        samplePayload: [{ id: 7, name: 'v1.0', html_url: 'https://example.com/r/7' }],
        itemsExpr: '[*]',
        fieldMap: { id: 'id', title: 'name' },
      },
      expect.anything(), // signal（可中止预览）
    )
    await waitFor(() => expect(screen.getByText(/样例模式（离线）/)).toBeTruthy())
  })
})

describe('N130 测试并轮换面板（详情抽屉 · 高级）', () => {
  it('轮换成功：脱敏 note 渲染，不回显凭据', async () => {
    const drawer = await openDetailTab('高级')
    mocks.rotateApiSourceCredential.mockResolvedValue({
      ok: true,
      statusClass: 'ok',
      latencyMs: 42,
      note: '已轮换。旧 Atom 地址保留 10 分钟，请尽快替换 FreshRSS 订阅。',
    })
    fireEvent.click(within(drawer).getByRole('button', { name: '测试并轮换凭据' }))
    const input = within(drawer).getByLabelText('新凭据（16–128 位字母/数字/连字符/下划线）')
    // write-only：掩码输入，不回显
    expect(input.getAttribute('type')).toBe('password')
    fireEvent.change(input, { target: { value: 'lumi-feed-9f8e7d6c5b4a3210' } })
    fireEvent.click(within(drawer).getByRole('button', { name: '测试并轮换' }))
    await waitFor(() =>
      expect(mocks.rotateApiSourceCredential).toHaveBeenCalledWith(
        'src-1',
        'lumi-feed-9f8e7d6c5b4a3210',
      ),
    )
    await waitFor(() =>
      expect(within(drawer).getByText(/已轮换。旧 Atom 地址保留 10 分钟/)).toBeTruthy(),
    )
    // 面板文本不包含凭据本身（脱敏）
    expect(within(drawer).queryByText('lumi-feed-9f8e7d6c5b4a3210')).toBeNull()
  })

  it('预演失败（422 credential_test_failed）：错误 message 原样透出', async () => {
    const drawer = await openDetailTab('高级')
    mocks.rotateApiSourceCredential.mockRejectedValue(
      new ApiError(422, 'credential_test_failed', '新凭据预演未通过（http_error），当前凭据未改动。'),
    )
    fireEvent.click(within(drawer).getByRole('button', { name: '测试并轮换凭据' }))
    fireEvent.change(
      within(drawer).getByLabelText('新凭据（16–128 位字母/数字/连字符/下划线）'),
      { target: { value: 'lumi-feed-9f8e7d6c5b4a3210' } },
    )
    fireEvent.click(within(drawer).getByRole('button', { name: '测试并轮换' }))
    await waitFor(() =>
      expect(within(drawer).getByText(/当前凭据未改动/)).toBeTruthy(),
    )
  })
})
