/** phase2 Gate 1 — Library 书签 + 工作区 Web UI 测试。
 *
 * - UnifiedContentCard：域徽标（RSS / 库）+ stale 诚实降级（「源已失效」
 *   且无任何链接）；
 * - BookmarksPage：列表行渲染 / 立即删除（行消失 + 正确 ref）/
 *   导入结果计数（role=status）；
 * - WorkspacesPage：保留工作区「稍后读」+「保留」标记、stale 内容提示、
 *   上移触发 PATCH 重排序（完整新顺序）、移除调用 DELETE；
 * - Sidebar / 折叠 Rail：书签 / 工作区 section 导航激活。
 *
 * 统一 vi.mock('../api/client')（保留其余真实导出），断言 BFF 契约调用。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { Bookmark, ResolvedItem, Workspace } from '../api/types'
import UnifiedContentCard from '../components/UnifiedContentCard'
import BookmarksPage from '../components/pages/BookmarksPage'
import WorkspacesPage from '../components/pages/WorkspacesPage'
import Sidebar from '../components/Sidebar'
import SidebarCollapsedRail from '../components/SidebarCollapsedRail'
import { useReaderUi } from '../store/reader-ui'

const mocks = vi.hoisted(() => ({
  listBookmarks: vi.fn(),
  deleteBookmark: vi.fn(),
  importBookmarks: vi.fn(),
  getFeeds: vi.fn(),
  listWorkspaces: vi.fn(),
  getWorkspaceContents: vi.fn(),
  reorderWorkspaceItems: vi.fn(),
  removeWorkspaceItem: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listBookmarks: mocks.listBookmarks,
    deleteBookmark: mocks.deleteBookmark,
    importBookmarks: mocks.importBookmarks,
    getFeeds: mocks.getFeeds,
    listWorkspaces: mocks.listWorkspaces,
    getWorkspaceContents: mocks.getWorkspaceContents,
    reorderWorkspaceItems: mocks.reorderWorkspaceItems,
    removeWorkspaceItem: mocks.removeWorkspaceItem,
  }
})

function bookmarkFixture(ref: string, over: Partial<Bookmark> = {}): Bookmark {
  return {
    ref,
    itemType: 'url',
    url: `https://example.com/${ref}`,
    rssItemRef: null,
    title: `书签 ${ref}`,
    note: '',
    createdAt: '2026-09-01T08:00:00Z',
    ...over,
  }
}

function resolvedItemFixture(over: Partial<ResolvedItem> = {}): ResolvedItem {
  return {
    ref: 'rss:e1.a',
    domain: 'rss',
    kind: 'rss',
    title: '文章 A',
    source: '示例源',
    datetime: '2026-09-01T08:00:00Z',
    excerpt: '这是摘要',
    url: 'https://example.com/a',
    stale: false,
    payload: {},
    ...over,
  }
}

function workspaceFixture(over: Partial<Workspace> = {}): Workspace {
  return {
    id: 'ws-1',
    name: '工作区',
    position: 0,
    itemCount: 0,
    reserved: false,
    ...over,
  }
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
  useReaderUi.setState({
    section: 'home',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
})

describe('UnifiedContentCard', () => {
  it('rss 条目：RSS 徽标 + data-domain=rss + 安全外链（target=_blank）', () => {
    render(<UnifiedContentCard item={resolvedItemFixture()} />)
    expect(screen.getByText('RSS')).toBeInTheDocument()
    expect(screen.getByRole('article')).toHaveAttribute('data-domain', 'rss')
    const link = screen.getByRole('link', { name: 'https://example.com/a' })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer noopener')
  })

  it('bookmark 条目：库徽标 + data-domain=library', () => {
    render(
      <UnifiedContentCard
        item={resolvedItemFixture({ ref: 'library:u1', domain: 'library', kind: 'bookmark' })}
      />,
    )
    expect(screen.getByText('库')).toBeInTheDocument()
    expect(screen.getByRole('article')).toHaveAttribute('data-domain', 'library')
  })

  it('stale：显示「源已失效」且不渲染任何链接（不伪造可打开内容）', () => {
    render(<UnifiedContentCard item={resolvedItemFixture({ stale: true })} />)
    expect(screen.getByText('源已失效')).toBeInTheDocument()
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.queryByText('RSS')).toBeNull()
  })
})

describe('BookmarksPage', () => {
  it('列表渲染：url 型标题为外链；rss 型标题为纯文本', async () => {
    mocks.listBookmarks.mockResolvedValue({
      items: [
        bookmarkFixture('library:b1'),
        bookmarkFixture('library:b2', { itemType: 'rss', url: null, rssItemRef: 'rss:e1.x' }),
      ],
      nextCursor: null,
    })
    render(withProviders(<BookmarksPage />))
    const link = await screen.findByRole('link', { name: '书签 library:b1' })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer noopener')
    expect(screen.getByText('书签 library:b2')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '书签 library:b2' })).toBeNull()
  })

  it('删除：点击「删除书签」立即删除（无二次确认），行消失', async () => {
    mocks.listBookmarks
      .mockResolvedValueOnce({
        items: [bookmarkFixture('library:b1'), bookmarkFixture('library:b2')],
        nextCursor: null,
      })
      .mockResolvedValue({ items: [bookmarkFixture('library:b1')], nextCursor: null })
    mocks.deleteBookmark.mockResolvedValue(undefined)
    render(withProviders(<BookmarksPage />))
    await screen.findByText('书签 library:b2')
    fireEvent.click(screen.getAllByRole('button', { name: '删除书签' })[1])
    await waitFor(() => expect(screen.queryByText('书签 library:b2')).toBeNull())
    expect(mocks.deleteBookmark).toHaveBeenCalledWith('library:b2')
  })

  it('导入：上传 .html 后显示成功/跳过/失败计数与失败原因（role=status）', async () => {
    mocks.listBookmarks.mockResolvedValue({ items: [], nextCursor: null })
    mocks.importBookmarks.mockResolvedValue({
      imported: 3,
      skipped: 1,
      failed: [{ index: 2, url: 'https://bad.example', reason: 'invalid_url' }],
    })
    render(withProviders(<BookmarksPage />))
    const input = screen.getByLabelText('导入书签文件')
    fireEvent.change(input, {
      target: { files: [new File(['<DL><p>'], 'bookmarks.html', { type: 'text/html' })] },
    })
    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('成功 3 条')
    expect(status).toHaveTextContent('跳过 1 条')
    expect(status).toHaveTextContent('失败 1 条')
    expect(status).toHaveTextContent('invalid_url')
    expect(mocks.importBookmarks).toHaveBeenCalledTimes(1)
  })

  it('空态与错误态：请求失败显示错误 + 重试；重试成功后显示空态文案', async () => {
    mocks.listBookmarks.mockRejectedValueOnce(new Error('boom'))
    render(withProviders(<BookmarksPage />))
    expect(await screen.findByText('书签加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
    mocks.listBookmarks.mockResolvedValue({ items: [], nextCursor: null })
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('无书签')).toBeInTheDocument()
  })
})

describe('WorkspacesPage', () => {
  const READ_LATER = workspaceFixture({
    id: 'read-later',
    name: '稍后读',
    reserved: true,
    position: 0,
  })
  const WEEKLY = workspaceFixture({ id: 'ws-2', name: '周报', position: 1, itemCount: 2 })

  it('保留工作区显示「稍后读」+「保留」标记；stale 内容显示「源已失效」且无链接', async () => {
    mocks.listWorkspaces.mockResolvedValue({ items: [READ_LATER, WEEKLY] })
    mocks.getWorkspaceContents.mockResolvedValue({
      items: [resolvedItemFixture({ stale: true })],
    })
    render(withProviders(<WorkspacesPage />))
    expect(await screen.findByText('稍后读')).toBeInTheDocument()
    expect(screen.getByText('保留')).toBeInTheDocument()
    // 默认选中第一个工作区（read-later）→ contents 加载后 stale 卡片
    expect(await screen.findByText('源已失效')).toBeInTheDocument()
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('源已失效，无法打开原文，建议移除。')).toBeInTheDocument()
  })

  it('上移触发 PATCH 重排序（完整新顺序）；移除调用 DELETE', async () => {
    mocks.listWorkspaces.mockResolvedValue({ items: [READ_LATER, WEEKLY] })
    mocks.getWorkspaceContents.mockImplementation(async (workspaceId: string) =>
      workspaceId === 'ws-2'
        ? {
            items: [
              resolvedItemFixture(),
              resolvedItemFixture({
                ref: 'rss:e2.b',
                title: '文章 B',
                domain: 'library',
                kind: 'bookmark',
              }),
            ],
          }
        : { items: [] },
    )
    mocks.reorderWorkspaceItems.mockResolvedValue({ items: [] })
    mocks.removeWorkspaceItem.mockResolvedValue(undefined)
    render(withProviders(<WorkspacesPage />))
    // 切到「周报」工作区（默认选中的是 read-later）
    fireEvent.click(await screen.findByRole('button', { name: /周报/ }))
    expect(await screen.findByText('文章 B')).toBeInTheDocument()
    // 第二张卡「上移」→ 新顺序 [B, A]
    const moveUps = screen.getAllByRole('button', { name: '上移' })
    expect(moveUps[0]).toBeDisabled() // 首卡无上移
    fireEvent.click(moveUps[1])
    await waitFor(() =>
      expect(mocks.reorderWorkspaceItems).toHaveBeenCalledWith('ws-2', [
        'rss:e2.b',
        'rss:e1.a',
      ]),
    )
    // 移除第一张卡
    fireEvent.click(screen.getAllByRole('button', { name: '移除' })[0])
    await waitFor(() =>
      expect(mocks.removeWorkspaceItem).toHaveBeenCalledWith('ws-2', 'rss:e1.a'),
    )
  })
})

describe('Sidebar / 折叠 Rail：书签与工作区导航（phase2 M1）', () => {
  it('展开侧栏：点击「书签」→ section=bookmarks；点击「工作区」→ section=workspaces', () => {
    mocks.getFeeds.mockResolvedValue([])
    render(withProviders(<Sidebar />))
    fireEvent.click(screen.getByRole('button', { name: '书签' }))
    expect(useReaderUi.getState().section).toBe('bookmarks')
    fireEvent.click(screen.getByRole('button', { name: '工作区' }))
    expect(useReaderUi.getState().section).toBe('workspaces')
  })

  it('折叠 Rail：书签 RailItem 已激活可点击', () => {
    render(<SidebarCollapsedRail />)
    const bookmark = screen.getByRole('button', { name: '书签' })
    expect(bookmark).not.toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(bookmark)
    expect(useReaderUi.getState().section).toBe('bookmarks')
  })
})
