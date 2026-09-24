/** N101/N102/N103/N104/N105 — 工作区标签页/分组/固定/预览/快照 UI 闭环。
 *
 * vi.mock('../api/client')（保留 ApiError 等真实导出，p0-10 模式）：
 * - N101 分组：分组视图渲染为可折叠分组区（未分组 = 隐式前置组、命名组
 *   按 groupOrder 序）；折叠状态写本机 localStorage；「移动到分组…」
 *   菜单 → Dialog → PATCH group；
 * - N102 固定：菜单 固定（set 语义）；移除固定条目 409
 *   workspace_item_pinned → 行内诚实提示 + 强制移除（force）；
 * - N103 预览：预览按钮打开页内窗格；连续打开 = 替换不叠加；
 *   「添加到工作区」只对非成员出现（幂等提升）；未保存笔记草稿拦截
 *   替换（诚实提示 + 保存/放弃出口）；
 * - N104 最近关闭：关闭的预览进入本机 LRU（20），恢复 = 重新打开预览；
 * - N105 快照：保存（名称）/ 恢复（模式选择 + diff 摘要 + 固定冲突
 *   诚实重试）/ 删除（二次确认）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import WorkspacesPage from '../components/pages/WorkspacesPage'
import { ApiError } from '../api/client'
import {
  loadCollapsedGroups,
  pushRecentlyClosed,
  RECENTLY_CLOSED_CAP,
} from '../lib/workspace-tabs'
import { useReaderUi } from '../store/reader-ui'
import type { RecentClosedItem } from '../lib/workspace-tabs'
import type {
  ResolvedItem,
  Workspace,
  WorkspaceGroupsResponse,
  WorkspaceItemsResolvedResponse,
  WorkspaceResumeResponse,
  WorkspaceSnapshotList,
} from '../api/types'

// 本页查询面较宽（contents + groups + snapshots），默认 1s 超时偏紧。
configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 20000 })

const mocks = vi.hoisted(() => ({
  listWorkspaces: vi.fn(),
  getWorkspaceContents: vi.fn(),
  getWorkspaceResume: vi.fn(),
  getWorkspaceGroups: vi.fn(),
  putWorkspaceResume: vi.fn(),
  reorderWorkspaceItems: vi.fn(),
  removeWorkspaceItem: vi.fn(),
  setWorkspaceItemPinned: vi.fn(),
  moveWorkspaceItemGroup: vi.fn(),
  addWorkspaceItem: vi.fn(),
  listWorkspaceSnapshots: vi.fn(),
  captureWorkspaceSnapshot: vi.fn(),
  deleteWorkspaceSnapshot: vi.fn(),
  restoreWorkspaceSnapshot: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listWorkspaces: mocks.listWorkspaces,
    getWorkspaceContents: mocks.getWorkspaceContents,
    getWorkspaceResume: mocks.getWorkspaceResume,
    getWorkspaceGroups: mocks.getWorkspaceGroups,
    putWorkspaceResume: mocks.putWorkspaceResume,
    reorderWorkspaceItems: mocks.reorderWorkspaceItems,
    removeWorkspaceItem: mocks.removeWorkspaceItem,
    setWorkspaceItemPinned: mocks.setWorkspaceItemPinned,
    moveWorkspaceItemGroup: mocks.moveWorkspaceItemGroup,
    addWorkspaceItem: mocks.addWorkspaceItem,
    listWorkspaceSnapshots: mocks.listWorkspaceSnapshots,
    captureWorkspaceSnapshot: mocks.captureWorkspaceSnapshot,
    deleteWorkspaceSnapshot: mocks.deleteWorkspaceSnapshot,
    restoreWorkspaceSnapshot: mocks.restoreWorkspaceSnapshot,
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
    name: '研究',
    position: 0,
    itemCount: 2,
    archived: false,
    reserved: false,
    description: '',
    revision: 1,
    ...over,
  }
}

function itemFixture(ref: string, title: string): ResolvedItem {
  return {
    ref,
    domain: 'rss',
    kind: 'rss',
    title,
    source: '示例源',
    datetime: '2026-09-01T08:00:00Z',
    excerpt: '这是摘要',
    url: `https://example.com/${title}`,
    stale: false,
    payload: {},
  }
}

const WS = workspaceFixture()
const ITEM_A = itemFixture('rss:e1.a', '文章 A')
const ITEM_B = itemFixture('rss:e1.b', '文章 B')
const ITEM_C = itemFixture('rss:e1.c', '文章 C')

function member(ref: string, position: number, groupName: string | null, pinned = false) {
  return {
    itemRef: ref,
    position,
    addedAt: '2026-09-22T00:00:00Z',
    groupName,
    pinned,
  }
}

/** A 固定；B 在「甲组」；C 未分组。 */
function groupsFixture(): WorkspaceGroupsResponse {
  return {
    workspaceId: 'ws-1',
    revision: 1,
    groupOrder: ['甲组'],
    pinned: [member(ITEM_A.ref, 1, null, true)],
    groups: [
      { name: null, items: [member(ITEM_C.ref, 3, null)] },
      { name: '甲组', items: [member(ITEM_B.ref, 2, '甲组')] },
    ],
  }
}

function contentsFixture(): WorkspaceItemsResolvedResponse {
  return { items: [ITEM_A, ITEM_B, ITEM_C] }
}

function snapshotsFixture(): WorkspaceSnapshotList {
  return {
    items: [
      {
        id: 'snap-1',
        workspaceId: 'ws-1',
        name: '周一快照',
        createdAt: '2026-09-22T09:00:00Z',
        itemCount: 3,
      },
    ],
  }
}

function resumeFixture(pointer: WorkspaceResumeResponse['pointer']): WorkspaceResumeResponse {
  return { workspaceId: 'ws-1', pointer }
}

async function openRowMenu(title: string) {
  fireEvent.click(screen.getByRole('button', { name: `「${title}」条目操作` }))
  return await screen.findByRole('menu')
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  useReaderUi.setState({ selectedEntryRef: null })
  mocks.listWorkspaces.mockResolvedValue({ items: [WS] })
  mocks.getWorkspaceContents.mockResolvedValue(contentsFixture())
  mocks.getWorkspaceGroups.mockResolvedValue(groupsFixture())
  mocks.getWorkspaceResume.mockResolvedValue(resumeFixture(null))
  mocks.putWorkspaceResume.mockResolvedValue(resumeFixture(null))
  mocks.reorderWorkspaceItems.mockResolvedValue({ items: [] })
  mocks.removeWorkspaceItem.mockResolvedValue(undefined)
  mocks.setWorkspaceItemPinned.mockResolvedValue({ itemRef: 'rss:e1.a' })
  mocks.moveWorkspaceItemGroup.mockResolvedValue({ itemRef: 'rss:e1.a' })
  mocks.addWorkspaceItem.mockResolvedValue({ itemRef: 'rss:e1.c' })
  mocks.listWorkspaceSnapshots.mockResolvedValue(snapshotsFixture())
  mocks.captureWorkspaceSnapshot.mockResolvedValue({
    id: 'snap-2',
    workspaceId: 'ws-1',
    name: '测试快照',
    createdAt: '2026-09-23T00:00:00Z',
    itemCount: 3,
  })
  mocks.deleteWorkspaceSnapshot.mockResolvedValue(undefined)
  mocks.restoreWorkspaceSnapshot.mockResolvedValue({
    restored: 3,
    missing: [],
    kept: 0,
    removed: [],
    revision: 7,
  })
})

// ---- N101 分组 ----------------------------------------------------------------

describe('N101 分组视图', () => {
  it('固定区在最前；未分组为隐式前置组；命名组按顺序渲染', async () => {
    render(withProviders(<WorkspacesPage />))
    const grouped = await screen.findByTestId('workspace-grouped-list')
    const sections = within(grouped).getAllByRole('region')
    expect(sections).toHaveLength(3)
    expect(within(sections[0]).getByText('固定')).toBeInTheDocument()
    expect(within(sections[1]).getByText('未分组')).toBeInTheDocument()
    expect(within(sections[2]).getByText('甲组')).toBeInTheDocument()
    // 条目归属正确（A 固定、C 未分组、B 在甲组）。
    expect(within(sections[0]).getByRole('button', { name: '文章 A' })).toBeInTheDocument()
    expect(within(sections[1]).getByRole('button', { name: '文章 C' })).toBeInTheDocument()
    expect(within(sections[2]).getByRole('button', { name: '文章 B' })).toBeInTheDocument()
  })

  it('折叠分组：aria-expanded 切换 + 状态写本机 localStorage（设备本地）', async () => {
    render(withProviders(<WorkspacesPage />))
    const toggle = await screen.findByTestId('workspace-group-toggle-甲组')
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(loadCollapsedGroups('ws-1').has('甲组')).toBe(true)
    // 折叠后该组条目隐藏。
    expect(screen.queryByRole('button', { name: '文章 B' })).not.toBeInTheDocument()
  })

  it('分组视图加载失败 → 诚实回退平铺（不伪造分组）', async () => {
    mocks.getWorkspaceGroups.mockRejectedValue(new Error('network down'))
    render(withProviders(<WorkspacesPage />))
    expect(await screen.findByRole('status')).toHaveTextContent('分组视图加载失败')
    expect(screen.getByRole('button', { name: '文章 A' })).toBeInTheDocument()
    expect(screen.queryByTestId('workspace-grouped-list')).not.toBeInTheDocument()
  })

  it('移动到分组…：菜单 → Dialog 选择既有组 → PATCH group', async () => {
    render(withProviders(<WorkspacesPage />))
    await screen.findByRole('button', { name: '文章 C' })
    await openRowMenu('文章 C')
    fireEvent.click(await screen.findByRole('menuitem', { name: '移动到分组…' }))
    const dialog = await screen.findByRole('dialog', { name: '移动到分组' })
    fireEvent.click(within(dialog).getByRole('radio', { name: '甲组' }))
    fireEvent.click(within(dialog).getByRole('button', { name: '移动' }))
    await waitFor(() => {
      expect(mocks.moveWorkspaceItemGroup).toHaveBeenCalledWith('ws-1', 'rss:e1.c', '甲组')
    })
  })
})

// ---- N102 固定 ----------------------------------------------------------------

describe('N102 固定标签页', () => {
  it('固定区条目标注已固定；菜单 固定/取消固定 = set 语义', async () => {
    render(withProviders(<WorkspacesPage />))
    await screen.findByText('已固定（移除需强制确认）')
    await openRowMenu('文章 C')
    fireEvent.click(await screen.findByRole('menuitem', { name: '固定' }))
    await waitFor(() => {
      expect(mocks.setWorkspaceItemPinned).toHaveBeenCalledWith('ws-1', 'rss:e1.c', true)
    })
  })

  it('移除固定条目 → 409 workspace_item_pinned → 行内诚实提示 + 强制移除', async () => {
    mocks.removeWorkspaceItem
      .mockRejectedValueOnce(new ApiError(409, 'workspace_item_pinned', '条目已固定。'))
      .mockResolvedValueOnce(undefined)
    render(withProviders(<WorkspacesPage />))
    await screen.findByText('已固定（移除需强制确认）')
    await openRowMenu('文章 A')
    fireEvent.click(await screen.findByRole('menuitem', { name: '移除' }))
    // 第一次调用不带 force。
    await waitFor(() => {
      expect(mocks.removeWorkspaceItem).toHaveBeenCalledTimes(1)
    })
    // 409 → 行内诚实提示，绝不静默删除。
    const notice = await screen.findByTestId('workspace-pinned-conflict')
    expect(notice).toHaveTextContent('常规移除被拒绝')
    // 显式确认后强制移除。
    fireEvent.click(within(notice).getByRole('button', { name: /强制移除/ }))
    await waitFor(() => {
      expect(mocks.removeWorkspaceItem).toHaveBeenLastCalledWith(
        'ws-1',
        'rss:e1.a',
        { force: true },
      )
    })
  })
})

// ---- N103 预览 ----------------------------------------------------------------

describe('N103 临时预览', () => {
  it('预览按钮打开页内窗格（不导航）；连续打开 = 替换不叠加', async () => {
    render(withProviders(<WorkspacesPage />))
    // 等分组视图渲染完成，行序才稳定：固定 A → 未分组 C → 甲组 B。
    await screen.findByTestId('workspace-grouped-list')
    const previewButtons = screen.getAllByRole('button', { name: '预览' })
    expect(previewButtons).toHaveLength(3)
    fireEvent.click(previewButtons[0])
    let pane = await screen.findByRole('region', { name: '内容预览' })
    expect(within(pane).getByText('文章 A')).toBeInTheDocument()
    expect(useReaderUi.getState().selectedEntryRef).toBeNull() // 不导航

    fireEvent.click(screen.getAllByRole('button', { name: '预览' })[2])
    pane = screen.getByRole('region', { name: '内容预览' })
    expect(within(pane).getByText('文章 B')).toBeInTheDocument()
    expect(within(pane).queryByText('文章 A')).not.toBeInTheDocument()
    // 同刻只有一个预览窗格。
    expect(screen.getAllByRole('region', { name: '内容预览' })).toHaveLength(1)
  })

  it('提升：成员不渲染「添加到工作区」（幂等入口，UI 不提供重复添加）', async () => {
    render(withProviders(<WorkspacesPage />))
    // 文章 A 已是成员（固定区）。
    await screen.findByTestId('workspace-grouped-list')
    fireEvent.click(screen.getAllByRole('button', { name: '预览' })[0])
    const pane = screen.getByRole('region', { name: '内容预览' })
    expect(within(pane).getByText('已在工作区')).toBeInTheDocument()
    expect(within(pane).queryByRole('button', { name: /添加到工作区/ })).not.toBeInTheDocument()
    expect(mocks.addWorkspaceItem).not.toHaveBeenCalled()
  })

  it('非成员条目（最近关闭恢复）→ 添加到工作区调用一次', async () => {
    const outsider = itemFixture('rss:e1.z', '外来文章')
    // 关键：outsider 不在分组数据里（非成员 → 才有「添加到工作区」按钮）。
    mocks.getWorkspaceGroups.mockResolvedValue({
      workspaceId: 'ws-1',
      revision: 1,
      groupOrder: [],
      pinned: [],
      groups: [],
    } satisfies WorkspaceGroupsResponse)
    mocks.getWorkspaceContents.mockResolvedValue({ items: [outsider] })
    localStorage.setItem(
      'lumi-workspace-recently-closed-v1',
      JSON.stringify([
        {
          ref: 'rss:e1.z',
          title: '外来文章',
          url: 'https://example.com/z',
          workspaceId: 'ws-1',
          closedAt: '2026-09-23T00:00:00Z',
        },
      ]),
    )
    render(withProviders(<WorkspacesPage />))
    await screen.findByRole('button', { name: '外来文章' })
    const closedPanel = await screen.findByTestId('workspace-recently-closed')
    fireEvent.click(within(closedPanel).getByRole('button', { name: '恢复' }))
    const pane = screen.getByRole('region', { name: '内容预览' })
    fireEvent.click(within(pane).getByRole('button', { name: /添加到工作区/ }))
    await waitFor(() => {
      expect(mocks.addWorkspaceItem).toHaveBeenCalledTimes(1)
      expect(mocks.addWorkspaceItem).toHaveBeenCalledWith('ws-1', 'rss:e1.z')
    })
  })

  it('未保存笔记草稿拦截替换：诚实提示 + 保存后放行', async () => {
    render(withProviders(<WorkspacesPage />))
    await screen.findByTestId('workspace-grouped-list')
    fireEvent.click(screen.getAllByRole('button', { name: '预览' })[0])
    const pane = screen.getByRole('region', { name: '内容预览' })
    fireEvent.change(within(pane).getByRole('textbox', { name: '预览笔记草稿' }), {
      target: { value: '未保存的想法' },
    })
    // 尝试替换 → 拦截提示，预览仍是 A。
    fireEvent.click(screen.getAllByRole('button', { name: '预览' })[2])
    expect(screen.getByTestId('workspace-preview-blocked')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: '内容预览' })).getByText('文章 A')).toBeInTheDocument()

    // 保存草稿 → 拦截解除；再次替换成功（B 替换 A，不叠加）。
    fireEvent.click(screen.getByRole('button', { name: /保存草稿/ }))
    expect(screen.queryByTestId('workspace-preview-blocked')).not.toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: '预览' })[2])
    expect(within(screen.getByRole('region', { name: '内容预览' })).getByText('文章 B')).toBeInTheDocument()
  })
})

// ---- N104 最近关闭 ------------------------------------------------------------

describe('N104 最近关闭', () => {
  it('关闭预览进入最近关闭；恢复 = 重新打开预览', async () => {
    render(withProviders(<WorkspacesPage />))
    await screen.findByTestId('workspace-grouped-list')
    fireEvent.click(screen.getAllByRole('button', { name: '预览' })[0])
    fireEvent.click(screen.getByRole('button', { name: '关闭预览' }))
    expect(screen.queryByRole('region', { name: '内容预览' })).not.toBeInTheDocument()
    const panel = screen.getByTestId('workspace-recently-closed')
    expect(within(panel).getByText('文章 A')).toBeInTheDocument()
    fireEvent.click(within(panel).getByRole('button', { name: '恢复' }))
    expect(within(screen.getByRole('region', { name: '内容预览' })).getByText('文章 A')).toBeInTheDocument()
  })

  it('最近关闭为 LRU 上限 20（本机）', () => {
    let list: RecentClosedItem[] = []
    for (let i = 0; i < 30; i += 1) {
      list = pushRecentlyClosed({
        ref: `rss:e${i}`,
        title: `t${i}`,
        url: null,
        workspaceId: 'ws-1',
      })
    }
    expect(list).toHaveLength(RECENTLY_CLOSED_CAP)
    expect(list[0].ref).toBe('rss:e29')
  })
})

// ---- N105 快照 ----------------------------------------------------------------

describe('N105 会话快照', () => {
  it('保存快照（名称输入）→ POST snapshots', async () => {
    render(withProviders(<WorkspacesPage />))
    fireEvent.change(await screen.findByRole('textbox', { name: '快照名称' }), {
      target: { value: '测试快照' },
    })
    fireEvent.click(screen.getByRole('button', { name: /保存快照/ }))
    await waitFor(() => {
      expect(mocks.captureWorkspaceSnapshot).toHaveBeenCalledWith('ws-1', '测试快照')
    })
  })

  it('恢复：模式选择 + diff 摘要诚实展示（缺失不复活）', async () => {
    mocks.restoreWorkspaceSnapshot.mockResolvedValue({
      restored: 3,
      missing: ['rss:e1.gone'],
      kept: 0,
      removed: ['rss:e1.extra'],
      revision: 7,
    })
    render(withProviders(<WorkspacesPage />))
    fireEvent.click(await screen.findByRole('button', { name: '恢复' }))
    const dialog = await screen.findByRole('dialog', { name: /恢复快照/ })
    fireEvent.click(within(dialog).getByRole('radio', { name: /替换/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: '恢复' }))
    await waitFor(() => {
      expect(mocks.restoreWorkspaceSnapshot).toHaveBeenCalledWith(
        'ws-1',
        'snap-1',
        'replace',
        false,
      )
    })
    const result = await screen.findByTestId('workspace-restore-result')
    expect(result).toHaveTextContent('恢复 3 条')
    expect(result).toHaveTextContent('缺失 1 条（未复活）')
    expect(result).toHaveTextContent('移除 1 条')
  })

  it('replace 遇固定条目 409 → 诚实提示，强制恢复带 force 重试', async () => {
    mocks.restoreWorkspaceSnapshot
      .mockRejectedValueOnce(
        new ApiError(409, 'workspace_item_pinned', '存在固定条目。'),
      )
      .mockResolvedValueOnce({ restored: 3, missing: [], kept: 0, removed: ['rss:e1.a'], revision: 8 })
    render(withProviders(<WorkspacesPage />))
    fireEvent.click(await screen.findByRole('button', { name: '恢复' }))
    const dialog = await screen.findByRole('dialog', { name: /恢复快照/ })
    fireEvent.click(within(dialog).getByRole('radio', { name: /替换/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: '恢复' }))
    const notice = await screen.findByText(/常规恢复已被拒绝/)
    fireEvent.click(within(dialog).getByRole('checkbox'))
    void notice
    fireEvent.click(within(dialog).getByRole('button', { name: '恢复' }))
    await waitFor(() => {
      expect(mocks.restoreWorkspaceSnapshot).toHaveBeenLastCalledWith(
        'ws-1',
        'snap-1',
        'replace',
        true,
      )
    })
  })

  it('删除快照：二次确认后 DELETE', async () => {
    render(withProviders(<WorkspacesPage />))
    const row = await screen.findByTestId('workspace-snapshot-snap-1')
    fireEvent.click(within(row).getByRole('button', { name: '删除' }))
    const dialog = await screen.findByRole('dialog', { name: '删除快照' })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认删除' }))
    await waitFor(() => {
      expect(mocks.deleteWorkspaceSnapshot).toHaveBeenCalledWith('ws-1', 'snap-1')
    })
  })
})
