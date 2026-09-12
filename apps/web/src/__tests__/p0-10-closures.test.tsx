/** P0-10 wave 1 — tags / favorites / workspace UI 闭环测试。
 *
 * 均为已有 BFF 契约的首批 UI 消费者（vi.mock('../api/client')，保留
 * ApiError 等真实导出）：
 * - 工作区：重命名（PATCH）/ 删除（DELETE 双重确认）；保留工作区
 *   read-later 不提供这两个入口（BFF 亦拒绝，双层防线）；
 * - 条目标签：EntryActionButtons 的标签 Popover → 勾选/取消 →
 *   assignTag/unassignTag；新建输入 → assignTag；
 * - 库收藏：UnifiedContentCard 库类条目收藏切换 → add/
 *   removeLibraryFavorite（乐观移除）；FavoritesPage LibraryRow
 *   取消收藏 → 行乐观消失。RSS star 行为不在本文件（g6-ui 覆盖）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import FavoritesPage from '../components/pages/FavoritesPage'
import WorkspacesPage from '../components/pages/WorkspacesPage'
import UnifiedContentCard from '../components/UnifiedContentCard'
import { EntryActionButtons } from '../components/EntryActionButtons'
import { useReaderUi } from '../store/reader-ui'
import type { ResolvedItem, Workspace, WorkspaceItemsResolvedResponse } from '../api/types'
import type { LibrarySearchItem, TagListResponse } from '../api/client'

const mocks = vi.hoisted(() => ({
  listWorkspaces: vi.fn(),
  getWorkspaceContents: vi.fn(),
  renameWorkspace: vi.fn(),
  deleteWorkspace: vi.fn(),
  listTags: vi.fn(),
  listTagsForItem: vi.fn(),
  assignTag: vi.fn(),
  unassignTag: vi.fn(),
  getFavorites: vi.fn(),
  getEntries: vi.fn(),
  addLibraryFavorite: vi.fn(),
  removeLibraryFavorite: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listWorkspaces: mocks.listWorkspaces,
    getWorkspaceContents: mocks.getWorkspaceContents,
    renameWorkspace: mocks.renameWorkspace,
    deleteWorkspace: mocks.deleteWorkspace,
    listTags: mocks.listTags,
    listTagsForItem: mocks.listTagsForItem,
    assignTag: mocks.assignTag,
    unassignTag: mocks.unassignTag,
    getFavorites: mocks.getFavorites,
    getEntries: mocks.getEntries,
    addLibraryFavorite: mocks.addLibraryFavorite,
    removeLibraryFavorite: mocks.removeLibraryFavorite,
  }
})

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
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

const READ_LATER = workspaceFixture({ id: 'read-later', name: '稍后读', reserved: true, position: 0 })
const WEEKLY = workspaceFixture({ id: 'ws-2', name: '周报', position: 1, itemCount: 2 })

function emptyContents(): WorkspaceItemsResolvedResponse {
  return { items: [] }
}

function tagListFixture(): TagListResponse {
  return {
    items: [
      { id: 1, name: 'rss', count: 2 },
      { id: 2, name: '前端', count: 1 },
    ],
  }
}

function itemTagsFixture() {
  return {
    items: [
      { tagId: 1, name: 'rss', origin: 'manual', status: 'attached' },
      { tagId: 3, name: '待读', origin: 'ai', status: 'suggested' },
    ],
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

function libraryItemFixture(over: Partial<LibrarySearchItem> = {}): LibrarySearchItem {
  return {
    ref: 'library:n1',
    kind: 'obsidian_note',
    title: '读书笔记',
    url: null,
    snippet: '',
    updatedAt: '2026-09-01T08:00:00Z',
    ...over,
  }
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
  mocks.renameWorkspace.mockResolvedValue(WEEKLY)
  mocks.deleteWorkspace.mockResolvedValue(undefined)
  mocks.assignTag.mockResolvedValue({})
  mocks.unassignTag.mockResolvedValue(undefined)
  mocks.addLibraryFavorite.mockResolvedValue(undefined)
  mocks.removeLibraryFavorite.mockResolvedValue(undefined)
  mocks.listTags.mockResolvedValue(tagListFixture())
  mocks.listTagsForItem.mockResolvedValue(itemTagsFixture())
  // FavoritesPage 的 RSS star 腿（空页 = 无 RSS 收藏；只测库收藏腿）
  mocks.getEntries.mockResolvedValue({ items: [], nextCursor: null })
})

// ---- 工作区：重命名 / 删除 ----

describe('WorkspacesPage 重命名/删除（P0-10）', () => {
  it('保留工作区（read-later）不提供重命名/删除操作入口', async () => {
    mocks.listWorkspaces.mockResolvedValue({ items: [READ_LATER, WEEKLY] })
    mocks.getWorkspaceContents.mockResolvedValue(emptyContents())
    render(withProviders(<WorkspacesPage />))
    // 默认选中 read-later：无「操作」菜单按钮
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '新建工作区' })).toBeEnabled()
    })
    expect(screen.queryByRole('button', { name: /操作/ })).toBeNull()
  })

  it('重命名非保留工作区：菜单 → 重命名 → PATCH（新名字）', async () => {
    mocks.listWorkspaces.mockResolvedValue({ items: [READ_LATER, WEEKLY] })
    mocks.getWorkspaceContents.mockResolvedValue(emptyContents())
    render(withProviders(<WorkspacesPage />))
    // 切到「周报」
    fireEvent.click(await screen.findByRole('button', { name: /周报/ }))
    fireEvent.click(await screen.findByRole('button', { name: '「周报」操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: /重命名/ }))
    const dialogInput = await screen.findByLabelText('工作区名称')
    expect(dialogInput).toHaveValue('周报')
    fireEvent.change(dialogInput, { target: { value: '周报整理' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(mocks.renameWorkspace).toHaveBeenCalledWith('ws-2', '周报整理')
    })
  })

  it('删除非保留工作区：菜单 → 删除 → 双重确认 → DELETE', async () => {
    mocks.listWorkspaces.mockResolvedValue({ items: [READ_LATER, WEEKLY] })
    mocks.getWorkspaceContents.mockResolvedValue(emptyContents())
    render(withProviders(<WorkspacesPage />))
    fireEvent.click(await screen.findByRole('button', { name: /周报/ }))
    fireEvent.click(await screen.findByRole('button', { name: '「周报」操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: /删除工作区/ }))
    // 第一层确认（未到 final 时不发 DELETE）
    fireEvent.click(screen.getByRole('button', { name: '删除工作区' }))
    expect(mocks.deleteWorkspace).not.toHaveBeenCalled()
    // 第二层：红色最终确认
    fireEvent.click(screen.getByRole('button', { name: /确认删除/ }))
    await waitFor(() => {
      expect(mocks.deleteWorkspace).toHaveBeenCalledWith('ws-2')
    })
  })
})

// ---- 条目标签：EntryActionButtons 的标签 Popover ----

describe('EntryActionButtons 标签面板（P0-10）', () => {
  function renderActions() {
    return render(
      withProviders(
        <EntryActionButtons entryRef="e1.a" starred={false} title="文章 A" />,
      ),
    )
  }

  it('打开标签面板：既有标签勾选态来自 item tags；suggested 行标注「建议」', async () => {
    renderActions()
    fireEvent.click(screen.getByRole('button', { name: '标签' }))
    // attached 勾选
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: '标签 rss' })).toBeChecked()
    })
    // 全量列表里的另一个标签未勾选
    expect(screen.getByRole('checkbox', { name: '标签 前端' })).not.toBeChecked()
    // suggested（不在全量列表）出现并标注「建议」
    expect(screen.getByRole('checkbox', { name: '标签 待读' })).not.toBeChecked()
    expect(screen.getByText('建议')).toBeInTheDocument()
  })

  it('勾选未绑定标签 → assignTag(itemRef=rss:e1.a, name)；取消勾选 → unassignTag', async () => {
    renderActions()
    fireEvent.click(screen.getByRole('button', { name: '标签' }))
    const checkbox = await screen.findByRole('checkbox', { name: '标签 前端' })
    fireEvent.click(checkbox)
    await waitFor(() => {
      expect(mocks.assignTag).toHaveBeenCalledWith({ itemRef: 'rss:e1.a', name: '前端', origin: 'manual' })
    })
    fireEvent.click(screen.getByRole('checkbox', { name: '标签 rss' }))
    await waitFor(() => {
      expect(mocks.unassignTag).toHaveBeenCalledWith({ itemRef: 'rss:e1.a', name: 'rss', origin: 'manual' })
    })
  })

  it('新建标签输入 → assignTag（upsert 语义）；空输入不提交', async () => {
    renderActions()
    fireEvent.click(screen.getByRole('button', { name: '标签' }))
    const input = await screen.findByLabelText('新建标签')
    // 空输入：提交按钮禁用
    expect(screen.getByRole('button', { name: '添加标签' })).toBeDisabled()
    fireEvent.change(input, { target: { value: '新标签' } })
    fireEvent.click(screen.getByRole('button', { name: '添加标签' }))
    await waitFor(() => {
      expect(mocks.assignTag).toHaveBeenCalledWith({ itemRef: 'rss:e1.a', name: '新标签', origin: 'manual' })
    })
  })
})

// ---- 库收藏：UnifiedContentCard + FavoritesPage ----

describe('库收藏切换（P0-10）', () => {
  it('UnifiedContentCard：库类条目收藏切换 → addLibraryFavorite(ref)；RSS 条目无收藏切换', async () => {
    mocks.getFavorites.mockResolvedValue({ library: [], rss: [] })
    const screen1 = render(
      withProviders(
        <UnifiedContentCard
          item={resolvedItemFixture({ ref: 'library:c1', domain: 'library', kind: 'clip' })}
        />,
      ),
    )
    const button = await screen.findByRole('button', { name: '加入收藏' })
    fireEvent.click(button)
    await waitFor(() => {
      expect(mocks.addLibraryFavorite).toHaveBeenCalledWith('library:c1')
    })
    screen1.unmount()

    // RSS 条目不渲染收藏切换（收藏语义归 RSS star，不跨域复制）
    mocks.getFavorites.mockResolvedValue({ library: [], rss: [] })
    const screen2 = render(withProviders(<UnifiedContentCard item={resolvedItemFixture()} />))
    await screen2.findByText('RSS')
    expect(screen2.queryByRole('button', { name: '加入收藏' })).toBeNull()
    screen2.unmount()
  })

  it('FavoritesPage LibraryRow：取消收藏 → removeLibraryFavorite + 行乐观消失', async () => {
    // 首次 GET 返回两条；删除后的重取（onSettled invalidate）只返回剩余一条
    // ——乐观移除与服务端真值一致，行不会在重取后闪回。
    const remaining = [libraryItemFixture({ ref: 'library:n2', title: '第二笔记' })]
    mocks.getFavorites
      .mockResolvedValueOnce({
        library: [libraryItemFixture(), libraryItemFixture({ ref: 'library:n2', title: '第二笔记' })],
        rss: [],
      })
      .mockImplementation(async () => ({ library: remaining, rss: [] }))
    render(withProviders(<FavoritesPage />))
    expect(await screen.findByText('读书笔记')).toBeInTheDocument()
    expect(screen.getByText('第二笔记')).toBeInTheDocument()
    // 取消第一条收藏
    const buttons = screen.getAllByRole('button', { name: '取消收藏' })
    fireEvent.click(buttons[0])
    await waitFor(() => {
      expect(mocks.removeLibraryFavorite).toHaveBeenCalledWith('library:n1')
    })
    // 乐观移除：行立即消失（不等 invalidate）；重取后仍不出现（真值一致）
    await waitFor(() => {
      expect(screen.queryByText('读书笔记')).toBeNull()
    })
    expect(screen.getByText('第二笔记')).toBeInTheDocument()
    // onSettled invalidate 触发了重取（≥2 次：初始 + 失效重取）
    expect(mocks.getFavorites.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('UnifiedContentCard：收藏操作失败 → 诚实错误提示（不假装成功）', async () => {
    mocks.getFavorites.mockResolvedValue({ library: [], rss: [] })
    mocks.addLibraryFavorite.mockRejectedValue(new Error('库不可用'))
    const screen1 = render(
      withProviders(
        <UnifiedContentCard
          item={resolvedItemFixture({ ref: 'library:c9', domain: 'library', kind: 'snapshot' })}
        />,
      ),
    )
    fireEvent.click(await screen.findByRole('button', { name: '加入收藏' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/收藏操作失败/)
    })
    screen1.unmount()
  })
})
