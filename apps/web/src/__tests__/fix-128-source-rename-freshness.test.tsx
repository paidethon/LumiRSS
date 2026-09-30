/** FIX-128 — 来源名称更新后，展示链路不得停留在旧名称。
 *
 * 守卫（复核结论 BASELINE_OK：现有实现已满足——本测试钉住该行为）：
 * 服务端别名保存/清除 → useSetSourceAliasMutation / useDeleteSourceAliasMutation
 * 精确失效 ['source-aliases'] → 所有共享该查询的展示消费方
 * （SourceLabel / 订阅页 / 对话框）同一次提交内拿到新值——改名后任何
 * 位置都不允许残留旧别名。分类结构变化（移动/改名/退订）走
 * invalidateSubscriptionState（feeds/categories/subscriptions/entries
 * 一起失效），与别名展示链路无关，由 rss-scope 等既有套件覆盖。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SourceAliasDialog from '../components/SourceAliasDialog'
import { SourceLabel } from '../lib/source-meta'

const FEED_URL = 'https://feed.example/rss'
const UPSTREAM_TITLE = '上游标题'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function aliasBody(customName: string) {
  return { feedUrl: FEED_URL, customName, updatedAt: '2026-09-22T00:00:00Z' }
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('FIX-128 来源改名后的展示新鲜度', () => {
  it('保存新别名 → 别名查询被重新拉取，SourceLabel 立即显示新名称', async () => {
    let currentAlias = aliasBody('旧名称')
    let aliasGetCount = 0
    let putBody: unknown = null
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (method === 'GET' && url.endsWith('/api/v1/sources/aliases')) {
          aliasGetCount += 1
          return Promise.resolve(
            jsonResponse(currentAlias.customName === '' ? { items: [] } : { items: [currentAlias] }),
          )
        }
        if (method === 'PUT' && url.endsWith('/api/v1/sources/alias')) {
          putBody = JSON.parse(String(init?.body))
          currentAlias = aliasBody((putBody as { customName: string }).customName)
          return Promise.resolve(jsonResponse(currentAlias))
        }
        if (method === 'GET' && url.includes('/api/v1/sources/alias/history')) {
          return Promise.resolve(jsonResponse({ items: [] }))
        }
        return Promise.resolve(jsonResponse({}))
      }),
    )

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <div data-testid="display">
          <SourceLabel feedTitle={UPSTREAM_TITLE} feedUrl={FEED_URL} />
        </div>
        <SourceAliasDialog open onClose={() => {}} feedUrl={FEED_URL} title={UPSTREAM_TITLE} />
      </QueryClientProvider>,
    )

    // 初始：展示链路显示当前别名（服务端赢）
    expect(await screen.findByText('当前别名：旧名称')).toBeInTheDocument()
    expect(screen.getAllByText('旧名称').length).toBeGreaterThan(0)

    fireEvent.change(screen.getByRole('textbox', { name: '新的别名' }), {
      target: { value: '新名称' },
    })
    const getsBeforeSave = aliasGetCount
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    // PUT 载荷 = { feedUrl, customName }（服务端真源语义）
    await waitFor(() => {
      expect(putBody).toEqual({ feedUrl: FEED_URL, customName: '新名称' })
    })
    // 失效生效：别名查询被重新拉取
    await waitFor(() => {
      expect(aliasGetCount).toBeGreaterThan(getsBeforeSave)
    })
    // 展示链路（与对话框共享同一查询缓存）同步换成新名称——
    // 「旧名称」不允许残留在任何展示位置。
    await waitFor(() => {
      expect(screen.queryByText('旧名称')).toBeNull()
    })
    expect(screen.getAllByText('新名称').length).toBeGreaterThan(0)
  })

  it('清除别名 → SourceLabel 回退上游标题，不残留旧别名', async () => {
    let currentAlias = aliasBody('旧名称')
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (method === 'GET' && url.endsWith('/api/v1/sources/aliases')) {
          return Promise.resolve(
            jsonResponse(currentAlias.customName === '' ? { items: [] } : { items: [currentAlias] }),
          )
        }
        if (method === 'DELETE' && url.includes('/api/v1/sources/alias?')) {
          currentAlias = aliasBody('')
          return Promise.resolve(new Response(null, { status: 204 }))
        }
        if (method === 'GET' && url.includes('/api/v1/sources/alias/history')) {
          return Promise.resolve(jsonResponse({ items: [] }))
        }
        return Promise.resolve(jsonResponse({}))
      }),
    )

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <SourceLabel feedTitle={UPSTREAM_TITLE} feedUrl={FEED_URL} />
        <SourceAliasDialog open onClose={() => {}} feedUrl={FEED_URL} title={UPSTREAM_TITLE} />
      </QueryClientProvider>,
    )

    expect(await screen.findByText('当前别名：旧名称')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '清除' }))

    await waitFor(() => {
      expect(screen.queryByText('旧名称')).toBeNull()
    })
    // 回退上游真实名（FreshRSS truth 永不被别名机制修改）
    expect(screen.getAllByText(UPSTREAM_TITLE).length).toBeGreaterThan(0)
  })
})
