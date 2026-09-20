/** F107/F108/F109 —— W6 收件连接器 Web 层。
 *
 * F107：投递记录面板（事件列表 + failed 重放 + 重放失败诚实）；
 * F108：接入检查（JSON 编辑 → 零写入试跑 → 校验通过/错误/notes）；
 * F109：轮换凭据两步（武装确认 → 一次性 secret 展示 + 旧令牌失效文案）。
 * 统一 vi.mock('../api/client')，绝不触网。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { InboxItemList } from '../api/types'
import InboxPage from '../components/pages/InboxPage'

const mocks = vi.hoisted(() => ({
  listInboxItems: vi.fn(),
  listInboxSources: vi.fn(),
  createInboxSource: vi.fn(),
  deleteInboxSource: vi.fn(),
  deleteInboxItem: vi.fn(),
  resolveItems: vi.fn(),
  getFeeds: vi.fn(),
  listInboxEvents: vi.fn(),
  replayInboxEvent: vi.fn(),
  dryRunInboxIngest: vi.fn(),
  rotateInboxSource: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listInboxItems: mocks.listInboxItems,
    listInboxSources: mocks.listInboxSources,
    createInboxSource: mocks.createInboxSource,
    deleteInboxSource: mocks.deleteInboxSource,
    deleteInboxItem: mocks.deleteInboxItem,
    resolveItems: mocks.resolveItems,
    getFeeds: mocks.getFeeds,
    listInboxEvents: mocks.listInboxEvents,
    replayInboxEvent: mocks.replayInboxEvent,
    dryRunInboxIngest: mocks.dryRunInboxIngest,
    rotateInboxSource: mocks.rotateInboxSource,
  }
})

const SOURCE = { uuid: 'src-1', name: '我的脚本', enabled: true, createdAt: '2026-09-01T00:00:00Z', lastError: null, lastSuccessAt: null }

function renderWithProviders(ui: ReactNode): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getFeeds.mockResolvedValue([])
  mocks.listInboxSources.mockResolvedValue([SOURCE])
  const empty: InboxItemList = { items: [], nextCursor: null, hasMore: false }
  mocks.listInboxItems.mockResolvedValue(empty)
})

describe('F107 投递记录与失败重放', () => {
  it('F107: 事件列表按状态渲染；failed 行重放成功', async () => {
    mocks.listInboxEvents.mockResolvedValue({
      items: [
        { id: 7, sourceUuid: 'src-1', guid: 'g-ok', status: 'delivered', errorSummary: null, payloadHashPrefix: 'aabbccdd', createdAt: '2026-09-18T08:00:00Z' },
        { id: 9, sourceUuid: 'src-1', guid: 'g-bad', status: 'failed', errorSummary: 'invalid payload', payloadHashPrefix: '11223344', createdAt: '2026-09-18T09:00:00Z' },
      ],
    })
    mocks.replayInboxEvent.mockResolvedValue({ status: 'created', ref: 'library:9', replayedFrom: 9 })
    renderWithProviders(<InboxPage />)
    fireEvent.click(await screen.findByRole('button', { name: '投递记录 我的脚本' }))
    await waitFor(() => expect(document.querySelector('[data-inbox-event="9"]')).not.toBeNull())
    expect(document.querySelector('[data-inbox-event="7"]')?.textContent).toContain('已投递')
    expect(document.querySelector('[data-inbox-event="9"]')?.textContent).toContain('失败')
    fireEvent.click(screen.getByRole('button', { name: '重放 9' }))
    await waitFor(() => expect(mocks.replayInboxEvent).toHaveBeenCalledWith(9))
    await waitFor(() => expect(document.querySelector('[data-replay-ok]')?.textContent ?? '').toContain('已创建新条目'))
  })

  it('F107: 重放被拒（409 not_replayable）诚实透出', async () => {
    mocks.listInboxEvents.mockResolvedValue({
      items: [
        { id: 5, sourceUuid: 'src-1', guid: 'g-x', status: 'failed', errorSummary: null, payloadHashPrefix: 'ff', createdAt: '2026-09-18T07:00:00Z' },
      ],
    })
    mocks.replayInboxEvent.mockRejectedValue(new Error('该事件状态为 delivered，只有 failed 可重放。'))
    renderWithProviders(<InboxPage />)
    fireEvent.click(await screen.findByRole('button', { name: '投递记录 我的脚本' }))
    fireEvent.click(await screen.findByRole('button', { name: '重放 5' }))
    await waitFor(() => expect(document.querySelector('[data-replay-fail]')?.textContent ?? '').toContain('只有 failed 可重放'))
  })
})

describe('F108 接入检查（零写入试跑）', () => {
  it('F108: 合法载荷 → wouldCreate；未知字段进 notes', async () => {
    mocks.dryRunInboxIngest.mockResolvedValue({
      valid: true,
      errors: [],
      wouldCreate: { title: '示例标题', kind: 'api_item' },
      notes: ['未知字段（将被忽略）：foo'],
      wouldDuplicate: false,
    })
    renderWithProviders(<InboxPage />)
    fireEvent.click(await screen.findByRole('button', { name: '接入检查 我的脚本' }))
    fireEvent.click(await screen.findByRole('button', { name: '零写入试跑' }))
    await waitFor(() => expect(mocks.dryRunInboxIngest).toHaveBeenCalledWith('src-1', expect.stringContaining('guid')))
    await waitFor(() => expect(document.querySelector('[data-dryrun-valid]')?.textContent ?? '').toContain('示例标题'))
    expect(document.querySelector('[data-dryrun-notes]')?.textContent).toContain('foo')
  })

  it('F108: 非法载荷 → 逐字段错误诚实列出（零写入）', async () => {
    mocks.dryRunInboxIngest.mockResolvedValue({
      valid: false,
      errors: [{ field: 'title', reason: 'Field required' }],
      wouldCreate: null,
      notes: [],
    })
    renderWithProviders(<InboxPage />)
    fireEvent.click(await screen.findByRole('button', { name: '接入检查 我的脚本' }))
    fireEvent.click(await screen.findByRole('button', { name: '零写入试跑' }))
    await waitFor(() => expect(document.querySelector('[data-dryrun-invalid]')?.textContent ?? '').toContain('title'))
  })
})

describe('F109 轮换凭据', () => {
  it('F109: 武装确认 → 轮换 → 一次性 secret + 旧令牌失效文案', async () => {
    mocks.rotateInboxSource.mockResolvedValue({
      uuid: 'src-1',
      name: '我的脚本',
      secret: 'new-secret-value',
      ingestPath: '/api/v1/inbox/ingest/src-1',
      createdAt: '2026-09-01T00:00:00Z',
    })
    renderWithProviders(<InboxPage />)
    fireEvent.click(await screen.findByRole('button', { name: '轮换凭据 我的脚本' }))
    // 武装态：出现确认按钮；此时尚未调用
    fireEvent.click(await screen.findByRole('button', { name: '确认轮换' }))
    await waitFor(() => expect(mocks.rotateInboxSource).toHaveBeenCalledWith('src-1'))
    await waitFor(() => expect(document.querySelector('[data-rotate-once]')).not.toBeNull())
    const secretInput = screen.getByLabelText('新 Bearer Secret') as HTMLInputElement
    expect(secretInput.value).toBe('new-secret-value')
    expect(document.querySelector('[data-rotate-once]')?.textContent).toContain('旧令牌自下一请求起立即失效')
  })

  it('F109: 确认前可取消，不触发轮换', async () => {
    renderWithProviders(<InboxPage />)
    fireEvent.click(await screen.findByRole('button', { name: '轮换凭据 我的脚本' }))
    fireEvent.click(await screen.findByRole('button', { name: '取消' }))
    expect(mocks.rotateInboxSource).not.toHaveBeenCalled()
  })
})
