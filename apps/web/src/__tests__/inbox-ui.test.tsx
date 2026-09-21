/** 0021 — Inbox 推送来源 Web UI 测试。
 *
 * - InboxPage：加载 Skeleton / 空态 / 错误重试 / 经 /resolve 的统一卡片
 *   （收件徽标 + stale 提示）/ 行内删除调用 DELETE /inbox/items/{uuid}；
 * - 连接器创建 Dialog：secret 仅创建成功后展示一次（含摄取路径）；
 * - open-item：api_item 打开 = 安全外链（http/https 放行，js: 拒绝）；
 * - Sidebar / 折叠 Rail：收件箱 section 导航激活。
 *
 * 统一 vi.mock('../api/client')（保留其余真实导出），断言 BFF 契约调用。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { InboxItemList, ResolvedItem } from '../api/types'
import InboxPage from '../components/pages/InboxPage'
import Sidebar from '../components/Sidebar'
import SidebarCollapsedRail from '../components/SidebarCollapsedRail'
import { isOpenable, openResolvedItem } from '../lib/open-item'
import { useReaderUi } from '../store/reader-ui'

const mocks = vi.hoisted(() => ({
  listInboxItems: vi.fn(),
  listInboxSources: vi.fn(),
  createInboxSource: vi.fn(),
  deleteInboxSource: vi.fn(),
  deleteInboxItem: vi.fn(),
  resolveItems: vi.fn(),
  getFeeds: vi.fn(),
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
  }
})

function page(ref: string): InboxItemList['items'][number] {
  return { ref, createdAt: '2026-09-13T08:00:00Z', sourceUuid: 'src-1' }
}

function resolvedApiItem(ref: string, over: Partial<ResolvedItem> = {}): ResolvedItem {
  return {
    ref,
    domain: 'library',
    kind: 'api_item',
    title: '推送的文章',
    source: 'Inbox · scripts',
    datetime: '2026-09-13T08:00:00Z',
    excerpt: '正文摘要',
    url: 'https://example.com/pushed',
    stale: false,
    payload: { inboxUuid: ref.replace('library:', ''), url: 'https://example.com/pushed' },
    ...over,
  }
}

function renderWithProviders(ui: ReactNode): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

function emptyList(): InboxItemList {
  return { items: [], nextCursor: null, hasMore: false }
}

beforeEach(() => {
  vi.clearAllMocks()
  useReaderUi.getState().selectSection('home')
  mocks.getFeeds.mockResolvedValue([])
  mocks.listInboxSources.mockResolvedValue([])
})

describe('InboxPage states', () => {
  it('renders the empty state when there are no items and no connectors', async () => {
    mocks.listInboxItems.mockResolvedValue(emptyList())
    renderWithProviders(<InboxPage />)
    expect(await screen.findByText('收件箱为空')).toBeTruthy()
  })

  it('renders error state with retry and refetches on click', async () => {
    mocks.listInboxItems.mockRejectedValue(new Error('网络错误'))
    renderWithProviders(<InboxPage />)
    // 页面同时可能有多个 alert（连接器错误 + 归类规则面板错误——后者
    // 随 lazy chunk 就绪时序出现）：断言「存在错误提示」而非唯一性。
    expect((await screen.findAllByRole('alert')).length).toBeGreaterThan(0)
    const retry = await screen.findByRole('button', { name: '重试' })
    mocks.listInboxItems.mockResolvedValue(emptyList())
    fireEvent.click(retry)
    await waitFor(() => expect(screen.getByText('收件箱为空')).toBeTruthy())
  })

  it('renders resolved cards with the inbox badge and stale hint', async () => {
    mocks.listInboxItems.mockResolvedValue({
      items: [page('library:u1'), page('library:u2')],
      nextCursor: null,
      hasMore: false,
    })
    mocks.resolveItems.mockResolvedValue({
      items: [
        resolvedApiItem('library:u1'),
        resolvedApiItem('library:u2', { stale: true, title: '失效条目' }),
      ],
    })
    renderWithProviders(<InboxPage />)
    expect(await screen.findByText('推送的文章')).toBeTruthy()
    expect(screen.getByText('收件')).toBeTruthy()
    expect(screen.getByText('失效条目')).toBeTruthy()
    expect(screen.getByText('该条目已失效，建议移除。')).toBeTruthy()
  })

  it('deletes an item through the BFF contract ref', async () => {
    mocks.listInboxItems.mockResolvedValue({
      items: [page('library:u1')],
      nextCursor: null,
      hasMore: false,
    })
    mocks.resolveItems.mockResolvedValue({ items: [resolvedApiItem('library:u1')] })
    mocks.deleteInboxItem.mockResolvedValue(undefined)
    renderWithProviders(<InboxPage />)
    expect(await screen.findByText('推送的文章')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '删除收件条目' }))
    await waitFor(() =>
      expect(mocks.deleteInboxItem).toHaveBeenCalledWith('library:u1'),
    )
  })

  it('shows the one-time secret after creating a connector', async () => {
    mocks.listInboxItems.mockResolvedValue(emptyList())
    mocks.createInboxSource.mockResolvedValue({
      uuid: 'src-9',
      name: '我的脚本',
      secret: 'one-time-secret-abc',
      ingestPath: '/api/v1/inbox/ingest/src-9',
      createdAt: '2026-09-13T08:00:00Z',
    })
    renderWithProviders(<InboxPage />)
    fireEvent.click(await screen.findByRole('button', { name: '新建连接器' }))
    const nameInput = await screen.findByLabelText('连接器名称')
    fireEvent.change(nameInput, { target: { value: '我的脚本' } })
    fireEvent.click(screen.getByRole('button', { name: '创建' }))
    expect(
      await screen.findByText(/仅显示这一次/),
    ).toBeTruthy()
    const secretField = screen.getByLabelText('Bearer Secret') as HTMLInputElement
    expect(secretField.value).toBe('one-time-secret-abc')
    expect(mocks.createInboxSource).toHaveBeenCalledWith('我的脚本')
  })
})

describe('open-item api_item routing', () => {
  it('opens safe external url for api_item cards', () => {
    const item = resolvedApiItem('library:u1')
    expect(isOpenable(item)).toBe(true)
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    expect(openResolvedItem(item)).toBe(true)
    expect(openSpy).toHaveBeenCalledWith(
      'https://example.com/pushed',
      '_blank',
      'noopener,noreferrer',
    )
    openSpy.mockRestore()
  })

  it('refuses to open api_item without a safe url', () => {
    const item = resolvedApiItem('library:u1', {
      url: null,
      payload: { inboxUuid: 'u1', url: null },
    })
    expect(isOpenable(item)).toBe(false)
    expect(openResolvedItem(item)).toBe(false)
  })
})

describe('inbox navigation', () => {
  it('sidebar nav switches to the inbox section', () => {
    renderWithProviders(<Sidebar />)
    const nav = screen.getByRole('button', { name: /收件箱/ })
    fireEvent.click(nav)
    expect(useReaderUi.getState().section).toBe('inbox')
  })

  it('collapsed rail exposes the inbox section', () => {
    renderWithProviders(<SidebarCollapsedRail />)
    const rail = screen.getByRole('button', { name: '收件箱' })
    fireEvent.click(rail)
    expect(useReaderUi.getState().section).toBe('inbox')
  })
})
