/** FIX-160 — 多选批量在视图/范围切换后不得作用于旧选中集合。
 *
 * 场景：view='all' 进入多选并选中若干行 → 切到 view='unread'（或切换
 * scope feed/分类）——EntriesList 保持挂载，列表内容已换，但旧
 * selectedRefs 原样保留：底部批量条仍显示「已选 N 条」，批量动作会
 * 作用于当前列表里根本不可见的旧集合。
 *
 * 契约：视图（view）或范围（scope）变化 → 选择集合立即清空（与
 * reader-ui「切 scope 清空 selection：旧选择可能已不属于新列表」同一
 * 语义）；多选模式保留（可重新勾选），批量条如实显示 已选 0 条 且
 * 动作禁用。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EntryList from '../components/EntryList'
import { useReaderUi } from '../store/reader-ui'
import type { EntryListItem } from '../api/types'

vi.mock('../components/EntryCard', () => ({
  default: function StubCard(props: {
    item: EntryListItem
    selectMode?: boolean
    checked?: boolean
    onToggleSelect?: (entryRef: string) => void
  }) {
    const { item, selectMode, checked, onToggleSelect } = props
    return (
      <div data-testid="stub-card" data-entry-ref={item.entryRef}>
        {selectMode && (
          <input
            type="checkbox"
            checked={checked ?? false}
            onChange={() => onToggleSelect?.(item.entryRef)}
            aria-label={`选择「${item.title}」`}
          />
        )}
        <span>{item.feedTitle}</span>
        <button type="button">{item.title}</button>
      </div>
    )
  },
}))
vi.mock('../components/EntryRow', () => ({
  default: function StubRow(props: {
    item: EntryListItem
    selectMode?: boolean
    checked?: boolean
    onToggleSelect?: (entryRef: string) => void
  }) {
    const { item, selectMode, checked, onToggleSelect } = props
    return (
      <div data-testid="stub-row" data-entry-ref={item.entryRef}>
        {selectMode && (
          <input
            type="checkbox"
            checked={checked ?? false}
            onChange={() => onToggleSelect?.(item.entryRef)}
            aria-label={`选择「${item.title}」`}
          />
        )}
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

const LISTS: Record<string, EntryListItem[]> = {
  all: [entry('e1.a'), entry('e1.b'), entry('e1.c')],
  unread: [entry('e2.a'), entry('e2.b')],
}

function mockApi() {
  const patchCalls: { ref: string }[] = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (/\/api\/v1\/entries\/[^/]+\/state$/.test(url) && init?.method === 'PATCH') {
      patchCalls.push({ ref: decodeURIComponent(/\/entries\/([^/]+)\//.exec(url)![1]!) })
      return Promise.resolve(new Response(null, { status: 204 }))
    }
    if (url.includes('/api/v1/entries?')) {
      const view = /view=([^&]+)/.exec(url)?.[1] ?? 'all'
      return Promise.resolve(
        jsonResponse({ items: LISTS[view] ?? LISTS.all!, nextCursor: null }),
      )
    }
    if (url.includes('/api/v1/feeds')) return Promise.resolve(jsonResponse([]))
    return Promise.resolve(jsonResponse({ items: [] }))
  })
  return { fetchMock, patchCalls }
}

function renderList() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <EntryList />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null })
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
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null })
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('FIX-160 — 视图/范围切换后批量选择不残留', () => {
  it('view=all 选中 2 条 → 切 view=unread → 选择清空；批量已读不会作用于旧集合', async () => {
    const { fetchMock, patchCalls } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    renderList()
    await screen.findAllByText('文章 e1.a')

    // R11 顶栏迁移：「选择」入口在「视图」选单内
    fireEvent.click(screen.getByRole('button', { name: '视图' }))
    fireEvent.click(await screen.findByTestId('enter-select-mode'))
    fireEvent.click(screen.getAllByRole('checkbox', { name: '选择「文章 e1.a」' })[0]!)
    fireEvent.click(screen.getAllByRole('checkbox', { name: '选择「文章 e1.b」' })[0]!)
    expect(screen.getByTestId('selected-count')).toHaveTextContent('已选 2 条')

    // 切换视图（EntriesList 保持挂载；列表换成 unread 集合）
    act(() => {
      useReaderUi.getState().selectView('unread')
    })
    await screen.findAllByText('文章 e2.a')

    // 旧选择立即清空：批量条如实显示 0，动作禁用（点击不产生任何请求，
    // 绝不作用于已不可见的 e1.a/e1.b）
    expect(screen.getByTestId('selected-count')).toHaveTextContent('已选 0 条')
    expect(screen.getByTestId('batch-read')).toBeDisabled()
    fireEvent.click(screen.getByTestId('batch-read'))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(patchCalls).toEqual([])
  })

  it('scope 切换（feed）同样清空选择', async () => {
    const { fetchMock } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    renderList()
    await screen.findAllByText('文章 e1.a')

    // R11 顶栏迁移：「选择」入口在「视图」选单内
    fireEvent.click(screen.getByRole('button', { name: '视图' }))
    fireEvent.click(await screen.findByTestId('enter-select-mode'))
    fireEvent.click(screen.getAllByRole('checkbox', { name: '选择「文章 e1.a」' })[0]!)
    expect(screen.getByTestId('selected-count')).toHaveTextContent('已选 1 条')

    act(() => {
      useReaderUi.getState().selectScope({ kind: 'rss-feed', feedUrl: 'https://b.example.com/feed.xml' })
    })
    await waitFor(() => {
      expect(screen.getByTestId('selected-count')).toHaveTextContent('已选 0 条')
    })
  })
})
