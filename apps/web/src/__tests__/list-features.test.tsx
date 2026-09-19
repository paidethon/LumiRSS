/** 2026-09 批次 — 列表功能（F05 分组 / F06 排序 / F07 多选 / F09 下拉刷新）
 * 与订阅置顶（F26）。
 *
 * 行为证明（不只「不抛错」）：
 * - F05：listGroupByFeed=true 时按 feedTitle 分组（首次出现顺序）、组头
 *   「已加载 n 条」是已加载口径、组头可折叠（会话内）、「只看此来源」
 *   有 feedUrl 才可用（无 feedUrl 禁用）；分页追加条目按来源正确归组
 *   （groupEntriesByFeed 纯函数）；
 * - F06：排序按钮 aria-pressed 与 settings.timelineOrder 双向同步；
 *   oldest 时客户端 reverse + 诚实标注（服务端分页仍为最新优先）；
 * - F07：进入/退出多选、勾选（点行与复选框）、批量已读逐条 PATCH、
 *   部分失败列出失败 ref 且「重试失败项」只重发失败项、超 100 上限禁用；
 * - F09：下拉达阈值释放触发 refetch 一次（刷新列表数据，不触发上游
 *   抓取）、未达阈值不触发、失败保留列表；
 * - F26：置顶/取消置顶、上移/下移（边界 disabled）、localStorage 持久。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EntryList, { groupEntriesByFeed } from '../components/EntryList'
import SubscriptionsPage, {
  PINNED_FEEDS_LIMIT,
  movePinnedFeed,
  readPinnedFeeds,
  togglePinnedFeed,
} from '../components/pages/SubscriptionsPage'
import { useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'
import type { EntryListItem } from '../api/types'

// 本文件聚焦 EntryList 的列表级行为（分组/排序/多选/刷新），不测卡片
// 内部——用轻量 stub 替代真实 EntryCard/EntryRow（每行真实卡片含菜单/
// 手势/hooks，101 行渲染在 CI 2 核 runner 上会拖垮超时）。stub 保留
// 本文件依赖的契约：标题/来源文本、selectMode 复选框、点行切换选中。
vi.mock('../components/EntryCard', () => ({
  default: function StubCard(props: {
    item: EntryListItem
    selected?: boolean
    selectMode?: boolean
    checked?: boolean
    onToggleSelect?: (entryRef: string) => void
  }) {
    const { item, selected, selectMode, checked, onToggleSelect } = props
    return (
      <div
        data-testid="stub-card"
        data-entry-ref={item.entryRef}
        onClick={() => {
          if (selectMode) onToggleSelect?.(item.entryRef)
        }}
      >
        {selectMode && (
          <input
            type="checkbox"
            checked={checked ?? false}
            onChange={() => onToggleSelect?.(item.entryRef)}
            onClick={(event) => event.stopPropagation()}
            aria-label={`选择「${item.title}」`}
          />
        )}
        <span>{item.feedTitle}</span>
        <button type="button">{item.title}</button>
        {selected ? <span data-testid="stub-selected" /> : null}
      </div>
    )
  },
}))
vi.mock('../components/EntryRow', () => ({
  default: function StubRow(props: {
    item: EntryListItem
    selected?: boolean
    selectMode?: boolean
    checked?: boolean
    onToggleSelect?: (entryRef: string) => void
  }) {
    const { item, selected, selectMode, checked, onToggleSelect } = props
    return (
      <div
        data-testid="stub-row"
        data-entry-ref={item.entryRef}
        onClick={() => {
          if (selectMode) onToggleSelect?.(item.entryRef)
        }}
      >
        {selectMode && (
          <input
            type="checkbox"
            checked={checked ?? false}
            onChange={() => onToggleSelect?.(item.entryRef)}
            onClick={(event) => event.stopPropagation()}
            aria-label={`选择「${item.title}」`}
          />
        )}
        <span>{item.feedTitle}</span>
        <button type="button">{item.title}</button>
        {selected ? <span data-testid="stub-selected" /> : null}
      </div>
    )
  },
}))

function entry(ref: string, overrides: Partial<EntryListItem> = {}): EntryListItem {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '源 A',
    feedUrl: 'https://a.example.com/feed.xml',
    author: null,
    url: null,
    publishedAt: '2026-09-18T08:00:00Z',
    read: false,
    starred: false,
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function withProviders(node: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

/** DOM 里每行同时挂 EntryRow + EntryCard（CSS 分发）——按首次出现去重。 */
function uniqueRowRefs(root: ParentNode): string[] {
  const unique: string[] = []
  for (const el of root.querySelectorAll('[data-entry-ref]')) {
    const ref = el.getAttribute('data-entry-ref')
    if (ref !== null && !unique.includes(ref)) unique.push(ref)
  }
  return unique
}

beforeEach(() => {
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null })
})

afterEach(() => {
  useAppSettings.getState().update({
    listGroupByFeed: false,
    timelineOrder: 'newest',
    groupByDate: false,
    cardSwipeAction: 'none',
  })
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null })
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('F05 按来源分组', () => {
  it('groupEntriesByFeed 纯函数：首次出现顺序；无 feedUrl → null；分页追加归组', () => {
    const batch1 = [
      entry('a1', { feedTitle: '源 A' }),
      entry('b1', { feedTitle: '源 B', feedUrl: 'https://b.example/rss' }),
      entry('a2', { feedTitle: '源 A' }),
    ]
    const groups = groupEntriesByFeed(batch1)
    expect(groups.map((g) => g.feedTitle)).toEqual(['源 A', '源 B'])
    expect(groups[0]!.items.map((i) => i.entryRef)).toEqual(['a1', 'a2'])
    expect(groups[0]!.feedUrl).toBe('https://a.example.com/feed.xml')
    // 分页追加（batch2 里的源 A 条目并入既有组，不产生第二组）
    const merged = groupEntriesByFeed([...batch1, entry('a3', { feedTitle: '源 A' })])
    expect(merged).toHaveLength(2)
    expect(merged[0]!.items.map((i) => i.entryRef)).toEqual(['a1', 'a2', 'a3'])
    // 缺失/空白 feedTitle → 「来源未知」；feedUrl 缺失 → null（不回填伪造）
    const fallback = groupEntriesByFeed([entry('x1', { feedTitle: '  ', feedUrl: undefined })])
    expect(fallback[0]!.feedTitle).toBe('来源未知')
    expect(fallback[0]!.feedUrl).toBeNull()
  })

  it('列表按来源分组渲染：组头计数（已加载口径）、组头折叠、只看此来源', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/entries')) {
        return jsonResponse({
          items: [
            entry('a1', { feedTitle: '源 A' }),
            entry('b1', { feedTitle: '源 B', feedUrl: 'https://b.example/rss' }),
            entry('a2', { feedTitle: '源 A' }),
          ],
          nextCursor: null,
        })
      }
      if (url.includes('/api/v1/feeds')) return jsonResponse([])
      return jsonResponse({ items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    useAppSettings.getState().update({ listGroupByFeed: true })
    const { container } = render(withProviders(<EntryList />))
    await screen.findAllByText('文章 a1')

    // 组头计数（已加载口径，非服务端总数）；顺序 = 首次出现顺序
    const counts = [...container.querySelectorAll('[data-loaded-count]')]
    expect(counts.map((el) => el.getAttribute('data-loaded-count'))).toEqual(['2', '1'])
    expect(counts[0]).toHaveTextContent('已加载 2 条')
    expect(counts[1]).toHaveTextContent('已加载 1 条')

    // 折叠「源 A」：组内行消失，源 B 保留（会话内本地状态）
    fireEvent.click(screen.getByRole('button', { name: '折叠/展开「源 A」分组' }))
    expect(screen.queryByText('文章 a1')).toBeNull()
    expect(screen.getAllByText('文章 b1').length).toBeGreaterThan(0)
    // 再点展开恢复
    fireEvent.click(screen.getByRole('button', { name: '折叠/展开「源 A」分组' }))
    expect(screen.getAllByText('文章 a1').length).toBeGreaterThan(0)

    // 只看此来源（源 A）：scope 切到该 rss-feed
    fireEvent.click(screen.getAllByRole('button', { name: '只看此来源' })[0]!)
    await waitFor(() => {
      expect(useReaderUi.getState().scope).toEqual({ kind: 'rss-feed', feedUrl: 'https://a.example.com/feed.xml' })
    })
  })

  it('组内第一项无 feedUrl → 「只看此来源」禁用（不伪造导航目标）', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/entries')) {
        return jsonResponse({ items: [entry('x1', { feedTitle: '源 X', feedUrl: undefined })], nextCursor: null })
      }
      if (url.includes('/api/v1/feeds')) return jsonResponse([])
      return jsonResponse({ items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    useAppSettings.getState().update({ listGroupByFeed: true })
    render(withProviders(<EntryList />))
    await screen.findAllByText('文章 x1')
    const button = screen.getByRole('button', { name: '只看此来源' })
    expect(button).toBeDisabled()
  })
})

describe('F06 排序切换（诚实客户端降级）', () => {
  it('切换按钮同步 settings；oldest 时 reverse + 常驻诚实标注；newest 恢复', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/entries')) {
        return jsonResponse({ items: [entry('e1.a'), entry('e1.b')], nextCursor: null })
      }
      if (url.includes('/api/v1/feeds')) return jsonResponse([])
      return jsonResponse({ items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    const { container } = render(withProviders(<EntryList />))
    await screen.findAllByText('文章 e1.a')

    const toggle = screen.getByTestId('timeline-order-toggle')
    expect(toggle).toHaveTextContent('最新优先')
    expect(toggle.getAttribute('aria-pressed')).toBe('false')
    expect(useAppSettings.getState().settings.timelineOrder).toBe('newest')
    // 默认最新优先：e1.a 在前
    expect(uniqueRowRefs(container).slice(0, 2)).toEqual(['e1.a', 'e1.b'])

    fireEvent.click(toggle)
    expect(useAppSettings.getState().settings.timelineOrder).toBe('oldest')
    expect(toggle).toHaveTextContent('最早优先')
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    // 客户端 reverse：已加载范围内 e1.b 在前
    expect(uniqueRowRefs(container).slice(0, 2)).toEqual(['e1.b', 'e1.a'])
    // 诚实标注：服务端分页仍为最新优先
    expect(screen.getByTestId('timeline-order-note')).toHaveTextContent(
      '最早优先（当前已加载范围内排序，服务端分页仍为最新优先）',
    )

    // 切回 newest：顺序与标注恢复
    fireEvent.click(toggle)
    expect(useAppSettings.getState().settings.timelineOrder).toBe('newest')
    expect(uniqueRowRefs(container).slice(0, 2)).toEqual(['e1.a', 'e1.b'])
    expect(screen.queryByTestId('timeline-order-note')).toBeNull()
  })
})

describe('F07 多选批量', () => {
  function mockEntriesApi(patchState: (ref: string, body: unknown) => Response = () => new Response(null, { status: 204 })) {
    const patchCalls: { ref: string; body: unknown }[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const match = /\/api\/v1\/entries\/([^/]+)\/state$/.exec(url)
      if (match !== null && init?.method === 'PATCH') {
        const ref = decodeURIComponent(match[1]!)
        const body = JSON.parse(String(init.body)) as unknown
        patchCalls.push({ ref, body })
        return patchState(ref, body)
      }
      if (url.includes('/api/v1/entries?')) {
        return jsonResponse({
          items: [entry('e1.a'), entry('e1.b'), entry('e1.c')],
          nextCursor: null,
        })
      }
      if (url.includes('/api/v1/feeds')) return jsonResponse([])
      return jsonResponse({ items: [] })
    })
    return { fetchMock, patchCalls }
  }

  it('进入/退出多选；点行与复选框切换选中；批量已读逐条 PATCH 后清空退出', async () => {
    const { fetchMock, patchCalls } = mockEntriesApi()
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<EntryList />))
    await screen.findAllByText('文章 e1.a')

    fireEvent.click(screen.getByTestId('enter-select-mode'))
    expect(screen.getByTestId('batch-bar')).toBeInTheDocument()
    // 真实 checkbox 进入 DOM（每行 row+card 两份，CSS 分发）
    expect(screen.getAllByRole('checkbox', { name: '选择「文章 e1.a」' }).length).toBeGreaterThan(0)

    // 点行标题 = 切换选中（不打开文章）
    fireEvent.click(screen.getAllByRole('button', { name: '文章 e1.a' })[0]!)
    expect(screen.getByTestId('selected-count')).toHaveTextContent('已选 1 条')
    expect(useReaderUi.getState().selectedEntryRef).toBeNull() // 未打开文章
    // 复选框切换 e1.b
    fireEvent.click(screen.getAllByRole('checkbox', { name: '选择「文章 e1.b」' })[0]!)
    expect(screen.getByTestId('selected-count')).toHaveTextContent('已选 2 条')
    // 再点一次取消
    fireEvent.click(screen.getAllByRole('checkbox', { name: '选择「文章 e1.b」' })[0]!)
    expect(screen.getByTestId('selected-count')).toHaveTextContent('已选 1 条')

    // 批量已读：逐条 PATCH read:true；完成后清空选择并退出多选
    fireEvent.click(screen.getByTestId('batch-read'))
    await waitFor(() => expect(screen.queryByTestId('batch-bar')).toBeNull())
    await waitFor(() => expect(patchCalls).toHaveLength(1))
    expect(patchCalls[0]).toEqual({ ref: 'e1.a', body: { read: true } })
    expect(useAppSettings.getState().settings.timelineOrder).toBe('newest') // 无副作用
    // 退出多选态：选择按钮回归
    expect(screen.getByTestId('enter-select-mode')).toBeInTheDocument()
  })

  it('部分失败：列出失败 ref；重试失败项只重发失败的', async () => {
    let failRef: string | null = 'e1.a'
    const { fetchMock, patchCalls } = mockEntriesApi((ref) =>
      ref === failRef ? jsonResponse({ error: { type: 'x', message: 'boom' } }, 500) : new Response(null, { status: 204 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<EntryList />))
    await screen.findAllByText('文章 e1.a')

    fireEvent.click(screen.getByTestId('enter-select-mode'))
    fireEvent.click(screen.getAllByRole('button', { name: '文章 e1.a' })[0]!)
    fireEvent.click(screen.getAllByRole('button', { name: '文章 e1.b' })[0]!)
    fireEvent.click(screen.getByTestId('batch-read'))

    // e1.a 失败：批量栏保留并诚实列出失败 ref
    const failedNote = await screen.findByTestId('batch-failed')
    expect(failedNote).toHaveTextContent('标为已读失败 1 条：e1.a')
    expect(screen.getByTestId('batch-retry')).toBeInTheDocument()

    // 修复后重试：只重发失败的 e1.a（e1.b 不重复发）
    failRef = null
    fireEvent.click(screen.getByTestId('batch-retry'))
    await waitFor(() => expect(screen.queryByTestId('batch-bar')).toBeNull())
    const refCounts = patchCalls.reduce<Record<string, number>>((acc, call) => {
      acc[call.ref] = (acc[call.ref] ?? 0) + 1
      return acc
    }, {})
    expect(refCounts).toEqual({ 'e1.a': 2, 'e1.b': 1 })
  })

  it('批量上限 100：全选超过上限后动作禁用并提示', async () => {
    const many = Array.from({ length: 101 }, (_, i) => entry(`m${i}`))
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/entries?')) return jsonResponse({ items: many, nextCursor: null })
      if (url.includes('/api/v1/feeds')) return jsonResponse([])
      return jsonResponse({ items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<EntryList />))
    await screen.findAllByText('文章 m0')

    fireEvent.click(screen.getByTestId('enter-select-mode'))
    fireEvent.click(screen.getByRole('button', { name: '全选已加载' }))
    expect(screen.getByTestId('selected-count')).toHaveTextContent('已选 101 条')
    expect(screen.getByRole('alert')).toHaveTextContent('一次最多批量处理 100 条')
    expect(screen.getByTestId('batch-read')).toBeDisabled()
    expect(screen.getByTestId('batch-star')).toBeDisabled()
    expect(screen.getByTestId('batch-readLater')).toBeDisabled()
  })
})

describe('F09 下拉刷新（刷新列表数据，不触发上游抓取）', () => {
  it('下拉达阈值释放 → refetch 一次 + 「已刷新」；未达阈值不触发', async () => {
    let entriesCalls = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/entries?')) {
        entriesCalls += 1
        return jsonResponse({ items: [entry('e1.a')], nextCursor: null })
      }
      if (url.includes('/api/v1/feeds')) return jsonResponse([])
      return jsonResponse({ items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<EntryList />))
    await screen.findAllByText('文章 e1.a')
    expect(entriesCalls).toBe(1)

    const container = screen.getByTestId('list-scroll-container')
    // 未达阈值（dy=100 → 位移 40 < 60）：不触发
    fireEvent.touchStart(container, { touches: [{ clientX: 100, clientY: 10 }] })
    fireEvent.touchMove(container, { touches: [{ clientX: 100, clientY: 110 }] })
    expect(screen.getByTestId('pull-indicator')).toHaveTextContent('下拉刷新列表')
    fireEvent.touchEnd(container)
    expect(screen.queryByTestId('pull-indicator')).toBeNull()
    expect(entriesCalls).toBe(1)

    // 达阈值（dy=200 → 位移 64 ≥ 60）：释放触发一次 refetch
    fireEvent.touchStart(container, { touches: [{ clientX: 100, clientY: 10 }] })
    fireEvent.touchMove(container, { touches: [{ clientX: 100, clientY: 210 }] })
    expect(screen.getByTestId('pull-indicator')).toHaveTextContent('释放刷新列表')
    fireEvent.touchEnd(container)
    await screen.findByText('已刷新')
    await waitFor(() => expect(entriesCalls).toBe(2))
    // 指示条 1.5s 后自动收起（真实计时器）
    await waitFor(
      () => expect(screen.queryByTestId('pull-indicator')).toBeNull(),
      { timeout: 3000 },
    )
  })

  it('刷新失败：显示「刷新失败」并保留列表（数据不丢）', async () => {
    let entriesCalls = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/entries?')) {
        entriesCalls += 1
        if (entriesCalls > 1) return jsonResponse({ error: { type: 'x', message: 'boom' } }, 500)
        return jsonResponse({ items: [entry('e1.a')], nextCursor: null })
      }
      if (url.includes('/api/v1/feeds')) return jsonResponse([])
      return jsonResponse({ items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<EntryList />))
    await screen.findAllByText('文章 e1.a')

    const container = screen.getByTestId('list-scroll-container')
    fireEvent.touchStart(container, { touches: [{ clientX: 100, clientY: 10 }] })
    fireEvent.touchMove(container, { touches: [{ clientX: 100, clientY: 210 }] })
    fireEvent.touchEnd(container)
    await screen.findByText('刷新失败')
    // 失败保留列表
    expect(screen.getAllByText('文章 e1.a').length).toBeGreaterThan(0)
  })

  it('不在顶部 / 触点超出顶部 60px：手势不激活', async () => {
    let entriesCalls = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/entries?')) {
        entriesCalls += 1
        return jsonResponse({ items: [entry('e1.a')], nextCursor: null })
      }
      if (url.includes('/api/v1/feeds')) return jsonResponse([])
      return jsonResponse({ items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<EntryList />))
    await screen.findAllByText('文章 e1.a')

    const container = screen.getByTestId('list-scroll-container')
    // 触点在容器顶部 60px 之外（jsdom rect.top=0 → clientY 200 超区）
    fireEvent.touchStart(container, { touches: [{ clientX: 100, clientY: 200 }] })
    fireEvent.touchMove(container, { touches: [{ clientX: 100, clientY: 400 }] })
    fireEvent.touchEnd(container)
    expect(screen.queryByTestId('pull-indicator')).toBeNull()
    expect(entriesCalls).toBe(1)
  })
})

// ---- F26 订阅置顶/排序 ----

const CAT_A = { id: 'user/-/label/技术', label: '技术' }
const SUBSCRIPTIONS = [
  { subscriptionRef: 's1.a', title: 'Tech Feed', feedUrl: 'https://tech.example/rss', category: CAT_A },
  { subscriptionRef: 's1.b', title: 'Lone Feed', feedUrl: 'https://lone.example/rss', category: null },
]

function mockSubscriptionApi() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/subscriptions')) return jsonResponse(SUBSCRIPTIONS)
    if (url.startsWith('/api/v1/categories')) return jsonResponse([CAT_A])
    if (url.startsWith('/api/v1/sources/volume')) return jsonResponse({ items: [] })
    if (url.startsWith('/api/v1/feeds')) return jsonResponse([])
    return jsonResponse({ items: [] })
  })
}

describe('F26 订阅置顶/排序', () => {
  it('置顶 → 置顶区出现并持久；上移/下移（边界 disabled）；取消置顶；刷新保持', async () => {
    vi.stubGlobal('fetch', mockSubscriptionApi())
    const { unmount } = render(withProviders(<SubscriptionsPage />))
    await screen.findByText('Tech Feed')

    // 初始无置顶区
    expect(screen.queryByTestId('pinned-section')).toBeNull()

    // 置顶 Tech Feed（行内 Pin 按钮 aria-pressed）
    const pinTech = screen.getByRole('button', { name: '置顶「Tech Feed」' })
    expect(pinTech.getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(pinTech)
    expect(screen.getByTestId('pinned-section')).toBeInTheDocument()
    expect(readPinnedFeeds()).toEqual(['https://tech.example/rss'])

    // 置顶 Lone Feed → 顺序 [tech, lone]
    fireEvent.click(screen.getByRole('button', { name: '置顶「Lone Feed」' }))
    expect(readPinnedFeeds()).toEqual(['https://tech.example/rss', 'https://lone.example/rss'])

    // 上移 Lone → [lone, tech]（持久化同步）
    fireEvent.click(screen.getByRole('button', { name: '上移「Lone Feed」' }))
    expect(readPinnedFeeds()).toEqual(['https://lone.example/rss', 'https://tech.example/rss'])
    const section = screen.getByTestId('pinned-section')
    // 置顶区同时展示两个订阅
    expect(within(section).getByText('Lone Feed')).toBeInTheDocument()
    expect(within(section).getByText('Tech Feed')).toBeInTheDocument()
    // 边界：第一行上移禁用、最后一行下移禁用
    expect(screen.getByRole('button', { name: '上移「Lone Feed」' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '下移「Tech Feed」' })).toBeDisabled()

    // 取消置顶 Tech（置顶区内的取消按钮）
    fireEvent.click(within(section).getByRole('button', { name: '取消置顶「Tech Feed」' }))
    expect(readPinnedFeeds()).toEqual(['https://lone.example/rss'])

    // 刷新（重新挂载）后置顶保持（localStorage 恢复）
    unmount()
    vi.stubGlobal('fetch', mockSubscriptionApi())
    render(withProviders(<SubscriptionsPage />))
    await screen.findByText('Tech Feed')
    expect(screen.getByTestId('pinned-section')).toBeInTheDocument()
    expect(within(screen.getByTestId('pinned-section')).getByText('Lone Feed')).toBeInTheDocument()
  })

  it('纯函数：toggle 上限 12；move 越界原样返回', () => {
    expect(PINNED_FEEDS_LIMIT).toBe(12)
    const full = Array.from({ length: PINNED_FEEDS_LIMIT }, (_, i) => `u${i}`)
    expect(togglePinnedFeed(full, 'new')).toBe(full) // 已满不再新增
    expect(togglePinnedFeed(['a', 'b'], 'a')).toEqual(['b']) // 取消
    expect(togglePinnedFeed(['a'], 'b')).toEqual(['a', 'b'])
    expect(movePinnedFeed(['a', 'b', 'c'], 'a', -1)).toEqual(['a', 'b', 'c']) // 顶部上移越界
    expect(movePinnedFeed(['a', 'b', 'c'], 'c', 1)).toEqual(['a', 'b', 'c']) // 底部下移越界
    expect(movePinnedFeed(['a', 'b', 'c'], 'b', -1)).toEqual(['b', 'a', 'c'])
    expect(movePinnedFeed(['a', 'b', 'c'], 'b', 1)).toEqual(['a', 'c', 'b'])
  })
})
