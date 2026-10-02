/** FIX-159 — RAG/Agent 引用点击定位正确性（WEB 腿核验）。
 *
 * 契约边界（按当前真实代码面）：
 * - 引用 ref 不携带段落锚（Agent 消息 citations: string[]；rag ask
 *   citations: {index, ref}）——客户端不存在「按引用滚段」的实现路径，
 *   因此不可能定位到错误段落；摘录 ord 在摘录对话框中显式逐条展示。
 * - 「打开正确文章」：引用 chip 经 POST /resolve 解析，打开走
 *   openResolvedItem → payload.entryRef（服务端权威当前 ref，含别名
 *   归一），而非客户端 ref 字符串拆包猜测。
 * - 「不串账户」：解析缓存在账户切换时整体 clear（O157
 *   resetAccountState → queryClient.clear()）——A 账号解析过的引用
 *   缓存绝不被 B 复用。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type {
  AgentMessage,
  AgentMessageRole,
  AgentThread,
  RagStatus,
} from '../api/client'

import AgentWorkbenchPage from '../components/pages/AgentWorkbenchPage'
import { resetAccountState } from '../lib/auth-reset'
import { useReaderUi } from '../store/reader-ui'

const mocks = vi.hoisted(() => ({
  listAgentThreads: vi.fn(),
  listAgentMessages: vi.fn(),
  getRagStatus: vi.fn(),
  resolveItems: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listAgentThreads: mocks.listAgentThreads,
    listAgentMessages: mocks.listAgentMessages,
    getRagStatus: mocks.getRagStatus,
    resolveItems: mocks.resolveItems,
  }
})

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
    createdAt: '2026-09-01T08:00:0Z',
  } as AgentMessage
}

function withProviders(ui: ReactNode, client?: QueryClient) {
  const qc = client ?? new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  useReaderUi.setState({ section: 'home', selectedEntryRef: null })
  mocks.getRagStatus.mockResolvedValue({
    enabled: false,
    fastembedAvailable: false,
    chunks: 0,
    model: 'none',
    vecTable: false,
    lastRebuildAt: null,
    lastError: null,
  } satisfies RagStatus)
})

describe('FIX-159 — 引用点击打开正确条目', () => {
  it('引用 chip 点击 → selectEntry 使用 resolve 的 payload.entryRef（服务端权威，不用客户端猜 ref）', async () => {
    mocks.listAgentThreads.mockResolvedValue({ items: [threadFixture('t1', '问答会话')] })
    mocks.listAgentMessages.mockResolvedValue({
      items: [
        msgFixture('user', { text: '问题' }, 1),
        {
          ...msgFixture('assistant', { text: '回答正文' }, 2),
          citations: ['rss:e1.a'],
        },
      ],
    })
    // 当前账户的 resolve 返回：ref → canonical entryRef e1.a（标题与
    // 另一账户的相似条目同名也只解析出本账户的 ref）。
    mocks.resolveItems.mockResolvedValue({
      items: [
        {
          ref: 'rss:e1.a',
          domain: 'rss',
          kind: 'rss',
          title: '同名相似条目',
          source: 'rss',
          datetime: null,
          excerpt: null,
          url: null,
          stale: false,
          payload: { entryRef: 'e1.a' },
        },
      ],
    })

    withProviders(<AgentWorkbenchPage />)
    fireEvent.click(await screen.findByRole('button', { name: /^问答会话/ }, { timeout: 3000 }))
    const chip = await screen.findByRole('button', { name: '同名相似条目' })
    fireEvent.click(chip)

    await waitFor(() => {
      expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    })
  })
})

describe('FIX-159 — 引用解析缓存账户隔离（O157 边界）', () => {
  it('账户切换 resetAccountState 清空 resolve 解析缓存——B 不可复用 A 的引用解析', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const keyA = ['resolve', ['rss:e1.a'].join('\n')]
    qc.setQueryData(keyA, {
      items: [
        {
          ref: 'rss:e1.a',
          domain: 'rss',
          kind: 'rss',
          title: 'A 账号的条目',
          source: 'rss',
          datetime: null,
          excerpt: null,
          url: null,
          stale: false,
          payload: { entryRef: 'e1.a' },
        },
      ],
    })
    expect(qc.getQueryData(keyA)).toBeDefined()

    resetAccountState(qc, { broadcast: false })

    expect(qc.getQueryData(keyA)).toBeUndefined()
  })
})
