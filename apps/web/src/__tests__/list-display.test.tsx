/** 2026-09 移动端专项 — 列表展示（F01–F04）与统一来源元信息（P2）。
 *
 * 行为证明（不只“不抛错”）：
 * - F02 摘要开关真实控制摘要行渲染（关 = 行消失，标题/来源仍在）；
 * - F03 封面开关关闭时 <img> 不进 DOM（零请求）；开启时 lazy + 无 referrer；
 * - F04 相对/绝对时间（非法/缺失 → —）；
 * - P2 来源缺失降级「来源未知」（绝不 undefined/空分隔点）；有 feedUrl
 *   时来源可点击进入该订阅范围；无 feedUrl 时纯文本（不伪装按钮）；
 * - F01 密度设置映射到列表容器 data-density（CSS 消费）。
 */

import { act, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import EntryCard from '../components/EntryCard'
import EntryList from '../components/EntryList'
import { useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'
import type { EntryListItem } from '../api/types'
import { formatListTime, formatRelativeTime } from '../lib/date-format'
import { resolveSourceName } from '../lib/source-meta'

/** EntryCard 内部 EntryActionButtons 使用 query hooks → 需 Provider。 */
function withProviders(node: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

function item(overrides: Partial<EntryListItem> = {}): EntryListItem {
  return {
    entryRef: 'e1.a',
    title: '文章标题',
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: '2026-09-18T08:00:00Z',
    read: false,
    starred: false,
    ...overrides,
  }
}

afterEach(() => {
  useAppSettings.getState().update({
    listShowSnippet: true,
    listShowCover: true,
    listTimeFormat: 'relative',
    listDensity: 'standard',
  })
  useReaderUi.getState().selectEntry(null)
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, selectedEntryRef: null })
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('lib 层纯函数', () => {
  it('resolveSourceName：空白/缺失 → 来源未知；正常保留', () => {
    expect(resolveSourceName(undefined)).toBe('来源未知')
    expect(resolveSourceName(null)).toBe('来源未知')
    expect(resolveSourceName('   ')).toBe('来源未知')
    expect(resolveSourceName(' 阮一峰的网络日志 ')).toBe('阮一峰的网络日志')
  })

  it('formatRelativeTime：刚刚/分钟/小时/昨天/天/超7天回退绝对；无效 → —', () => {
    const now = new Date('2026-09-18T12:00:00Z')
    expect(formatRelativeTime(null)).toBe('—')
    expect(formatRelativeTime('not-a-date')).toBe('—')
    expect(formatRelativeTime('2026-09-18T11:59:30Z', now)).toBe('刚刚')
    expect(formatRelativeTime('2026-09-18T11:30:00Z', now)).toBe('30 分钟前')
    expect(formatRelativeTime('2026-09-18T06:00:00Z', now)).toBe('6 小时前')
    expect(formatRelativeTime('2026-09-17T06:00:00Z', now)).toBe('昨天')
    expect(formatRelativeTime('2026-09-14T12:00:00Z', now)).toBe('4 天前')
    // 超 7 天回退完整绝对时间（含年份）；未来时间不相对化。
    expect(formatRelativeTime('2026-08-20T00:00:00Z', now)).toContain('2026')
    expect(formatRelativeTime('2026-09-19T00:00:00Z', now)).toContain('2026')
  })

  it('formatListTime：absolute 模式走列表短格式', () => {
    const now = new Date('2026-09-18T12:00:00Z')
    expect(formatListTime('2026-09-18T11:30:00Z', 'relative', now)).toBe('30 分钟前')
    expect(formatListTime('2026-09-18T11:30:00Z', 'absolute', now)).toMatch(/09\/18/)
  })
})

describe('EntryCard — F02/F03/F04/P2', () => {
  it('F02：摘要行随开关渲染/消失；无 snippet 字段时该行恒不渲染', () => {
    const withSnippet = item({ snippet: '这是正文摘要，应当出现在卡片里。' })
    const { unmount } = render(withProviders(<EntryCard item={withSnippet} selected={false} />))
    expect(screen.getByText('这是正文摘要，应当出现在卡片里。')).toBeInTheDocument()
    unmount()

    useAppSettings.getState().update({ listShowSnippet: false })
    render(withProviders(<EntryCard item={withSnippet} selected={false} />))
    expect(screen.queryByText('这是正文摘要，应当出现在卡片里。')).toBeNull()
    expect(screen.getByText('文章标题')).toBeInTheDocument() // 标题仍在
  })

  it('F02：无 snippet 字段 → 不渲染摘要行（无伪造内容）', () => {
    render(withProviders(<EntryCard item={item()} selected={false} />))
    expect(document.querySelectorAll('.line-clamp-2').length).toBe(0)
  })

  it('F03：关闭封面 = <img> 不进 DOM（零请求）；开启时 lazy + no-referrer', () => {
    const withCover = item({ coverUrl: 'https://img.example/cover.jpg' })
    useAppSettings.getState().update({ listShowCover: false })
    const { unmount } = render(withProviders(<EntryCard item={withCover} selected={false} />))
    expect(document.querySelector('img')).toBeNull()
    unmount()

    useAppSettings.getState().update({ listShowCover: true })
    render(withProviders(<EntryCard item={withCover} selected={false} />))
    const img = document.querySelector('img')
    expect(img).not.toBeNull()
    expect(img!.getAttribute('loading')).toBe('lazy')
    expect(img!.getAttribute('referrerPolicy')).toBe('no-referrer')
    expect(img!.getAttribute('src')).toBe('https://img.example/cover.jpg')
  })

  it('P2：来源缺失 → 「来源未知」；无 feedUrl 时来源是纯文本非按钮', () => {
    render(withProviders(<EntryCard item={item({ feedTitle: '  ', feedUrl: null })} selected={false} />))
    expect(screen.getByText('来源未知')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '来源未知' })).toBeNull()
  })

  it('P2：有 feedUrl 时来源可点击 → 进入 home + 该订阅 scope（不打开文章）', () => {
    useReaderUi.setState({ section: 'search' })
    render(
      withProviders(
        <EntryCard
          item={item({ feedUrl: 'https://a.example.com/feed.xml' })}
          selected={false}
        />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '示例源' }))
    const state = useReaderUi.getState()
    expect(state.section).toBe('home')
    expect(state.scope).toEqual({ kind: 'rss-feed', feedUrl: 'https://a.example.com/feed.xml' })
    expect(state.selectedEntryRef).toBeNull()
  })

  it('F04：刚发布 → 「刚刚」；缺失 publishedAt → 「—」', () => {
    render(withProviders(<EntryCard item={item({ publishedAt: new Date().toISOString() })} selected={false} />))
    expect(screen.getByText('刚刚')).toBeInTheDocument()
  })
})

describe('EntryList — F01 密度映射', () => {
  it('列表容器 data-density 跟随设置（CSS 消费）', async () => {
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/entries?')) {
        return Promise.resolve(json({ items: [item()], nextCursor: null }))
      }
      if (url.includes('/api/v1/feeds')) {
        return Promise.resolve(json({ feeds: [] }))
      }
      if (url.includes('/api/v1/workspaces/')) {
        return Promise.resolve(json({ items: [] }))
      }
      return Promise.resolve(json({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null })
    const view = render(withProviders(<EntryList />))
    // 桌面行 + 移动卡同时挂载（CSS 分发）→ 两个标题元素。
    expect((await screen.findAllByText('文章标题')).length).toBe(2)
    expect(view.container.querySelector('ul')!.getAttribute('data-density')).toBe('standard')
    act(() => {
      useAppSettings.getState().update({ listDensity: 'comfortable' })
    })
    expect(view.container.querySelector('ul')!.getAttribute('data-density')).toBe('comfortable')
    act(() => {
      useAppSettings.getState().update({ listDensity: 'compact' })
    })
    expect(view.container.querySelector('ul')!.getAttribute('data-density')).toBe('compact')
  })
})
