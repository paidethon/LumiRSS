/** NEW-216 集合整理工作台入口测试 —— 快照 diff + 按选恢复主链路、排序
 * 配方 explain、引用检查失效清单。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import New216CollectionOpsPanel from '../components/new211/New216CollectionOpsPanel'

const WORKSPACES = {
  items: [{ id: 'ws-1', name: '调研集合' }],
}
const SNAPSHOTS = {
  items: [
    { id: 'snap-a', name: '初始', refCount: 2, createdAt: '2026-09-27T00:00:00+00:00' },
    { id: 'snap-b', name: '第二轮', refCount: 2, createdAt: '2026-09-28T00:00:00+00:00' },
  ],
}
const DIFF = {
  added: ['rss:e1.new'],
  removed: ['library:11111111-1111-4111-8111-111111111111'],
  addedTotal: 1,
  removedTotal: 1,
}
const RESTORE = { restored: ['library:11111111-1111-4111-8111-111111111111'], skippedExisting: 0, invalidRefs: 0 }
const RECIPES = {
  items: [
    {
      id: 'recipe-1',
      name: '标题升序',
      fields: [{ key: 'title', dir: 'asc' }],
      exceptions: [],
      explain: '按标题升序排序。',
    },
  ],
}
const CHECK = {
  checked: 4,
  issues: [{ surface: 'workspaces', locator: 'ws-1', ref: 'library:22222222-2222-4222-8222-222222222222' }],
  keptStale: [],
  truncated: false,
}

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/sort-recipes')) {
    return Promise.resolve(new Response(JSON.stringify(RECIPES), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/sort-recipes/recipe-1/preview')) {
    return Promise.resolve(
      new Response(JSON.stringify({ explain: '按标题升序排序。', ordering: [{ ref: 'rss:e1.a', position: 1, fixed: false }], memberCount: 1 }), { status: 200 }),
    )
  }
  if (method === 'GET' && url.endsWith('/api/v1/workspaces')) {
    return Promise.resolve(new Response(JSON.stringify(WORKSPACES), { status: 200 }))
  }
  if (method === 'GET' && url.includes('/member-snapshots')) {
    return Promise.resolve(new Response(JSON.stringify(SNAPSHOTS), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/member-snapshots/diff')) {
    return Promise.resolve(new Response(JSON.stringify(DIFF), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/member-snapshots/restore')) {
    return Promise.resolve(new Response(JSON.stringify(RESTORE), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/references/check')) {
    return Promise.resolve(new Response(JSON.stringify(CHECK), { status: 200 }))
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <New216CollectionOpsPanel onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)
})

describe('New216CollectionOpsPanel', () => {
  it('快照差异：选集合 → 两张快照 diff → 勾选恢复被移除成员', async () => {
    renderPanel()
    fireEvent.change(await screen.findByLabelText('选择集合'), { target: { value: 'ws-1' } })
    fireEvent.change(await screen.findByLabelText('较早快照'), { target: { value: 'snap-a' } })
    fireEvent.change(screen.getByLabelText('较晚快照'), { target: { value: 'snap-b' } })
    fireEvent.click(screen.getByRole('button', { name: '比较差异' }))
    const diff = await screen.findByTestId('new216-diff')
    expect(diff).toHaveTextContent('新增 1 篇 / 移除 1 篇')
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: '恢复所选' }))
    await waitFor(() => expect(screen.getByTestId('new216-restore-result')).toBeInTheDocument())
    expect(screen.getByTestId('new216-restore-result')).toHaveTextContent('已恢复 1 条')
  })

  it('排序配方：explain 随配方展示，可预览', async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole('tab', { name: '排序配方' }))
    fireEvent.change(await screen.findByLabelText('选择集合'), { target: { value: 'ws-1' } })
    expect(await screen.findByText('标题升序')).toBeInTheDocument()
    expect(screen.getByText('按标题升序排序。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    await waitFor(() => expect(screen.getByTestId('new217-preview')).toBeInTheDocument())
  })

  it('引用检查：失效引用清单 + 重关联入口', async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole('tab', { name: '引用检查' }))
    const list = await screen.findByTestId('new218-references')
    expect(list).toHaveTextContent('已检查 4 个引用')
    expect(list).toHaveTextContent('[workspaces] library:22222222')
    expect(screen.getByRole('button', { name: '重新关联' })).toBeDisabled()
  })
})
