/** P15 — 工作区续读指针 + 跨设备并发 UI 闭环。
 *
 * vi.mock('../api/client')（保留 ApiError 等真实导出，p0-10 模式）：
 * - 续读 chip：指针存在且指向列表内条目时显示「继续上次：<标题>」；
 *   点击 = 打开该条目（既有 lib/open-item 路由）+ PUT 续读指针；
 *   指针为空 / 指向条目不在列表 → 诚实隐藏；
 * - 打开条目（卡片标题）→ PUT 续读指针；
 * - 重排序 409（workspace_revision_conflict）→ 页面级诚实提示 +
 *   重取（getWorkspaceContents 再次调用），行内不重复报错；
 * - 重排序成功 → 无提示，且请求携带 expectedRevision。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import WorkspacesPage from '../components/pages/WorkspacesPage'
import { ApiError } from '../api/client'
import { useReaderUi } from '../store/reader-ui'
import type {
  ResolvedItem,
  Workspace,
  WorkspaceItemsResolvedResponse,
  WorkspaceResumeResponse,
} from '../api/types'

const mocks = vi.hoisted(() => ({
  listWorkspaces: vi.fn(),
  getWorkspaceContents: vi.fn(),
  getWorkspaceResume: vi.fn(),
  putWorkspaceResume: vi.fn(),
  reorderWorkspaceItems: vi.fn(),
  removeWorkspaceItem: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listWorkspaces: mocks.listWorkspaces,
    getWorkspaceContents: mocks.getWorkspaceContents,
    getWorkspaceResume: mocks.getWorkspaceResume,
    putWorkspaceResume: mocks.putWorkspaceResume,
    reorderWorkspaceItems: mocks.reorderWorkspaceItems,
    removeWorkspaceItem: mocks.removeWorkspaceItem,
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
    url: 'https://example.com/a',
    stale: false,
    payload: {},
  }
}

const WS = workspaceFixture({ id: 'ws-1', name: '研究' })
const ITEM_A = itemFixture('rss:e1.a', '文章 A')
const ITEM_B = itemFixture('rss:e1.b', '文章 B')

function contentsFixture(): WorkspaceItemsResolvedResponse {
  return { items: [ITEM_A, ITEM_B] }
}

function resumeFixture(pointer: WorkspaceResumeResponse['pointer']): WorkspaceResumeResponse {
  return { workspaceId: 'ws-1', pointer }
}

beforeEach(() => {
  vi.clearAllMocks()
  useReaderUi.setState({ selectedEntryRef: null })
  mocks.listWorkspaces.mockResolvedValue({ items: [WS] })
  mocks.getWorkspaceContents.mockResolvedValue(contentsFixture())
  mocks.getWorkspaceResume.mockResolvedValue(resumeFixture(null))
  mocks.putWorkspaceResume.mockResolvedValue(resumeFixture(null))
  mocks.reorderWorkspaceItems.mockResolvedValue({ items: [] })
  mocks.removeWorkspaceItem.mockResolvedValue(undefined)
})

describe('P15 续读 chip', () => {
  it('指针存在且指向列表内条目：显示 chip；点击打开该条目并 PUT 指针', async () => {
    mocks.getWorkspaceResume.mockResolvedValue(
      resumeFixture({ itemRef: 'rss:e1.b', positionAtSave: 2, updatedAt: '2026-09-23T00:00:00Z' }),
    )
    render(withProviders(<WorkspacesPage />))

    const chip = await screen.findByText(/继续上次：/)
    expect(chip).toHaveTextContent('文章 B')

    fireEvent.click(screen.getByRole('button', { name: /继续上次：/ }))
    // 打开路由（rss → Reader selectEntry）真实生效。
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.b')
    // 打开成功 → 保存续读指针。
    await waitFor(() => {
      expect(mocks.putWorkspaceResume).toHaveBeenCalledWith('ws-1', 'rss:e1.b')
    })
  })

  it('无指针 → 不显示 chip', async () => {
    render(withProviders(<WorkspacesPage />))
    await screen.findByText('文章 A')
    expect(screen.queryByText(/继续上次：/)).toBeNull()
  })

  it('指针指向的条目不在列表（他端已移除）→ 诚实隐藏 chip', async () => {
    mocks.getWorkspaceResume.mockResolvedValue(
      resumeFixture({ itemRef: 'rss:e1.gone', positionAtSave: 9, updatedAt: '2026-09-23T00:00:00Z' }),
    )
    render(withProviders(<WorkspacesPage />))
    await screen.findByText('文章 A')
    expect(screen.queryByText(/继续上次：/)).toBeNull()
  })
})

describe('P15 打开条目保存指针', () => {
  it('点击卡片标题打开 → PUT 续读指针（打开路由不变）', async () => {
    render(withProviders(<WorkspacesPage />))
    fireEvent.click(await screen.findByRole('button', { name: '文章 A' }))
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    await waitFor(() => {
      expect(mocks.putWorkspaceResume).toHaveBeenCalledWith('ws-1', 'rss:e1.a')
    })
  })
})

describe('P15 重排序跨设备冲突', () => {
  it('409 workspace_revision_conflict → 诚实提示 + 重取；行内不重复报错', async () => {
    mocks.reorderWorkspaceItems.mockRejectedValue(
      new ApiError(409, 'workspace_revision_conflict', '工作区已在其他设备更新。'),
    )
    render(withProviders(<WorkspacesPage />))
    const moveUpButtons = await screen.findAllByRole('button', { name: '上移' })
    fireEvent.click(moveUpButtons[1]) // 第二张卡上移

    const notice = await screen.findByText(/工作区已在其他设备更新，已刷新/)
    expect(notice).toBeInTheDocument()
    // 诚实重取：contents 失效后再次拉取（初始 + 重取 ≥ 2 次）。
    await waitFor(() => {
      expect(mocks.getWorkspaceContents.mock.calls.length).toBeGreaterThanOrEqual(2)
    })
    // 冲突走页面级提示，行内不重复出现「操作失败」。
    expect(screen.queryByText(/操作失败/)).toBeNull()
  })

  it('重排序成功 → 无提示；请求携带 expectedRevision', async () => {
    render(withProviders(<WorkspacesPage />))
    const moveUpButtons = await screen.findAllByRole('button', { name: '上移' })
    fireEvent.click(moveUpButtons[1])

    await waitFor(() => {
      expect(mocks.reorderWorkspaceItems).toHaveBeenCalledWith('ws-1', [ITEM_B.ref, ITEM_A.ref], 1)
    })
    await waitFor(() => {
      expect(mocks.getWorkspaceContents.mock.calls.length).toBeGreaterThanOrEqual(2)
    })
    expect(screen.queryByText(/工作区已在其他设备更新/)).toBeNull()
  })
})
