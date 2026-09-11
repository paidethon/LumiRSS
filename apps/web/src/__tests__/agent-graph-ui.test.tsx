/** phase2 G7/G8 — Agent 工作台 + 标签/图谱 Web UI 测试。
 *
 * - AgentWorkbenchPage：会话列表渲染；发送 → POST messages（202）→
 *   轮询 /messages 直到 assistant 回复渲染；
 * - approval 卡片：pending 时给 批准/拒绝；点批准 →
 *   decideAgentApproval(threadId, approvalId, 'approve')；
 * - GraphPage：节点/边摘要行 + truncated 截断提示；「显示为表格」
 *   语义 <table> 等价路径列出节点；标签 chips 渲染名称/数量；
 * - Sidebar / 折叠 Rail：Agent 工作台 / 标签 / 图谱 section 导航激活，
 *   API 来源 / 邮件简报保持 PlannedItem（aria-disabled）。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）+
 * vi.mock('cytoscape')（jsdom 无 canvas；fake 只需 on/destroy）。
 * cytoscape 在页面内是动态 import —— vitest 模块 mock 对其同样生效。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type {
  AgentMessage,
  AgentMessageRole,
  AgentThread,
  GraphResponse,
  RagStatus,
  TagListResponse,
} from '../api/client'
import type { WorkspaceListResponse } from '../api/types'
import AgentWorkbenchPage from '../components/pages/AgentWorkbenchPage'
import GraphPage from '../components/pages/GraphPage'
import Sidebar from '../components/Sidebar'
import SidebarCollapsedRail from '../components/SidebarCollapsedRail'
import { useReaderUi } from '../store/reader-ui'

const mocks = vi.hoisted(() => ({
  getFeeds: vi.fn(),
  listAgentThreads: vi.fn(),
  createAgentThread: vi.fn(),
  deleteAgentThread: vi.fn(),
  listAgentMessages: vi.fn(),
  sendAgentMessage: vi.fn(),
  decideAgentApproval: vi.fn(),
  getRagStatus: vi.fn(),
  listTags: vi.fn(),
  getGraph: vi.fn(),
  listWorkspaces: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getFeeds: mocks.getFeeds,
    listAgentThreads: mocks.listAgentThreads,
    createAgentThread: mocks.createAgentThread,
    deleteAgentThread: mocks.deleteAgentThread,
    listAgentMessages: mocks.listAgentMessages,
    sendAgentMessage: mocks.sendAgentMessage,
    decideAgentApproval: mocks.decideAgentApproval,
    getRagStatus: mocks.getRagStatus,
    listTags: mocks.listTags,
    getGraph: mocks.getGraph,
    listWorkspaces: mocks.listWorkspaces,
  }
})

// jsdom 无 canvas：cytoscape 换成最小 fake（页面只需要 on/destroy）。
const cyInstance = vi.hoisted(() => ({
  on: vi.fn(),
  destroy: vi.fn(),
}))

vi.mock('cytoscape', () => ({
  default: vi.fn(() => cyInstance),
}))

// ---- fixtures ----

function threadFixture(id: string, title: string): AgentThread {
  return { id, title, createdAt: '2026-09-01T08:00:00Z' }
}

function msgFixture(
  role: AgentMessageRole,
  content: Record<string, unknown>,
  seq: number,
): AgentMessage {
  return {
    id: `m${seq}`,
    threadId: 't1',
    seq,
    role,
    content,
    citations: [],
    createdAt: '2026-09-01T08:00:00Z',
  }
}

function ragFixture(): RagStatus {
  return {
    enabled: false,
    chunks: 0,
    model: 'test-model',
    vecTable: true,
    lastRebuildAt: null,
    lastError: null,
    fastembedAvailable: true,
  }
}

function tagsFixture(): TagListResponse {
  return {
    items: [
      { id: 1, name: 'rss', count: 2 },
      { id: 2, name: '前端', count: 1 },
    ],
  }
}

function workspacesFixture(): WorkspaceListResponse {
  return {
    items: [
      { id: 'w1', name: '工作区一', itemCount: 0, position: 0, reserved: false },
    ],
  }
}

function graphFixture(truncated = false): GraphResponse {
  return {
    nodes: [
      { ref: 'library:1', label: '书签一', kind: 'library', degree: 1 },
      { ref: 'tag:rss', label: '#rss', kind: 'tag', degree: 2 },
      { ref: 'rss:https://example.com', label: '示例订阅', kind: 'rss', degree: 1 },
    ],
    edges: [
      { src: 'library:1', dst: 'tag:rss', kind: 'tagged' },
      { src: 'rss:https://example.com', dst: 'tag:rss', kind: 'tagged' },
    ],
    truncated,
    totalNodes: 3,
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
  cyInstance.on.mockClear()
  cyInstance.destroy.mockClear()
  useReaderUi.setState({
    section: 'home',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
  mocks.getFeeds.mockResolvedValue([])
  mocks.listAgentThreads.mockResolvedValue({ items: [] })
  mocks.listAgentMessages.mockResolvedValue({ items: [] })
  mocks.sendAgentMessage.mockResolvedValue({ status: 'processing' })
  mocks.decideAgentApproval.mockResolvedValue({ status: 'ok', message: null })
  mocks.getRagStatus.mockResolvedValue(ragFixture())
  mocks.listTags.mockResolvedValue(tagsFixture())
  mocks.getGraph.mockResolvedValue(graphFixture())
  mocks.listWorkspaces.mockResolvedValue(workspacesFixture())
})

describe('AgentWorkbenchPage', () => {
  it('会话列表渲染；发送 → POST 消息 → 轮询直到 assistant 回复渲染', async () => {
    mocks.listAgentThreads.mockResolvedValue({
      items: [threadFixture('t1', '测试会话')],
    })
    const userMsg = msgFixture('user', { text: '你好' }, 1)
    const assistantMsg = msgFixture('assistant', { text: '你好，这是回答。' }, 2)
    let polls = 0
    mocks.listAgentMessages.mockImplementation(() => {
      polls += 1
      if (polls <= 1) return Promise.resolve({ items: [] })
      if (polls === 2) return Promise.resolve({ items: [userMsg] })
      return Promise.resolve({ items: [userMsg, assistantMsg] })
    })

    render(withProviders(<AgentWorkbenchPage />))

    // 选中已有会话（行 = 标题 + 相对时间）
    fireEvent.click(await screen.findByRole('button', { name: /测试会话/ }))
    fireEvent.change(screen.getByLabelText('输入消息'), { target: { value: '你好' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() =>
      expect(mocks.sendAgentMessage).toHaveBeenCalledWith('t1', '你好'),
    )
    // 轮询先见 user 气泡，最终渲染 assistant 回复（refetchInterval 1s → 放宽超时）
    await waitFor(
      () => expect(screen.getByText('你好，这是回答。')).toBeInTheDocument(),
      { timeout: 5000 },
    )
    expect(screen.getByText('你好')).toBeInTheDocument()
    expect(polls).toBeGreaterThanOrEqual(3)
  })

  it('approval 卡片：pending 给 批准/拒绝；点批准调用 approve', async () => {
    mocks.listAgentThreads.mockResolvedValue({
      items: [threadFixture('t1', '测试会话')],
    })
    mocks.listAgentMessages.mockResolvedValue({
      items: [
        msgFixture('user', { text: '保存这个页面' }, 1),
        msgFixture(
          'approval',
          {
            approvalId: 'a1',
            callId: 'c1',
            tool: 'save_bookmark',
            args: { url: 'https://example.com' },
            status: 'pending',
            expiresInMinutes: 15,
          },
          2,
        ),
      ],
    })

    render(withProviders(<AgentWorkbenchPage />))
    fireEvent.click(await screen.findByRole('button', { name: /测试会话/ }))

    expect(await screen.findByText(/需要批准的写入操作 · save_bookmark/)).toBeInTheDocument()
    // args pretty JSON 可见
    expect(screen.getByText(/"url": "https:\/\/example.com"/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '批准写入' }))
    await waitFor(() =>
      expect(mocks.decideAgentApproval).toHaveBeenCalledWith('t1', 'a1', 'approve'),
    )
    expect(screen.getByRole('button', { name: '拒绝写入' })).toBeInTheDocument()
  })
})

describe('GraphPage', () => {
  it('摘要行 + truncated 截断提示；显示为表格 → 语义 table 列出节点', async () => {
    mocks.getGraph.mockResolvedValue(graphFixture(true))
    render(withProviders(<GraphPage />))

    expect(await screen.findByText(/共 3 节点 · 2 边/)).toBeInTheDocument()
    expect(
      screen.getByText(/节点过多，已按连接数截断显示前 2000 个/),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '显示为表格' }))
    const table = screen.getByRole('table')
    expect(within(table).getByText('书签一')).toBeInTheDocument()
    expect(within(table).getByText('#rss')).toBeInTheDocument()
    expect(within(table).getByText('示例订阅')).toBeInTheDocument()
    // 列头齐全（标签 / 类型 / 连接数）
    expect(within(table).getByText('连接数')).toBeInTheDocument()
  })

  it('标签 chips 渲染名称/数量（非图形等价路径）', async () => {
    render(withProviders(<GraphPage />))
    expect(await screen.findByText('#rss (2)')).toBeInTheDocument()
    expect(screen.getByText('#前端 (1)')).toBeInTheDocument()
    expect(screen.getByText('标签列表（非图形等价路径）')).toBeInTheDocument()
  })
})

describe('Sidebar / 折叠 Rail 导航激活', () => {
  it('Sidebar：Agent 工作台 → section=agent；标签 / 图谱 → section=graph；API 来源/邮件简报保持 PlannedItem', () => {
    render(withProviders(<Sidebar />))
    fireEvent.click(screen.getByRole('button', { name: 'Agent 工作台' }))
    expect(useReaderUi.getState().section).toBe('agent')
    fireEvent.click(screen.getByRole('button', { name: '标签 / 图谱' }))
    expect(useReaderUi.getState().section).toBe('graph')

    const apiSource = screen.getByText('API 来源').closest('div')
    expect(apiSource).toHaveAttribute('aria-disabled', 'true')
    const mailDigest = screen.getByText('邮件简报').closest('div')
    expect(mailDigest).toHaveAttribute('aria-disabled', 'true')
  })

  it('折叠 Rail：Agent 工作台 / 标签 / 图谱 可点击激活对应 section', () => {
    render(withProviders(<SidebarCollapsedRail />))
    fireEvent.click(screen.getByRole('button', { name: 'Agent 工作台' }))
    expect(useReaderUi.getState().section).toBe('agent')
    fireEvent.click(screen.getByRole('button', { name: '标签 / 图谱' }))
    expect(useReaderUi.getState().section).toBe('graph')
  })
})
