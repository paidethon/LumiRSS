/** N111/N112/N113/N114/N120 — 工作区材料扩展 UI 闭环。
 *
 * vi.mock('../api/client')（保留 ApiError 等真实导出，p0-10 模式）：
 * - N111 目标卡：目标陈述 + 完成条件清单渲染；勾选写设备本机
 *   localStorage（服务端只存文本）；编辑表单带陈述/条件；
 * - N112 看板：五状态列（含 待摘录/待验证）+ 移动下拉含全部状态；
 * - N113 大纲：分节列表渲染（同一条目跨节重复出现原样展示；unresolved
 *   诚实标记）；行菜单「移动到分节…」→ Dialog → 加入（可多节）；
 * - N114 汇编预览：按大纲展示草稿（标题/摘录/引文/排除计数）+ 下载
 *   Markdown 走 markdown 端点；
 * - N120 清理预演：分类目只读报告 → 勾选可执行类目 → 应用 → 撤销。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import WorkspacesPage from '../components/pages/WorkspacesPage'
import { loadCheckedConditions } from '../lib/goal-conditions'
import { useReaderUi } from '../store/reader-ui'
import type {
  ResolvedItem,
  Workspace,
  WorkspaceGroupsResponse,
  WorkspaceItemsResolvedResponse,
  WorkspaceResumeResponse,
} from '../api/types'

configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 20000 })

const mocks = vi.hoisted(() => ({
  listWorkspaces: vi.fn(),
  getWorkspaceContents: vi.fn(),
  getWorkspaceGroups: vi.fn(),
  getWorkspaceResume: vi.fn(),
  putWorkspaceResume: vi.fn(),
  getWorkspaceBoard: vi.fn(),
  getWorkspaceGoal: vi.fn(),
  putWorkspaceGoal: vi.fn(),
  setBoardStatus: vi.fn(),
  listWorkspaceSections: vi.fn(),
  createWorkspaceSection: vi.fn(),
  addWorkspaceSectionItem: vi.fn(),
  removeWorkspaceSectionItem: vi.fn(),
  reorderWorkspaceSections: vi.fn(),
  compileWorkspace: vi.fn(),
  compileWorkspaceMarkdown: vi.fn(),
  getWorkspaceCleanupPreview: vi.fn(),
  applyWorkspaceCleanup: vi.fn(),
  undoWorkspaceCleanup: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listWorkspaces: mocks.listWorkspaces,
    getWorkspaceContents: mocks.getWorkspaceContents,
    getWorkspaceGroups: mocks.getWorkspaceGroups,
    getWorkspaceResume: mocks.getWorkspaceResume,
    putWorkspaceResume: mocks.putWorkspaceResume,
    getWorkspaceBoard: mocks.getWorkspaceBoard,
    getWorkspaceGoal: mocks.getWorkspaceGoal,
    putWorkspaceGoal: mocks.putWorkspaceGoal,
    setBoardStatus: mocks.setBoardStatus,
    listWorkspaceSections: mocks.listWorkspaceSections,
    createWorkspaceSection: mocks.createWorkspaceSection,
    addWorkspaceSectionItem: mocks.addWorkspaceSectionItem,
    removeWorkspaceSectionItem: mocks.removeWorkspaceSectionItem,
    reorderWorkspaceSections: mocks.reorderWorkspaceSections,
    compileWorkspace: mocks.compileWorkspace,
    compileWorkspaceMarkdown: mocks.compileWorkspaceMarkdown,
    getWorkspaceCleanupPreview: mocks.getWorkspaceCleanupPreview,
    applyWorkspaceCleanup: mocks.applyWorkspaceCleanup,
    undoWorkspaceCleanup: mocks.undoWorkspaceCleanup,
  }
})

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function workspaceFixture(): Workspace {
  return {
    id: 'ws-1',
    name: '研究',
    position: 0,
    itemCount: 2,
    archived: false,
    reserved: false,
    description: '',
    revision: 1,
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

function groupsFixture(): WorkspaceGroupsResponse {
  return {
    workspaceId: 'ws-1',
    revision: 1,
    groupOrder: [],
    pinned: [],
    groups: [
      { name: null, items: [{ itemRef: ITEM_A.ref, position: 1, addedAt: '2026-09-22T00:00:00Z', groupName: null, pinned: false }] },
      { name: null, items: [{ itemRef: ITEM_B.ref, position: 2, addedAt: '2026-09-22T00:00:00Z', groupName: null, pinned: false }] },
    ],
  }
}

function contentsFixture(): WorkspaceItemsResolvedResponse {
  return { items: [ITEM_A, ITEM_B] }
}

function sectionsFixture() {
  return {
    items: [
      {
        id: 'sec-1',
        workspaceId: 'ws-1',
        title: '背景',
        sortIndex: 1,
        createdAt: '2026-09-23T00:00:00Z',
        items: [
          { itemRef: ITEM_A.ref, position: 1, addedAt: '2026-09-23T00:00:00Z', unresolved: false },
          { itemRef: 'rss:e1.gone', position: 2, addedAt: '2026-09-23T00:00:00Z', unresolved: true },
        ],
      },
      {
        id: 'sec-2',
        workspaceId: 'ws-1',
        title: '方法',
        sortIndex: 2,
        createdAt: '2026-09-23T00:00:00Z',
        items: [
          // 同一条目（文章 A）同时属于第二个分节 —— 引用而非复制
          { itemRef: ITEM_A.ref, position: 1, addedAt: '2026-09-23T00:00:00Z', unresolved: false },
        ],
      },
    ],
  }
}

function goalFixture() {
  return {
    workspaceId: 'ws-1',
    targetCount: 2,
    deadline: null,
    doneCount: 1,
    createdAt: '2026-09-23T00:00:00Z',
    goalText: '读完两篇检索增强文章',
    conditions: ['能复述核心论点', '写一篇摘要'],
  }
}

function boardFixture() {
  const statuses = ['todo', 'reading', 'excerpted', 'needs_verification', 'done'] as const
  return {
    workspaceId: 'ws-1',
    columns: statuses.map((status) => ({
      status,
      items:
        status === 'done'
          ? [{ itemRef: ITEM_B.ref, status, updatedAt: '2026-09-23T00:00:00Z' }]
          : [],
      total: status === 'done' ? 1 : 0,
    })),
  }
}

function cleanupPreviewFixture() {
  return {
    workspaceId: 'ws-1',
    categories: [
      {
        category: 'unresolved_refs',
        items: [{ itemRef: 'rss:e1.gone', reason: '来源条目已不存在（feed/entry 已消失）。' }],
      },
      { category: 'protected_library_refs', items: [] },
      { category: 'unverifiable_refs', items: [] },
      { category: 'empty_groups', items: [] },
      { category: 'orphan_section_refs', items: [] },
      { category: 'pinned_group_conflicts', items: [] },
    ],
    actionable: ['unresolved_refs', 'empty_groups', 'orphan_section_refs'],
    reportOnly: ['protected_library_refs', 'unverifiable_refs', 'pinned_group_conflicts'],
  }
}

function compileFixture() {
  return {
    workspaceId: 'ws-1',
    workspaceName: '研究',
    generatedAt: '2026-09-24T00:00:00Z',
    sections: [
      {
        sectionId: 'sec-1',
        title: '背景',
        items: [
          {
            itemRef: ITEM_A.ref,
            title: '文章 A',
            excerpt: '这是摘要',
            citation: '/reader?entry=e1.a',
            note: null,
          },
        ],
      },
      {
        sectionId: 'sec-2',
        title: '方法',
        items: [],
      },
    ],
    includedCount: 1,
    excludedMissing: 1,
    excluded: [{ itemRef: 'rss:e1.gone', reason: 'not_found' }],
  }
}

function resumeFixture(pointer: WorkspaceResumeResponse['pointer']): WorkspaceResumeResponse {
  return { workspaceId: 'ws-1', pointer }
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
  mocks.listWorkspaceSections.mockResolvedValue(sectionsFixture())
  mocks.addWorkspaceSectionItem.mockResolvedValue({
    itemRef: ITEM_A.ref,
    position: 1,
    addedAt: '2026-09-24T00:00:00Z',
    unresolved: false,
  })
  mocks.createWorkspaceSection.mockResolvedValue({
    id: 'sec-new',
    workspaceId: 'ws-1',
    title: '新节',
    sortIndex: 3,
    createdAt: '2026-09-24T00:00:00Z',
    items: [],
  })
  mocks.getWorkspaceGoal.mockResolvedValue(goalFixture())
  mocks.putWorkspaceGoal.mockResolvedValue(goalFixture())
  mocks.getWorkspaceBoard.mockResolvedValue(boardFixture())
  mocks.setBoardStatus.mockResolvedValue({
    itemRef: ITEM_B.ref,
    status: 'todo',
    updatedAt: '2026-09-24T00:00:00Z',
  })
  mocks.compileWorkspace.mockResolvedValue(compileFixture())
  mocks.compileWorkspaceMarkdown.mockResolvedValue('# 研究（汇编草稿）')
  mocks.getWorkspaceCleanupPreview.mockResolvedValue(cleanupPreviewFixture())
  mocks.applyWorkspaceCleanup.mockResolvedValue({
    logId: 'clean-1',
    removed: { unresolvedRefs: 1, emptyGroups: 0, orphanSectionRefs: 0 },
  })
  mocks.undoWorkspaceCleanup.mockResolvedValue({
    logId: 'clean-1',
    restoredRefs: 1,
    restoredSectionRefs: 0,
  })
})

async function openOutline() {
  render(withProviders(<WorkspacesPage />))
  fireEvent.click(await screen.findByRole('button', { name: '大纲' }))
  await screen.findByTestId('workspace-outline')
}

// ===== N111 目标卡 ============================================================

describe('N111 目标卡扩展', () => {
  it('渲染目标陈述 + 完成条件清单；勾选写设备本机 localStorage', async () => {
    render(withProviders(<WorkspacesPage />))
    fireEvent.click(await screen.findByRole('button', { name: '看板' }))
    expect(await screen.findByTestId('goal-statement')).toHaveTextContent(
      '读完两篇检索增强文章',
    )
    const conditions = screen.getByTestId('goal-conditions')
    expect(conditions).toHaveTextContent('能复述核心论点')
    expect(conditions).toHaveTextContent('写一篇摘要')
    // 勾选 → 只写本机（不调用 PUT）
    fireEvent.click(screen.getByRole('checkbox', { name: '完成条件：能复述核心论点' }))
    await waitFor(() => {
      expect(loadCheckedConditions('ws-1', ['能复述核心论点', '写一篇摘要'])).toEqual(
        new Set(['能复述核心论点']),
      )
    })
    expect(mocks.putWorkspaceGoal).not.toHaveBeenCalled()
  })

  it('编辑表单提交 goalText/conditions（PUT 接受扩展字段）', async () => {
    render(withProviders(<WorkspacesPage />))
    fireEvent.click(await screen.findByRole('button', { name: '看板' }))
    fireEvent.click(await screen.findByRole('button', { name: '编辑目标' }))
    const editor = await screen.findByTestId('goal-editor')
    expect(editor).toHaveTextContent('目标陈述')
    fireEvent.change(screen.getByLabelText('目标陈述'), {
      target: { value: '新的陈述' },
    })
    fireEvent.change(screen.getByLabelText('完成条件'), {
      target: { value: '条件一\n条件二' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(mocks.putWorkspaceGoal).toHaveBeenCalledWith('ws-1', 2, null, {
        goalText: '新的陈述',
        conditions: ['条件一', '条件二'],
      })
    })
  })
})

// ===== N112 看板五状态 ========================================================

describe('N112 材料状态扩展', () => {
  it('看板渲染五列（含 待摘录/待验证）；移动下拉含全部状态', async () => {
    render(withProviders(<WorkspacesPage />))
    fireEvent.click(await screen.findByRole('button', { name: '看板' }))
    await screen.findByTestId('workspace-board')
    for (const label of ['待处理', '阅读中', '待摘录', '待验证', '已完成']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
    const select = screen.getByRole('combobox', { name: '移动条目 rss:e1.b' })
    for (const option of ['待处理', '阅读中', '待摘录', '待验证', '已完成']) {
      expect(within(select).getByRole('option', { name: option })).toBeInTheDocument()
    }
    fireEvent.change(select, { target: { value: 'needs_verification' } })
    await waitFor(() => {
      expect(mocks.setBoardStatus).toHaveBeenCalledWith('ws-1', 'rss:e1.b', 'needs_verification')
    })
  })
})

// ===== N113 大纲 ================================================================

describe('N113 分节大纲', () => {
  it('分节列表渲染：同一条目跨节重复出现原样展示；unresolved 诚实标记', async () => {
    await openOutline()
    const sec1 = await screen.findByTestId('workspace-section-sec-1')
    const sec2 = await screen.findByTestId('workspace-section-sec-2')
    expect(sec1).toHaveTextContent('背景')
    expect(sec2).toHaveTextContent('方法')
    // 同一条目（文章 A）在两个分节都有引用
    expect(sec1.querySelector(`[data-section-item="${ITEM_A.ref}"]`)).not.toBeNull()
    expect(sec2.querySelector(`[data-section-item="${ITEM_A.ref}"]`)).not.toBeNull()
    // 悬空引用诚实标记
    expect(sec1.querySelector('[data-section-item="rss:e1.gone"]')).not.toBeNull()
    expect(screen.getAllByTestId('section-item-unresolved').length).toBe(1)
  })

  it('行菜单「移动到分节…」→ Dialog：可加入已有条目的节（多节引用）', async () => {
    render(withProviders(<WorkspacesPage />))
    fireEvent.click(await screen.findByRole('button', { name: `「文章 B」条目操作` }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '移动到分节…' }))
    const dialog = await screen.findByRole('dialog', { name: '移动到分节' })
    // 文章 A 已在 背景 节 → 标注；但 B 未在任何节，选择「方法」加入
    fireEvent.click(await within(dialog).findByRole('radio', { name: /方法/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: '加入分节' }))
    await waitFor(() => {
      expect(mocks.addWorkspaceSectionItem).toHaveBeenCalledWith('ws-1', 'sec-2', ITEM_B.ref)
    })
  })

  it('已在节中的条目仍可选（同一条目允许多节引用，幂等加入）', async () => {
    render(withProviders(<WorkspacesPage />))
    fireEvent.click(await screen.findByRole('button', { name: `「文章 A」条目操作` }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '移动到分节…' }))
    const dialog = await screen.findByRole('dialog', { name: '移动到分节' })
    // 文章 A 已在「背景」与「方法」两节 → 每节都显示「已在该节」；radio 仍可用
    await waitFor(() => {
      expect(within(dialog).getAllByText('已在该节').length).toBe(2)
    })
    fireEvent.click(within(dialog).getByRole('radio', { name: /背景/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: '加入分节' }))
    await waitFor(() => {
      expect(mocks.addWorkspaceSectionItem).toHaveBeenCalledWith('ws-1', 'sec-1', ITEM_A.ref)
    })
  })
})

// ===== N114 汇编预览 ==========================================================

describe('N114 汇编预览', () => {
  it('按大纲展示草稿（标题/摘录/引文/诚实排除计数）', async () => {
    await openOutline()
    fireEvent.click(screen.getByRole('button', { name: '汇编预览' }))
    const draft = await screen.findByTestId('compile-draft-body')
    expect(draft).toHaveTextContent('背景')
    expect(draft).toHaveTextContent('文章 A')
    expect(draft).toHaveTextContent('/reader?entry=e1.a')
    expect(draft).toHaveTextContent('收录 1 条 · 排除 1 条')
    expect(mocks.compileWorkspace).toHaveBeenCalledWith('ws-1')
  })

  it('下载 Markdown 走 markdown 端点', async () => {
    const createObjectURL = vi.fn(() => 'blob:mock')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', {
      value: createObjectURL,
      configurable: true,
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: revokeObjectURL,
      configurable: true,
    })
    await openOutline()
    fireEvent.click(screen.getByRole('button', { name: '汇编预览' }))
    await screen.findByTestId('compile-draft-body')
    fireEvent.click(screen.getByRole('button', { name: '下载 Markdown' }))
    await waitFor(() => {
      expect(mocks.compileWorkspaceMarkdown).toHaveBeenCalledWith('ws-1')
      expect(createObjectURL).toHaveBeenCalled()
    })
  })
})

// ===== N120 清理预演 ==========================================================

describe('N120 清理预演', () => {
  it('分类目报告 + 勾选可执行类目应用 + 撤销', async () => {
    await openOutline()
    fireEvent.click(screen.getByRole('button', { name: '清理预演' }))
    const panel = await screen.findByTestId('workspace-cleanup-panel')
    await within(panel).findByText('已消失的来源条目')
    expect(panel).toHaveTextContent('rss:e1.gone')
    fireEvent.click(
      screen.getByRole('checkbox', { name: '选择清理类目：已消失的来源条目' }),
    )
    fireEvent.click(screen.getByRole('button', { name: '应用选中的清理（1 类）' }))
    await waitFor(() => {
      expect(mocks.applyWorkspaceCleanup).toHaveBeenCalledWith('ws-1', ['unresolved_refs'])
    })
    // 应用成功 → 摘要 + 撤销入口
    expect(await screen.findByTestId('cleanup-applied')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    await waitFor(() => {
      expect(mocks.undoWorkspaceCleanup).toHaveBeenCalledWith('ws-1', 'clean-1')
    })
  })

  it('没有可清理项目时诚实空态', async () => {
    mocks.getWorkspaceCleanupPreview.mockResolvedValue({
      workspaceId: 'ws-1',
      categories: cleanupPreviewFixture().categories.map((c) => ({ ...c, items: [] })),
      actionable: ['unresolved_refs', 'empty_groups', 'orphan_section_refs'],
      reportOnly: [],
    })
    await openOutline()
    fireEvent.click(screen.getByRole('button', { name: '清理预演' }))
    expect(await screen.findByTestId('cleanup-empty')).toHaveTextContent(
      '没有发现可清理的项目。',
    )
  })
})
