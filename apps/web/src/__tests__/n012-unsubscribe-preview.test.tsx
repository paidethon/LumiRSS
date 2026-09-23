/** N012 UI — 退订对话框的影响预览 + 确认门 + keep_artifacts 选择。
 *
 * - 预览到达前最终确认按钮禁用（确认前必见影响）；
 * - 预览渲染影响清单（工作区引用/批注/未读…计数 + 样本）；
 * - 默认保留工件（?keep_artifacts=true）；取消勾选 → false（显式清理）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UnsubscribeDialog from '../components/UnsubscribeDialog'

const REF = 's1.ZmVlZC80Mg'

const SUBSCRIPTION = {
  subscriptionRef: REF,
  title: '示例源',
  feedUrl: 'https://feed.example/rss',
  category: null,
}

const PREVIEW = {
  subscriptionRef: REF,
  feedUrl: 'https://feed.example/rss',
  title: '示例源',
  projectionEntries: 12,
  unreadCount: 5,
  workspaceItems: {
    count: 2,
    items: [{ workspaceId: 'ws1', workspaceName: '研究计划', itemRef: 'rss:e1.x' }],
  },
  boardItems: { count: 1, items: [{ workspaceId: 'ws1', itemRef: 'rss:e1.x', status: 'reading' }] },
  libraryItems: { count: 1, items: [{ itemRef: 'library:u1', rssItemRef: 'rss:e1.x', title: '书签' }] },
  annotations: {
    count: 3,
    items: [{ id: 'a1', entryRef: 'e1.x', excerpt: '关键论点' }],
  },
  inboxRules: {
    count: 1,
    items: [{ id: 1, field: 'source', operator: 'contains', value: '示例', matchedSample: 'title' }],
  },
  sampleLimit: 50,
  note: '预览为只读快照',
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderDialog(routes: Record<string, () => Response>) {
  const calls: { method: string; url: string }[] = []
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    calls.push({ method, url })
    const handler = routes[`${method} ${url}`]
    if (handler === undefined) return Promise.resolve(jsonResponse({}))
    return Promise.resolve(handler())
  })
  vi.stubGlobal('fetch', fn)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <UnsubscribeDialog open onClose={() => {}} subscription={SUBSCRIPTION} />
    </QueryClientProvider>,
  )
  return { calls }
}

const previewRoute = {
  [`GET /api/v1/subscriptions/${REF}/unsubscribe-preview`]: () => jsonResponse(PREVIEW),
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('N012 退订影响预览对话框', () => {
  it('预览渲染影响清单（计数 + 样本），确认门在预览到达前禁用', async () => {
    const { calls } = renderDialog(previewRoute)
    // 影响清单可见
    const impact = await screen.findByTestId('unsubscribe-impact')
    expect(impact.textContent).toContain('工作区引用')
    expect(impact.textContent).toContain('研究计划')
    expect(impact.textContent).toContain('关键论点')
    expect(impact.textContent).toContain('5')
    // 进入最终确认：预览已到达 → 确认按钮可用
    fireEvent.click(screen.getByRole('button', { name: '取消订阅' }))
    const confirm = await screen.findByRole('button', { name: '确认取消订阅' })
    await waitFor(() => expect(confirm).not.toBeDisabled())
    // 预览请求先于任何删除（只读在先）
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  })

  it('默认保留工件 → DELETE ?keep_artifacts=true', async () => {
    const { calls } = renderDialog(previewRoute)
    await screen.findByTestId('unsubscribe-impact')
    fireEvent.click(screen.getByRole('button', { name: '取消订阅' }))
    const confirm = await screen.findByRole('button', { name: '确认取消订阅' })
    await waitFor(() => expect(confirm).not.toBeDisabled())
    fireEvent.click(confirm)
    await waitFor(() => {
      expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('keep_artifacts=true'))).toBe(true)
    })
  })

  it('取消勾选（显式清理）→ DELETE ?keep_artifacts=false', async () => {
    const { calls } = renderDialog(previewRoute)
    await screen.findByTestId('unsubscribe-impact')
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: '取消订阅' }))
    const confirm = await screen.findByRole('button', { name: '确认取消订阅' })
    await waitFor(() => expect(confirm).not.toBeDisabled())
    fireEvent.click(confirm)
    await waitFor(() => {
      expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('keep_artifacts=false'))).toBe(true)
    })
  })

  it('预览未到达时确认按钮禁用（确认门）', async () => {
    // 预览一直 pending（无路由 → 走 jsonResponse({})？改为永不 resolve）
    let resolvePreview: ((response: Response) => void) | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        if (String(input).endsWith('/unsubscribe-preview')) {
          return new Promise<Response>((resolve) => {
            resolvePreview = resolve
          })
        }
        return Promise.resolve(jsonResponse({}))
      }),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <UnsubscribeDialog open onClose={() => {}} subscription={SUBSCRIPTION} />
      </QueryClientProvider>,
    )
    fireEvent.click(await screen.findByRole('button', { name: '取消订阅' }))
    const confirm = screen.getByRole('button', { name: '确认取消订阅' })
    expect(confirm).toBeDisabled()
    // 预览到达 → 门打开
    resolvePreview?.(jsonResponse(PREVIEW))
    await waitFor(() => expect(confirm).not.toBeDisabled())
  })
})
