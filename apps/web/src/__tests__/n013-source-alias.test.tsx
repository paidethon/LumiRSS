/** N013 UI — 来源改名（服务端别名 + 历史 + 恢复）。
 *
 * - 保存 → PUT /api/v1/sources/alias { feedUrl, customName }；
 * - 历史列表渲染（旧名 + 上游当时名），「恢复」= 用旧名重新 PUT；
 * - 展示解析：resolveDisplayTitle 服务端别名（feedUrl 键）赢，
 *   localStorage（feedTitle 键）只是离线回退。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SourceAliasDialog from '../components/SourceAliasDialog'
import { resolveDisplayTitle } from '../lib/source-aliases'

const FEED_URL = 'https://feed.example/rss'

const ALIAS = { feedUrl: FEED_URL, customName: '当前别名', updatedAt: '2026-09-22T00:00:00Z' }

const HISTORY = {
  items: [
    {
      id: 2,
      feedUrl: FEED_URL,
      oldCustomName: '旧名二',
      upstreamNameAtSave: '上游 v2',
      changedAt: '2026-09-22T00:00:00Z',
    },
    {
      id: 1,
      feedUrl: FEED_URL,
      oldCustomName: null,
      upstreamNameAtSave: '上游 v1',
      changedAt: '2026-09-21T00:00:00Z',
    },
  ],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderDialog(routes: Record<string, () => Response>) {
  const calls: { method: string; url: string; body?: unknown }[] = []
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    let body: unknown
    try {
      body = init?.body !== undefined ? JSON.parse(String(init.body)) : undefined
    } catch {
      body = undefined
    }
    calls.push({ method, url, body })
    const handler = routes[`${method} ${url}`]
    if (handler === undefined) return Promise.resolve(jsonResponse({}))
    return Promise.resolve(handler())
  })
  vi.stubGlobal('fetch', fn)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <SourceAliasDialog open onClose={() => {}} feedUrl={FEED_URL} title="示例源" />
    </QueryClientProvider>,
  )
  return { calls }
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('N013 来源改名对话框', () => {
  it('保存 → PUT 载荷携带 feedUrl + customName；成功后状态可见', async () => {
    const { calls } = renderDialog({
      'GET /api/v1/sources/aliases': () => jsonResponse({ items: [ALIAS] }),
      [`GET /api/v1/sources/alias/history?feedUrl=${encodeURIComponent(FEED_URL)}&limit=20`]: () => jsonResponse({ items: [] }),
      'PUT /api/v1/sources/alias': () => jsonResponse(ALIAS),
    })
    await screen.findByText('当前别名：当前别名')
    fireEvent.change(screen.getByRole('textbox', { name: '新的别名' }), {
      target: { value: '更好认的名字' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT')
      expect(put?.body).toEqual({ feedUrl: FEED_URL, customName: '更好认的名字' })
    })
  })

  it('历史渲染（旧名 + 上游快照），恢复 = 用旧名重新 PUT', async () => {
    const { calls } = renderDialog({
      'GET /api/v1/sources/aliases': () => jsonResponse({ items: [ALIAS] }),
      [`GET /api/v1/sources/alias/history?feedUrl=${encodeURIComponent(FEED_URL)}&limit=20`]: () => jsonResponse(HISTORY),
      'PUT /api/v1/sources/alias': () => jsonResponse(ALIAS),
    })
    const history = await screen.findByTestId('alias-history')
    expect(history.textContent).toContain('旧名二')
    expect(history.textContent).toContain('上游 v2')
    expect(history.textContent).toContain('（首设别名）')
    // 首设别名行没有可恢复的名字 → 只有一个恢复按钮
    fireEvent.click(screen.getByRole('button', { name: '恢复「旧名二」' }))
    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT')
      expect(put?.body).toEqual({ feedUrl: FEED_URL, customName: '旧名二' })
    })
  })

  it('当前别名来自服务端（未设置时诚实显示）', async () => {
    renderDialog({
      'GET /api/v1/sources/aliases': () => jsonResponse({ items: [] }),
      [`GET /api/v1/sources/alias/history?feedUrl=${encodeURIComponent(FEED_URL)}&limit=20`]: () => jsonResponse({ items: [] }),
    })
    expect(await screen.findByText('当前别名：未设置')).toBeInTheDocument()
  })
})

describe('N013 展示名解析（服务端赢，本地回退）', () => {
  it('服务端别名优先于本地别名与上游标题', () => {
    const server = new Map([[FEED_URL, '服务端名']])
    localStorage.setItem('lumirss-source-aliases', JSON.stringify({ 示例源: '本地名' }))
    expect(resolveDisplayTitle(FEED_URL, '示例源', server)).toBe('服务端名')
    // 服务端未覆盖该 feed → 本地别名回退
    expect(resolveDisplayTitle(FEED_URL, '示例源', new Map())).toBe('本地名')
    // 都没有 → 上游标题（先清掉本地别名）
    localStorage.clear()
    expect(resolveDisplayTitle(FEED_URL, '示例源', undefined)).toBe('示例源')
    // 无 feedUrl（来源页缺失态）→ 只走本地（重建本地别名）
    localStorage.setItem('lumirss-source-aliases', JSON.stringify({ 示例源: '本地名' }))
    expect(resolveDisplayTitle(null, '示例源', server)).toBe('本地名')
  })
})
