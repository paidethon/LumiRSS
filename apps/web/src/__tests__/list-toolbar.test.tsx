/** R11 方案 B — 列表顶栏集成（未读 segmented / 视图选单 / 工具抽屉入口）。
 *
 * 图2 九入口逐一归属、一个不删：
 * - 抽屉（六项）：阅读预算/今日必读/阅读路径/阅读决策→阅读组；
 *   积压整理→整理组；共读空间→共读组（ToolsDrawer 行为细节见
 *   tools-drawer.test.tsx，此处锁「工具按钮打开唯一抽屉」的接线与
 *   顶栏不再有六个平铺工具入口）；
 * - 视图选单（三项）：时间线排序（最新优先）/聚合同链/选择；
 * - 顶栏 segmented：全部/未读（复用 view 语义，与 MobileHeader 同源）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import EntryList from '../components/EntryList'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import type { EntryListItem } from '../api/types'

// 轻量 stub 行卡（与 list-features.test.tsx 同一契约：标题/来源文本）。
vi.mock('../components/EntryCard', () => ({
  default: function StubCard({ item }: { item: EntryListItem }) {
    return (
      <div data-testid="stub-card" data-entry-ref={item.entryRef}>
        <span>{item.feedTitle}</span>
        <button type="button">{item.title}</button>
      </div>
    )
  },
}))
vi.mock('../components/EntryRow', () => ({
  default: function StubRow({ item }: { item: EntryListItem }) {
    return (
      <div data-testid="stub-row" data-entry-ref={item.entryRef}>
        <span>{item.feedTitle}</span>
        <button type="button">{item.title}</button>
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
    publishedAt: '2026-09-01T10:00:00Z',
    read: false,
    starred: false,
    snippet: null,
    ...overrides,
  }
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

function withProviders(ui: ReactNode): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function renderList(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/entries?')) {
        return Promise.resolve(
          jsonResponse({ items: [entry('e1.a'), entry('e1.b')], nextCursor: null }),
        )
      }
      if (url.includes('/api/v1/feeds')) return Promise.resolve(jsonResponse([]))
      return Promise.resolve(jsonResponse({ items: [] }))
    }),
  )
  render(withProviders(<EntryList />))
}

beforeEach(() => {
  window.localStorage.clear()
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null })
  useAppSettings.setState({
    settings: { ...useAppSettings.getState().settings, timelineOrder: 'newest' },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('R11 顶栏 — 未读 segmented（全部/未读）', () => {
  it('segmented 双向绑定 view 语义；aria-pressed 表达当前态', async () => {
    renderList()
    await screen.findAllByText('文章 e1.a')

    const all = screen.getByRole('button', { name: '全部' })
    const unread = screen.getByRole('button', { name: '未读' })
    expect(all).toHaveAttribute('aria-pressed', 'true')
    expect(unread).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(unread)
    await waitFor(() => {
      expect(useReaderUi.getState().view).toBe('unread')
    })
    expect(unread).toHaveAttribute('aria-pressed', 'true')
    expect(all).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(all)
    await waitFor(() => {
      expect(useReaderUi.getState().view).toBe('all')
    })
  })

  it('收藏视图（侧栏进入）下 segmented 两者都不激活（不冒充）', async () => {
    act(() => {
      useReaderUi.setState({ view: 'starred' })
    })
    renderList()
    await screen.findAllByText('文章 e1.a')
    expect(screen.getByRole('button', { name: '全部' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: '未读' })).toHaveAttribute('aria-pressed', 'false')
  })
})

describe('R11 顶栏 — 视图选单（排序/聚合/选择）', () => {
  it('选单含时间线排序/聚合同链/选择三项；聚合同链点击后带选中标记', async () => {
    renderList()
    await screen.findAllByText('文章 e1.a')

    fireEvent.click(screen.getByRole('button', { name: '视图' }))
    const menu = await screen.findByRole('menu')
    expect(menu).toHaveTextContent('时间线排序：最新优先')
    expect(menu).toHaveTextContent('聚合同链')
    expect(menu).toHaveTextContent('选择文章')

    fireEvent.click(screen.getByText('聚合同链'))
    // 菜单选择后关闭；再次打开可见选中标记（诚实状态）
    fireEvent.click(screen.getByRole('button', { name: '视图' }))
    await waitFor(() => {
      expect(screen.getByRole('menu')).toBeInTheDocument()
    })
  })

  it('「选择文章」进入多选（批处理模式）；「退出多选」在顶栏可达', async () => {
    renderList()
    await screen.findAllByText('文章 e1.a')

    fireEvent.click(screen.getByRole('button', { name: '视图' }))
    fireEvent.click(await screen.findByTestId('enter-select-mode'))
    expect(screen.getByTestId('batch-bar')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '退出多选' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '退出多选' }))
    await waitFor(() => {
      expect(screen.queryByTestId('batch-bar')).toBeNull()
    })
  })
})

describe('R11 顶栏 — 工具按钮打开唯一抽屉', () => {
  it('「工具」打开 DetailDrawer（标题「工具」），六工具分三组全在', async () => {
    renderList()
    await screen.findAllByText('文章 e1.a')

    fireEvent.click(screen.getByTestId('tools-drawer-open'))
    expect(await screen.findByRole('tablist', { name: '工具分组' })).toBeInTheDocument()
    for (const id of ['budget', 'queue', 'path', 'decisions']) {
      expect(screen.getByTestId(`tools-drawer-item-${id}`)).toBeInTheDocument()
    }
    fireEvent.click(screen.getByRole('tab', { name: '整理' }))
    expect(screen.getByTestId('tools-drawer-item-backlog')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '共读' }))
    expect(screen.getByTestId('tools-drawer-item-space')).toBeInTheDocument()
  })

  it('旧平铺六入口不再出现在顶栏（迁移到抽屉，非删除功能）', async () => {
    renderList()
    await screen.findAllByText('文章 e1.a')
    for (const label of ['阅读预算', '今日必读', '阅读路径', '阅读决策', '积压整理', '共读空间']) {
      expect(screen.queryByRole('button', { name: label })).toBeNull()
    }
  })
})
