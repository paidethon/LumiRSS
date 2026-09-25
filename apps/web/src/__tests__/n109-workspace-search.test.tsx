/** N109 测试 — 工作区标签全文检索（WorkspacesPage 搜索本工作区）。
 *
 * 覆盖：搜索输入 → GET /workspaces/{id}/search?q=；结果列表渲染
 * （标题 + 摘要 + 匹配面 chip）与「打开」跳转（复用预览窗格）；
 * 空命中诚实空态；空输入不发请求。scoping 由服务端保证（有 BFF 测试），
 * Web 侧如实透传 q。vi.mock('../api/client')（保留真实导出）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import WorkspacesPage from '../components/pages/WorkspacesPage'
import { useReaderUi } from '../store/reader-ui'
import type {
  ResolvedItem,
  Workspace,
  WorkspaceGroupsResponse,
  WorkspaceItemsResolvedResponse,
} from '../api/types'

configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 20000 })

const mocks = vi.hoisted(() => ({
  listWorkspaces: vi.fn(),
  getWorkspaceContents: vi.fn(),
  getWorkspaceGroups: vi.fn(),
  getWorkspaceResume: vi.fn(),
  searchWorkspace: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listWorkspaces: mocks.listWorkspaces,
    getWorkspaceContents: mocks.getWorkspaceContents,
    getWorkspaceGroups: mocks.getWorkspaceGroups,
    getWorkspaceResume: mocks.getWorkspaceResume,
    searchWorkspace: mocks.searchWorkspace,
  }
})

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

const WS: Workspace = {
  id: 'ws-1',
  name: '研究',
  position: 0,
  itemCount: 2,
  archived: false,
  reserved: false,
  description: '',
  revision: 1,
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

const ITEM_A = itemFixture('rss:e1.a', '文章 A')

const GROUPS: WorkspaceGroupsResponse = {
  workspaceId: 'ws-1',
  revision: 1,
  groupOrder: [],
  pinned: [],
  groups: [{ name: null, items: [{ itemRef: ITEM_A.ref, position: 1, addedAt: '2026-09-22T00:00:00Z', groupName: null, pinned: false }] }],
}

const CONTENTS: WorkspaceItemsResolvedResponse = { items: [ITEM_A] }

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  useReaderUi.setState({ selectedEntryRef: null })
  mocks.listWorkspaces.mockResolvedValue({ items: [WS] })
  mocks.getWorkspaceContents.mockResolvedValue(CONTENTS)
  mocks.getWorkspaceGroups.mockResolvedValue(GROUPS)
  mocks.getWorkspaceResume.mockResolvedValue({ workspaceId: 'ws-1', pointer: null })
  mocks.searchWorkspace.mockResolvedValue({
    workspaceId: 'ws-1',
    query: 'needle',
    truncated: false,
    results: [
      {
        itemRef: ITEM_A.ref,
        domain: 'rss',
        title: '文章 A',
        excerpt: '正文里出现 needle 一词的上下文摘要',
        matchedIn: 'content',
      },
    ],
  })
})

describe('WorkspacesPage — N109 搜索本工作区', () => {
  it('输入关键词 → 搜索并渲染结果（标题/摘要/匹配面/打开跳转）', async () => {
    render(withProviders(<WorkspacesPage />))
    const input = await screen.findByTestId('workspace-search-input')
    fireEvent.change(input, { target: { value: 'needle' } })

    await waitFor(() => expect(mocks.searchWorkspace).toHaveBeenCalled())
    expect(mocks.searchWorkspace.mock.calls[0]?.slice(0, 2)).toEqual(['ws-1', 'needle'])
    const results = await screen.findByTestId('workspace-search-results')
    expect(results).toHaveTextContent('文章 A')
    expect(results).toHaveTextContent('正文里出现 needle 一词的上下文摘要')
    expect(results).toHaveTextContent('全文')

    // 跳转：打开 = 复用既有预览窗格（服务端解析的完整卡片数据）
    fireEvent.click(screen.getByRole('button', { name: '打开' }))
    const slot = await waitFor(() => {
      const el = document.querySelector('[data-workspace-preview-slot]')
      expect(el).not.toBeNull()
      return el as HTMLElement
    })
    expect(slot).toHaveTextContent('文章 A')
  })

  it('空命中 → 诚实空态', async () => {
    mocks.searchWorkspace.mockResolvedValue({
      workspaceId: 'ws-1',
      query: 'nohit',
      truncated: false,
      results: [],
    })
    render(withProviders(<WorkspacesPage />))
    const input = await screen.findByTestId('workspace-search-input')
    fireEvent.change(input, { target: { value: 'nohit' } })
    expect(await screen.findByTestId('workspace-search-empty')).toHaveTextContent(
      '没有匹配「nohit」的条目。',
    )
  })

  it('空输入不发请求', async () => {
    render(withProviders(<WorkspacesPage />))
    await screen.findByTestId('workspace-search-input')
    expect(mocks.searchWorkspace).not.toHaveBeenCalled()
  })
})
