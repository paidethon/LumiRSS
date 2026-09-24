/** N128/N129/N130 — Web UI 测试（API 来源：样例预览 Tab / 预算块 / 轮换面板）。
 *
 * - N129：列表行的预算块渲染（每小时运行预算 + 下次允许运行时间 +
 *   「遇限流将等待，不使用替代密钥规避」文案）；
 * - N128：新增对话框的「用样例预览」Tab —— 粘贴 JSON → 结构候选下拉 →
 *   预览调用 previewApiSourceSample 且渲染 sampleMode 结果；
 * - N130：轮换面板 —— 预演结果（脱敏）与轮换成功 note 渲染。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

beforeEach(() => {
  vi.clearAllMocks()
  mocks.updateApiSource.mockResolvedValue(apiSourceFixture())
})

describe('N129 限额友好预算块', () => {
  it('渲染每小时运行预算 + 下次允许运行 + 限流等待文案', async () => {
    mocks.listApiSources.mockResolvedValue({
      items: [
        apiSourceFixture({
          nextAllowedRun: '2026-09-24T12:00:00Z',
        }),
      ],
    })
    render(withProviders(<ApiSourcesSection />))
    await waitFor(() => expect(screen.getByText('Hacker News API')).toBeTruthy())
    expect(screen.getByLabelText('每小时运行预算 Hacker News API')).toBeTruthy()
    expect(screen.getByText(/下次允许运行：/)).toBeTruthy()
    expect(screen.getByText(/遇限流将等待，不使用替代密钥规避/)).toBeTruthy()
  })

  it('调整预算 → PATCH maxRunsPerHour', async () => {
    mocks.listApiSources.mockResolvedValue({ items: [apiSourceFixture()] })
    render(withProviders(<ApiSourcesSection />))
    await waitFor(() => expect(screen.getByText('Hacker News API')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('每小时运行预算 Hacker News API'), {
      target: { value: '12' },
    })
    await waitFor(() =>
      expect(mocks.updateApiSource).toHaveBeenCalledWith('src-1', { maxRunsPerHour: 12 }),
    )
  })
})

describe('N128 用样例预览 Tab', () => {
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
    fireEvent.click(screen.getByRole('button', { name: /新增来源/ }))
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
    expect(mocks.previewApiSourceSample).toHaveBeenCalledWith({
      samplePayload: [{ id: 7, name: 'v1.0', html_url: 'https://example.com/r/7' }],
      itemsExpr: '[*]',
      fieldMap: { id: 'id', title: 'name' },
    })
    await waitFor(() => expect(screen.getByText(/样例模式（离线）/)).toBeTruthy())
  })
})

describe('N130 测试并轮换面板', () => {
  it('轮换成功：脱敏 note 渲染，不回显凭据', async () => {
    mocks.listApiSources.mockResolvedValue({ items: [apiSourceFixture()] })
    mocks.rotateApiSourceCredential.mockResolvedValue({
      ok: true,
      statusClass: 'ok',
      latencyMs: 42,
      note: '已轮换。旧 Atom 地址保留 10 分钟，请尽快替换 FreshRSS 订阅。',
    })
    render(withProviders(<ApiSourcesSection />))
    await waitFor(() => expect(screen.getByText('Hacker News API')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '测试并轮换凭据 Hacker News API' }))
    const input = screen.getByLabelText('新凭据（16–128 位字母/数字/连字符/下划线）')
    fireEvent.change(input, { target: { value: 'lumi-feed-9f8e7d6c5b4a3210' } })
    fireEvent.click(screen.getByRole('button', { name: '测试并轮换' }))
    await waitFor(() =>
      expect(mocks.rotateApiSourceCredential).toHaveBeenCalledWith(
        'src-1',
        'lumi-feed-9f8e7d6c5b4a3210',
      ),
    )
    await waitFor(() => expect(screen.getByText(/已轮换。旧 Atom 地址保留 10 分钟/)).toBeTruthy())
    // 面板文本不包含凭据本身（脱敏）
    expect(screen.queryByText('lumi-feed-9f8e7d6c5b4a3210')).toBeNull()
  })

  it('预演失败（422 credential_test_failed）：错误 message 原样透出', async () => {
    mocks.listApiSources.mockResolvedValue({ items: [apiSourceFixture()] })
    mocks.rotateApiSourceCredential.mockRejectedValue(
      new ApiError(422, 'credential_test_failed', '新凭据预演未通过（http_error），当前凭据未改动。'),
    )
    render(withProviders(<ApiSourcesSection />))
    await waitFor(() => expect(screen.getByText('Hacker News API')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '测试并轮换凭据 Hacker News API' }))
    fireEvent.change(screen.getByLabelText('新凭据（16–128 位字母/数字/连字符/下划线）'), {
      target: { value: 'lumi-feed-9f8e7d6c5b4a3210' },
    })
    fireEvent.click(screen.getByRole('button', { name: '测试并轮换' }))
    await waitFor(() => expect(screen.getByText(/当前凭据未改动/)).toBeTruthy())
  })
})
