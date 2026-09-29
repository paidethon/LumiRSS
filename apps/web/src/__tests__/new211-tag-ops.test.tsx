/** NEW-211 标签整理工作台入口测试 —— 合并向导预览→应用主链路 + 错误态。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import New211TagOpsPanel from '../components/new211/New211TagOpsPanel'

const TAGS = {
  items: [
    { id: 1, name: '旧标签', count: 3 },
    { id: 2, name: '另一个旧标签', count: 1 },
    { id: 3, name: '目标标签', count: 5 },
  ],
}

const PREVIEW = {
  target: { tagId: 3, name: '目标标签' },
  sources: [{ tagId: 1, name: '旧标签', bindings: 3, overlaps: 1, willMove: 2 }],
  affectedArticles: 7,
  references: { synonyms: 2, groupMemberships: 1 },
}

const APPLY = {
  logId: 'log-1',
  targetName: '目标标签',
  mergedSources: [{ tagId: 1, name: '旧标签', bindings: 3 }],
  synonymsSynced: 2,
  groupMembershipsReleased: 1,
}

let mergeShouldFail = false

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/api/v1/tags/merge-wizard/logs')) {
    return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
  }
  if (method === 'GET' && url.includes('/api/v1/tags')) {
    return Promise.resolve(new Response(JSON.stringify(TAGS), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/merge-wizard/preview')) {
    if (mergeShouldFail) {
      return Promise.resolve(
        new Response(JSON.stringify({ error: { type: 'invalid_merge_wizard', message: '目标标签不能同时在源标签列表中。' } }), { status: 422 }),
      )
    }
    return Promise.resolve(new Response(JSON.stringify(PREVIEW), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/merge-wizard/apply')) {
    return Promise.resolve(new Response(JSON.stringify(APPLY), { status: 200 }))
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <New211TagOpsPanel onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  mergeShouldFail = false
  vi.clearAllMocks()
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)
})

describe('New211TagOpsPanel', () => {
  it('合并向导：勾选源标签 → 预览 → 确认合并（真实链路）', async () => {
    renderPanel()
    await screen.findByRole('tab', { name: '合并向导' })
    fireEvent.click(await screen.findByRole('checkbox', { name: /旧标签（3）/ }))
    await waitFor(() => expect(screen.getByLabelText('目标标签')).not.toBeDisabled())
    fireEvent.change(screen.getByLabelText('目标标签'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: '预览合并' }))
    const box = await screen.findByTestId('new211-merge-preview')
    expect(box).toHaveTextContent('受影响文章 7 篇')
    expect(box).toHaveTextContent('将移动 2')
    fireEvent.click(screen.getByRole('button', { name: '确认原子合并' }))
    await waitFor(() => expect(screen.getByTestId('new211-merge-result')).toBeInTheDocument())
    expect(screen.getByTestId('new211-merge-result')).toHaveTextContent('已合并到「目标标签」')
  })

  it('预览失败（422 稳定信封）→ 诚实错误而非假成功', async () => {
    mergeShouldFail = true
    renderPanel()
    await screen.findByRole('checkbox', { name: /旧标签（3）/ })
    fireEvent.click(screen.getByRole('checkbox', { name: /旧标签（3）/ }))
    await waitFor(() => expect(screen.getByLabelText('目标标签')).not.toBeDisabled())
    fireEvent.change(screen.getByLabelText('目标标签'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: '预览合并' }))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('目标标签不能同时在源标签列表中。'),
    )
    expect(screen.queryByTestId('new211-merge-preview')).not.toBeInTheDocument()
  })

  it('切到清理台：三桶报告 + 带引用标签的删除按钮在未确认时禁用', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.includes('/tags/cleanup/report') && method === 'GET') {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              buckets: {
                unused: [{ tagId: 9, name: '无主', bindings: 0, references: { synonyms: 0, groupMemberships: 0, mergeLogs: 0 } }],
                referencedOnly: [
                  { tagId: 8, name: '仅引用', bindings: 0, references: { synonyms: 1, groupMemberships: 0, mergeLogs: 0 } },
                ],
                inUse: [],
              },
            }),
            { status: 200 },
          ),
        )
      }
      if (method === 'GET' && url.includes('/api/v1/tags')) {
        return Promise.resolve(new Response(JSON.stringify(TAGS), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
    })
    renderPanel()
    fireEvent.click(await screen.findByRole('tab', { name: '清理台' }))
    await screen.findByText('无人使用（1）')
    expect(screen.getByText('仍有关联内容（0）')).toBeInTheDocument()
    const deleteUnused = screen.getByRole('button', { name: '删除' })
    expect(deleteUnused).toBeEnabled()
    const deleteReferenced = screen.getByRole('button', { name: '确认并删' })
    expect(deleteReferenced).toBeDisabled()
  })
})
