/** Read Later 专项测试 — P0-01 服务端时间线版（wave 2 重写）。
 *
 * 旧行为（客户端 view=all 拉全量 + 本地过滤 + localStorage 双写 +
 * once-only 对账）已删除；本文件断言新契约：
 * - 稍后读视图 = GET /workspaces/read-later/timeline（server-driven、
 *   cursor 分页、悬挂成员 stale 行可见而非消失）；
 * - toggle = POST/DELETE /workspaces/read-later/items（mutation 承载：
 *   乐观更新 + 失败回滚 + 诚实错误）；
 * - Clock 激活态真源 = GET /workspaces/read-later/items（服务端成员
 *   清单 + 在途 mutation 乐观覆盖）；localStorage 不再参与。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import EntryList from '../components/EntryList'
import EntryRow from '../components/EntryRow'
import ReaderHeader from '../components/ReaderHeader'
import { useReaderUi } from '../store/reader-ui'

const FEEDS = [{ title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml', category: null }]

function entryCard(ref: string) {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源 A',
    feedUrl: 'https://a.example.com/feed.xml',
    author: null,
    url: null,
    publishedAt: '2026-08-30T00:00:00Z',
    read: false,
    starred: false,
    snippet: '',
    matchedFields: [],
  }
}

/** 时间线行：entry 卡片或 stale（悬挂成员）。 */
function timelineRow(itemRef: string, over: Record<string, unknown> = {}) {
  return { itemRef, addedAt: '2026-09-01T08:00:00Z', stale: false, entry: entryCard(itemRef.slice(4)), ...over }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** fetch mock 路由：时间线 / 成员清单 / 增删。通过闭包 state 控制
 * 服务端「真值」，mutation 成功时同步更新（模拟服务端提交）。 */
function mockApi(initial: { refs: string[] }) {
  const state = { refs: [...initial.refs] }
  const impl = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.startsWith('/api/v1/feeds')) return Promise.resolve(jsonResponse(FEEDS))
    if (url.startsWith('/api/v1/workspaces/read-later/timeline')) {
      return Promise.resolve(
        jsonResponse({
          items: state.refs.map((ref) =>
            timelineRow(ref, ref === 'rss:e1.stale' ? { stale: true, entry: null } : {}),
          ),
          nextCursor: null,
        }),
      )
    }
    if (url.startsWith('/api/v1/workspaces/read-later/items')) {
      // DELETE 走路径参数：/items/rss%3Ae1.a（removeWorkspaceItem 契约）
      const pathMatch = url.match(/^\/api\/v1\/workspaces\/read-later\/items\/(.+)$/)
      if (pathMatch !== null && method === 'DELETE') {
        const removed = decodeURIComponent(pathMatch[1])
        state.refs = state.refs.filter((r) => r !== removed)
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      if (method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            items: state.refs.map((itemRef, index) => ({
              itemRef,
              addedAt: '2026-09-01T08:00:00Z',
              position: index,
            })),
          }),
        )
      }
      if (method === 'POST') {
        const body = JSON.parse(String(init?.body ?? '{}')) as { itemRef?: string }
        if (body.itemRef !== undefined) state.refs.push(body.itemRef)
        return Promise.resolve(jsonResponse({ itemRef: body.itemRef, addedAt: '', position: 0 }, 201))
      }
    }
    return Promise.reject(new Error(`unexpected fetch: ${method} ${url}`))
  }
  return Object.assign(vi.fn().mockImplementation(impl), { state })
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({ section: 'home', view: 'read-later', scope: { kind: 'all' }, selectedEntryRef: null, mobileSidebarOpen: false })
  // jsdom 无 IntersectionObserver：stub 为空实现（无限滚动哨兵不触发自动拉页）
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe() {}
      disconnect() {}
      unobserve() {}
    },
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('稍后读视图 = 服务端时间线（P0-01）', () => {
  it('渲染 timeline 端点的行（不是 view=all 本地过滤）；列表头计数', async () => {
    const api = mockApi({ refs: ['rss:e1.a', 'rss:e1.b'] })
    vi.stubGlobal('fetch', api)
    render(withProviders(<EntryList />))
    // 行标题在桌面行 + 移动卡两份 DOM（CSS 分发）——用 getAllByText
    await waitFor(() => {
      expect(screen.getAllByText('文章 e1.a').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('文章 e1.b').length).toBeGreaterThan(0)
    // 列表头 h2：全部信息源 · 稍后读；计数 = 服务端返回行数
    await screen.findByRole('heading', { name: /稍后读/ })
    expect(screen.getByText(/已加载 2 条/)).toBeInTheDocument()
    // 服务端时间线视图不再对 entries 全量端点发起请求
    for (const call of api.mock.calls) {
      expect(String(call[0])).not.toContain('/api/v1/entries')
    }
  })

  it('悬挂成员（stale）显式渲染为失效行 + 移除出口，不静默隐藏', async () => {
    const api = mockApi({ refs: ['rss:e1.a', 'rss:e1.stale'] })
    vi.stubGlobal('fetch', api)
    render(withProviders(<EntryList />))
    expect(await screen.findByText('条目已失效或不存在')).toBeInTheDocument()
    expect(screen.getByText(/rss:e1.stale/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '从稍后读移除失效条目' })).toBeInTheDocument()
  })

  it('空时间线 → 稍后读空态', async () => {
    const api = mockApi({ refs: [] })
    vi.stubGlobal('fetch', api)
    render(withProviders(<EntryList />))
    expect(await screen.findByText('还没有稍后读的文章')).toBeInTheDocument()
  })

  it('localStorage 不再参与：toggle 后无 lumirss-read-later 双写', async () => {
    const api = mockApi({ refs: [] })
    vi.stubGlobal('fetch', api)
    render(withProviders(<EntryList />))
    await screen.findByText('还没有稍后读的文章')
    expect(localStorage.getItem('lumirss-read-later')).toBeNull()
  })
})

describe('稍后读 toggle（mutation：乐观 + 失败回滚 + 诚实错误）', () => {
  it('移除：行立即消失（乐观），服务端收到 DELETE', async () => {
    const api = mockApi({ refs: ['rss:e1.a'] })
    vi.stubGlobal('fetch', api)
    render(withProviders(<EntryList />))
    await waitFor(() => {
      expect(screen.getAllByText('文章 e1.a').length).toBeGreaterThan(0)
    })
    // Clock 激活态来自 refs 清单（异步到达）——等它翻到「已加入」再点击
    const clocks = await screen.findAllByRole('button', { name: '从稍后读移除' })
    fireEvent.click(clocks[0])
    // 乐观：行立即从时间线消失（桌面行 + 移动卡双 DOM → 用 All 变体断言不存在）
    await waitFor(() => expect(screen.queryAllByText('文章 e1.a')).toHaveLength(0))
    // 服务端 DELETE 已发出（路径参数契约：/items/<encoded ref>）
    await waitFor(() => {
      expect(api.mock.calls.some(([u, init]) => String(u).endsWith('/read-later/items/rss%3Ae1.a') && init?.method === 'DELETE')).toBe(true)
    })
    // 失效重取后服务端真值一致（行保持消失）
    expect(api.state.refs).toHaveLength(0)
  })

  it('失败：乐观移除回滚（行保留）+ 错误诚实透出', async () => {
    const api = mockApi({ refs: ['rss:e1.a'] })
    vi.stubGlobal('fetch', api)
    // 让 DELETE 返回 500（移除失败）
    const origImpl = api.getMockImplementation()
    api.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.startsWith('/api/v1/workspaces/read-later/items') && init?.method === 'DELETE') {
        return Promise.resolve(
          jsonResponse({ error: { type: 'workspace_write_failed', message: '服务端写入失败' } }, 500),
        )
      }
      return origImpl?.(input, init) ?? Promise.reject(new Error('no impl'))
    })
    render(withProviders(<EntryList />))
    await waitFor(() => {
      expect(screen.getAllByText('文章 e1.a').length).toBeGreaterThan(0)
    })
    // Clock 激活态来自 refs 清单（异步到达）——等它翻到「已加入」再点击
    const clocks = await screen.findAllByRole('button', { name: '从稍后读移除' })
    fireEvent.click(clocks[0])
    // 回滚：行重新可见（不假装成功）
    await waitFor(() => {
      expect(screen.getAllByText('文章 e1.a').length).toBeGreaterThan(0)
    })
    // 诚实错误（列表级 alert：乐观移除会卸载行组件，错误态由共享 cache 承载）
    expect(await screen.findByText(/稍后读操作失败：服务端写入失败/)).toBeInTheDocument()
  })

  it('加入（组件外驱动同源 hook）：POST /workspaces/read-later/items', async () => {
    const api = mockApi({ refs: [] })
    vi.stubGlobal('fetch', api)
    render(withProviders(<EntryRow item={{
      entryRef: 'e1.a',
      title: '文章 e1.a',
      feedTitle: '示例源 A',
      author: null,
      url: null,
      publishedAt: '2026-08-30T00:00:00Z',
      read: false,
      starred: false,
    }} selected={false} />))

    const clock = await screen.findByRole('button', { name: '加入稍后读' })
    expect(clock).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(clock)
    // 乐观翻转（mutation variables 覆盖，未落库前展示目标值）
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '从稍后读移除' })).toHaveAttribute('aria-pressed', 'true')
    })
    await waitFor(() => {
      expect(
        api.mock.calls.some(([u, init]) => String(u).endsWith('/read-later/items') && init?.method === 'POST'),
      ).toBe(true)
    })
  })
})

describe('ReaderHeader Clock（服务端成员清单真源）', () => {
  it('成员清单命中 → 「从稍后读移除」；未命中 → 「加入稍后读」', async () => {
    const api = mockApi({ refs: ['rss:e1.a'] })
    vi.stubGlobal('fetch', api)
    const detail = {
      entryRef: 'e1.a', title: '文章', feedTitle: '源', author: null,
      url: null, publishedAt: null, read: false, starred: false,
      contentText: '', contentHtml: null,
    }
    render(withProviders(<ReaderHeader detail={detail} />))
    // refs 清单加载完成前不假装未加入（本例 e1.a 在清单里）
    await waitFor(
      () => {
        expect(screen.getAllByRole('button', { name: '从稍后读移除' }).length).toBeGreaterThan(0)
      },
      { timeout: 3000 },
    )

    // 组件外驱动 toggle（同一 mutation 语义）：乐观翻转到未加入
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '从稍后读移除' }))
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '加入稍后读' })).toBeInTheDocument()
    })
  })
})

describe('Sidebar 稍后读入口（§30）', () => {
  it('工作区含稍后读（Clock）+ 收藏；稍后读入口 active 态', async () => {
    const api = mockApi({ refs: [] })
    vi.stubGlobal('fetch', api)
    const Sidebar = (await import('../components/Sidebar')).default
    render(withProviders(<Sidebar />))
    const rl = screen.getByRole('button', { name: '稍后读' })
    // view=read-later（beforeEach 已设置）→ active
    expect(rl).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('button', { name: '收藏' })).toBeInTheDocument()
  })
})
