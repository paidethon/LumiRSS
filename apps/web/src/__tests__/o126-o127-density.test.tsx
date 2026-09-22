/** O126/O127 — 信息密度与视觉层级改造（内容优先收纳）行为证明。
 *
 * O127 ReaderHeader（jsdom 无 matchMedia → useIsMobile 视为移动端）：
 * - 高频动作留在工具栏：已读 / 稍后读 / 星标 / 打开原文 / 更多操作；
 * - 低频动作（查找 / 链接 / AI / 快照 / 分享 / 复制引用 / 打印）以
 *   menuitem 形式收进既有「更多操作」菜单——可达性不降级，aria 语义
 *   与动作接线一致（打印 → window.print；复制引用 → 剪贴板；快照 →
 *   createSnapshot）；
 * - 朗读能力缺失 → 菜单不出「朗读」项（不假装可派发）；能力可用 →
 *   菜单项触发与桌面按钮同一状态机。
 * - 桌面工具栏按钮仍在 DOM（真实浏览器 <lg 由 max-lg:hidden 隐藏），
 *   断言其位于折叠组容器内（语义近似，同 mobile-reader 约定）。
 *
 * O126 EntryActionButtons card 变体（移动卡片）：
 * - 高频 Clock/Star/Tags 按钮留卡上（44px 触控，aria 不变）；
 * - 存书签/翻译标题/添加到工作区不再是行内空图标，收进「更多操作」
 *   菜单（菜单按钮 44px），选择触发与旧按钮相同的 mutation；
 * - 已在稍后读 → 菜单出现「延后 7 天」。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ReaderHeader from '../components/ReaderHeader'
import { EntryActionButtons } from '../components/EntryActionButtons'
import type { EntryDetail } from '../api/types'

function detailFixture(over: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: null,
    url: 'https://example.com/a',
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '正文',
    contentHtml: '<p>正文</p>',
    ...over,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function stubNavigatorMember(name: string, value: unknown): void {
  Object.defineProperty(window.navigator, name, { value, configurable: true })
}

function deleteNavigatorMember(name: string): void {
  const nav = window.navigator as unknown as Record<string, unknown>
  delete nav[name]
}

afterEach(() => {
  vi.unstubAllGlobals()
  deleteNavigatorMember('share')
  deleteNavigatorMember('clipboard')
})

// ---- O127 ReaderHeader ----

describe('O127 — ReaderHeader 移动端收纳（更多操作菜单）', () => {
  const allCallbacks = {
    onOpenAiConversation: () => {},
    onOpenFind: () => {},
    onOpenLinks: () => {},
    collectSpeechText: () => '第一段正文',
    onAutoScrollToggle: () => {},
  }

  it('高频动作留在工具栏；桌面低频按钮位于 <lg 折叠组（内容优先）', () => {
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))
    // 高频：直接可达
    expect(screen.getByRole('button', { name: '标记为已读' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '加入稍后读' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收藏' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '打开原文' })).toBeInTheDocument()
    // 低频（桌面残留按钮）确实包在 max-lg:hidden 折叠组里（移动端隐藏）
    expect(
      screen.getByRole('button', { name: '打印' }).closest('[class*="max-lg:hidden"]'),
    ).not.toBeNull()
    expect(
      screen.getByRole('button', { name: '保存快照' }).closest('[class*="max-lg:hidden"]'),
    ).not.toBeNull()
  })

  it('更多操作菜单收纳低频动作：查找/链接/AI/快照/分享/引用/打印/滚屏/导出', async () => {
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    const menu = await screen.findByRole('menu')
    for (const name of [
      '文内查找',
      '文中链接',
      'AI 对话',
      '保存快照',
      '复制链接', // jsdom 无 navigator.share → 诚实降级标签
      '复制为纯文本',
      '复制为 Markdown',
      '打印',
      '自动滚屏',
      '导出 Markdown',
      '导出 HTML',
    ]) {
      expect(within(menu).getByRole('menuitem', { name })).toBeInTheDocument()
    }
    // 朗读能力缺失 → 菜单不出「朗读」（与桌面禁用按钮同一诚实语义）
    expect(within(menu).queryByRole('menuitem', { name: '朗读' })).toBeNull()
  })

  it('菜单「打印」→ window.print()；菜单「复制为纯文本」→ 剪贴板引用文本', async () => {
    const printMock = vi.fn()
    vi.stubGlobal('print', printMock)
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigatorMember('clipboard', { writeText })
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => '引文内容',
    } as Selection)
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '打印' }))
    expect(printMock).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制为纯文本' }))
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        '文章 A\n示例源\nhttps://example.com/a\n\n引文内容',
      )
    })
  })

  it('菜单「复制链接」（无 share 能力）→ 剪贴板写入 + 「链接已复制」反馈', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigatorMember('clipboard', { writeText })
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制链接' }))
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('https://example.com/a')
    })
    expect(await screen.findByText('链接已复制')).toBeInTheDocument()
  })

  it('菜单「保存快照」→ createSnapshot({url})（与桌面按钮同一 mutation）', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.includes('/api/v1/library/snapshots') && method === 'POST') {
        return Promise.resolve(
          jsonResponse({
            ref: 'snap-1',
            url: 'https://example.com/a',
            status: 'ready',
            createdAt: '2026-09-01T08:00:00Z',
          }),
        )
      }
      if (url.includes('/api/v1/workspaces/read-later/items')) {
        return Promise.resolve(jsonResponse({ items: [] }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '保存快照' }))
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([u, init]) =>
          String(u).includes('/api/v1/library/snapshots') && init?.method === 'POST',
      )
      expect(post).toBeDefined()
      expect(JSON.parse(String(post![1]?.body))).toEqual({ url: 'https://example.com/a' })
    })
  })
})

// ---- O126 EntryActionButtons card 变体 ----

const WS = {
  id: 'ws-1',
  name: '周报',
  position: 0,
  itemCount: 0,
  archived: false,
  reserved: false,
  description: '',
}

function cardApiHarness(opts: { readLater?: boolean } = {}) {
  const bookmarkCalls: Record<string, unknown>[] = []
  const workspaceItemCalls: { url: string; body: Record<string, unknown> }[] = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.startsWith('/api/v1/library/bookmarks') && method === 'POST') {
      bookmarkCalls.push(JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>)
      return Promise.resolve(
        jsonResponse({ ref: 'library:b1', kind: 'bookmark', title: '文章 A', url: null, snippet: '', updatedAt: '2026-09-01T08:00:00Z' }),
      )
    }
    if (url.startsWith('/api/v1/library/bookmarks')) return Promise.resolve(jsonResponse({ items: [] }))
    if (url.startsWith('/api/v1/workspaces/read-later/items')) {
      return Promise.resolve(
        jsonResponse({
          items: opts.readLater
            ? [{ itemRef: 'rss:e1.a', addedAt: '2026-09-01T08:00:00Z', position: 0 }]
            : [],
        }),
      )
    }
    if (/\/api\/v1\/workspaces\/[^/]+\/items$/.test(url) && method === 'POST') {
      workspaceItemCalls.push({ url, body: JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown> })
      return Promise.resolve(jsonResponse({}))
    }
    if (url.startsWith('/api/v1/workspaces')) return Promise.resolve(jsonResponse({ items: [WS] }))
    if (url.includes('/api/v1/tags/item')) return Promise.resolve(jsonResponse({ items: [] }))
    if (url.startsWith('/api/v1/tags')) return Promise.resolve(jsonResponse({ items: [] }))
    return Promise.resolve(jsonResponse({}))
  })
  return { fetchMock, bookmarkCalls, workspaceItemCalls }
}

describe('O126 — EntryActionButtons card 变体（移动卡片收纳）', () => {
  it('高频 Clock/Star/Tags 留卡上（aria 不变）；存书签/翻译/工作区不再是无空图标按钮', () => {
    const { fetchMock } = cardApiHarness()
    vi.stubGlobal('fetch', fetchMock)
    render(
      withProviders(<EntryActionButtons entryRef="e1.a" starred={false} title="文章 A" variant="card" />),
    )
    expect(screen.getByRole('button', { name: '加入稍后读' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收藏' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '标签' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '存书签' })).toBeNull()
    expect(screen.queryByRole('button', { name: '翻译标题' })).toBeNull()
    expect(screen.queryByRole('button', { name: '添加到工作区' })).toBeNull()
  })

  it('更多操作菜单：存书签/翻译标题/工作区可达（禁用组头 + 扁平工作区项）；选择存书签 → 幂等 POST', async () => {
    const { fetchMock, bookmarkCalls } = cardApiHarness()
    vi.stubGlobal('fetch', fetchMock)
    render(
      withProviders(<EntryActionButtons entryRef="e1.a" starred={false} title="文章 A" variant="card" />),
    )

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    expect(await screen.findByRole('menuitem', { name: '存书签' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '翻译标题' })).toBeInTheDocument()
    // 「添加到工作区」是禁用组头；工作区本体可直接选择（扁平化，无二级菜单）
    // （Base UI 禁用项用 aria-disabled/data-disabled，非 HTML disabled）
    expect(screen.getByRole('menuitem', { name: '添加到工作区' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(await screen.findByRole('menuitem', { name: '周报' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('menuitem', { name: '存书签' }))
    await waitFor(() => {
      expect(bookmarkCalls).toEqual([{ rssItemRef: 'rss:e1.a', title: '文章 A' }])
    })
  })

  it('选择工作区菜单项 → addWorkspaceItem（POST，POST 幂等可重加）', async () => {
    const { fetchMock, workspaceItemCalls } = cardApiHarness()
    vi.stubGlobal('fetch', fetchMock)
    render(
      withProviders(<EntryActionButtons entryRef="e1.a" starred={false} title="文章 A" variant="card" />),
    )

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '周报' }))
    await waitFor(() => {
      expect(workspaceItemCalls).toEqual([
        { url: '/api/v1/workspaces/ws-1/items', body: { itemRef: 'rss:e1.a' } },
      ])
    })
  })

  it('已在稍后读 → Clock 激活态 + 菜单出现「延后 7 天」；收藏激活态 aria 不变', async () => {
    const { fetchMock } = cardApiHarness({ readLater: true })
    vi.stubGlobal('fetch', fetchMock)
    render(
      withProviders(<EntryActionButtons entryRef="e1.a" starred={true} title="文章 A" variant="card" />),
    )
    // 服务端成员清单命中 → Clock 激活；starred → Star 激活（aria 不变）
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '从稍后读移除' })).toHaveAttribute('aria-pressed', 'true')
    })
    expect(screen.getByRole('button', { name: '取消收藏' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    expect(
      await screen.findByRole('menuitem', { name: '延后 7 天（到期自动回来）' }),
    ).toBeInTheDocument()
  })
})
