/** F27 日期筛选 / F28 突出匹配词 / F29 高级面板。
 *
 * 纯逻辑（lib/search-advanced / lib/highlight-text）+ SearchPage 接线：
 * - quickRange 本地时区生成正确 from/to（今天/近7天/近30天）；
 * - buildAdvancedSearchUrl 参数齐全（空条件省略）；searchEntriesAdvanced
 *   错误信封转 Error message；
 * - splitTerms / splitHighlightSegments：casefold 命中、跨词合并、无残留；
 * - SearchPage：快捷范围生成 from/to 参数（断言 fetch URL）、chips 显示
 *   与清除恢复、高级条件传 intitle/phrase/exclude、空查询 + 仅高级条件
 *   诚实提示不发请求、高亮 <mark> 随开关与搜索词变化（无残留）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SearchPage from '../components/pages/SearchPage'
import {
  buildAdvancedSearchUrl,
  isAdvancedSearchActive,
  quickRange,
  searchEntriesAdvanced,
  toLocalDateString,
} from '../lib/search-advanced'
import { HighlightText, splitHighlightSegments, splitTerms } from '../lib/highlight-text'
import { useAppSettings } from '../store/app-settings'
import { useSearchState } from '../store/search-state'
import { useReaderUi } from '../store/reader-ui'
import type { SearchResponse } from '../api/types'

function searchResponse(items: Partial<SearchResponse['items'][number]>[] = []): SearchResponse {
  return {
    items: items.map((item) => ({
      entryRef: 'e1.a',
      title: '默认标题',
      feedTitle: '源',
      feedUrl: 'https://a.example/rss',
      matchedFields: ['title'],
      publishedAt: '2026-09-18T08:00:00Z',
      read: false,
      snippet: '',
      starred: false,
      ...item,
    })),
    nextCursor: null,
    hasMore: false,
    elapsedMs: 1,
    index: { entryCount: 1, lastSyncedAt: null, partial: false },
    library: [],
    libraryHasMore: false,
    libraryNextCursor: null,
    libraryError: null,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function withProviders(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

/** 输入 + Enter 立即提交（不等 300ms 防抖，测试确定性）。 */
async function submitQuery(query: string) {
  const input = screen.getByLabelText('搜索')
  fireEvent.change(input, { target: { value: query } })
  fireEvent.keyDown(input, { key: 'Enter' })
}

afterEach(() => {
  useSearchState.getState().clear()
  useAppSettings.getState().update({ searchHighlightMatches: true })
  useReaderUi.setState({ selectedEntryRef: null })
  vi.unstubAllGlobals()
})

describe('search-advanced 纯逻辑', () => {
  it('toLocalDateString / quickRange：本地时区 YYYY-MM-DD（今天/近7天/近30天）', () => {
    const now = new Date(2026, 8, 18, 15, 30) // 2026-09-18 15:30 本地
    expect(toLocalDateString(now)).toBe('2026-09-18')
    expect(quickRange('today', now)).toEqual({ from: '2026-09-18', to: '2026-09-18' })
    expect(quickRange('7d', now)).toEqual({ from: '2026-09-12', to: '2026-09-18' })
    expect(quickRange('30d', now)).toEqual({ from: '2026-08-20', to: '2026-09-18' })
  })

  it('buildAdvancedSearchUrl：条件齐全；空条件省略', () => {
    const full = buildAdvancedSearchUrl({
      q: 'react',
      from: '2026-09-12',
      to: '2026-09-18',
      intitle: 'hook',
      phrase: 'use state',
      exclude: 'class 组件',
      state: 'unread',
    })
    expect(full.startsWith('/api/v1/search?')).toBe(true)
    expect(full).toContain('q=react')
    expect(full).toContain('from=2026-09-12')
    expect(full).toContain('to=2026-09-18')
    expect(full).toContain('intitle=hook')
    expect(full).toContain('phrase=use')
    expect(full).toContain('exclude=')
    expect(full).toContain('state=unread')

    const minimal = buildAdvancedSearchUrl({ q: 'react', from: null, intitle: '' })
    expect(minimal).not.toContain('from=')
    expect(minimal).not.toContain('intitle=')
    expect(minimal).not.toContain('phrase=')
  })

  it('isAdvancedSearchActive：日期或高级任一存在即激活', () => {
    expect(isAdvancedSearchActive(null, null)).toBe(false)
    expect(isAdvancedSearchActive({ from: null, to: null }, null)).toBe(false)
    expect(isAdvancedSearchActive({ from: '2026-09-01', to: null }, null)).toBe(true)
    expect(isAdvancedSearchActive(null, { intitle: '', phrase: 'x', exclude: '' })).toBe(true)
    expect(isAdvancedSearchActive(null, { intitle: '', phrase: '', exclude: '' })).toBe(false)
  })

  it('searchEntriesAdvanced：非 2xx 错误信封转 Error message', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(jsonResponse({ error: { type: 'invalid_q', message: 'q 不能为空' } }, 422)),
    )
    vi.stubGlobal('fetch', fetchMock)
    await expect(searchEntriesAdvanced({ q: '' })).rejects.toThrow('q 不能为空')
  })
})

describe('highlight-text 纯逻辑（F28）', () => {
  it('splitTerms：空白分词去空', () => {
    expect(splitTerms('  React   资料 ')).toEqual(['React', '资料'])
    expect(splitTerms('   ')).toEqual([])
  })

  it('splitHighlightSegments：大小写不敏感、相邻命中合并、无命中原样', () => {
    expect(splitHighlightSegments('React 指南与 react 历史', ['react'])).toEqual([
      { text: 'React', hit: true },
      { text: ' 指南与 ', hit: false },
      { text: 'react', hit: true },
      { text: ' 历史', hit: false },
    ])
    expect(splitHighlightSegments('abc', ['ab', 'bc'])).toEqual([{ text: 'abc', hit: true }])
    expect(splitHighlightSegments('纯文本', ['xyz'])).toEqual([{ text: '纯文本', hit: false }])
    expect(splitHighlightSegments('任意', [])).toEqual([{ text: '任意', hit: false }])
  })

  it('HighlightText 组件：开关关闭 / 无 terms → 无 <mark>；命中包裹且文本无残缺', () => {
    const { container, rerender } = render(
      <HighlightText text="React 指南" terms={['react']} enabled={false} />,
    )
    expect(container.querySelectorAll('mark')).toHaveLength(0)
    expect(container.textContent).toBe('React 指南')
    rerender(<HighlightText text="React 指南" terms={[]} enabled />)
    expect(container.querySelectorAll('mark')).toHaveLength(0)
    rerender(<HighlightText text="React 指南" terms={['react']} enabled />)
    const marks = container.querySelectorAll('mark')
    expect(marks).toHaveLength(1)
    expect(marks[0]!.textContent).toBe('React')
    expect(container.textContent).toBe('React 指南')
  })
})

describe('SearchPage — F27 日期筛选', () => {
  it('快捷范围生成正确 from/to 参数（断言 fetch URL）；chip 显示并可清除恢复', async () => {
    const searchUrls: string[] = []
    vi.stubGlobal('fetch', mockSearchApiFetch(searchUrls, [{ entryRef: 's1', title: '结果 一' }]))
    render(withProviders(<SearchPage />))
    await submitQuery('react')
    await screen.findByText('结果 一')
    expect(searchUrls).toHaveLength(1)
    expect(searchUrls[0]).not.toContain('from=')

    // 打开日期面板 → 近 7 天（快捷范围即时应用）
    fireEvent.click(screen.getByTestId('date-panel-toggle'))
    expect(screen.getByTestId('date-panel')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('quick-range-7d'))
    const expected = quickRange('7d')
    await waitFor(() => expect(searchUrls.length).toBe(2))
    expect(searchUrls[1]).toContain(`from=${expected.from}`)
    expect(searchUrls[1]).toContain(`to=${expected.to}`)

    // chip 显示当前范围 + 清除恢复（重新发基础搜索，无 from/to）
    expect(screen.getByTestId('applied-date-label')).toHaveTextContent('近 7 天')
    fireEvent.click(screen.getByRole('button', { name: '清除日期范围「近 7 天」' }))
    await waitFor(() => expect(searchUrls.length).toBe(3))
    expect(searchUrls[2]).not.toContain('from=')
    expect(searchUrls[2]).not.toContain('to=')
    expect(screen.queryByTestId('applied-date-label')).toBeNull()
  })

  it('自定义起止：date input 应用后传参；只填起为单边范围', async () => {
    const searchUrls: string[] = []
    vi.stubGlobal('fetch', mockSearchApiFetch(searchUrls, [{ entryRef: 's1', title: '结果 一' }]))
    render(withProviders(<SearchPage />))
    await submitQuery('react')
    await screen.findByText(/共约 1/)
    fireEvent.click(screen.getByTestId('date-panel-toggle'))
    fireEvent.change(screen.getByLabelText('开始日期'), { target: { value: '2026-09-01' } })
    fireEvent.click(within(screen.getByTestId('date-panel')).getByRole('button', { name: '应用' }))
    // 最终态契约：最近一次带日期的请求是 from=2026-09-01 且无 to（不做
    // 精确计数——base/advanced 两条查询的触发顺序在慢机上有竞态）。
    await waitFor(() => {
      const dated = searchUrls.filter((u) => u.includes('from='))
      expect(dated.length).toBeGreaterThan(0)
      expect(dated[dated.length - 1]!.includes('from=2026-09-01')).toBe(true)
      expect(dated[dated.length - 1]!.includes('to=')).toBe(false)
    })
  })

  it('清除日期后恢复全部结果（基础查询接手）', async () => {
    const searchUrls: string[] = []
    vi.stubGlobal('fetch', mockSearchApiFetch(searchUrls, [{ entryRef: 's1', title: '结果 一' }]))
    render(withProviders(<SearchPage />))
    await submitQuery('react')
    await screen.findByText(/共约 1/)
    fireEvent.click(screen.getByTestId('date-panel-toggle'))
    fireEvent.click(screen.getByTestId('quick-range-today'))
    // 应用范围后至少一次带日期的请求。清除后：日期标签消失、结果仍在；
    // 清除点之后若还有请求，必须是不带日期的基础查询（恢复走缓存时
    // 可零请求——那也是合法实现，不把网络次数当契约）。
    await waitFor(() => expect(searchUrls.some((u) => u.includes('from='))).toBe(true))
    const countBeforeClear = searchUrls.length
    fireEvent.click(screen.getByRole('button', { name: '清除日期范围「今天」' }))
    await waitFor(() => expect(screen.queryByTestId('applied-date-label')).toBeNull())
    expect(screen.getByText(/共约 1/)).toBeInTheDocument()
    for (const url of searchUrls.slice(countBeforeClear)) {
      expect(url.includes('from=')).toBe(false)
    }
  })
})

describe('SearchPage — F29 高级面板', () => {
  it('条件传 intitle/phrase/exclude；chips 显示与逐项清除', async () => {
    const searchUrls: string[] = []
    vi.stubGlobal('fetch', mockSearchApiFetch(searchUrls, [{ entryRef: 's1', title: '结果 一' }]))
    render(withProviders(<SearchPage />))
    await submitQuery('react')
    await screen.findByText(/共约 1/)

    fireEvent.click(screen.getByTestId('advanced-panel-toggle'))
    expect(screen.getByTestId('advanced-panel')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('仅标题'), { target: { value: '指南' } })
    fireEvent.change(screen.getByLabelText('精确短语'), { target: { value: 'use state' } })
    fireEvent.change(screen.getByLabelText('排除词'), { target: { value: 'class' } })
    fireEvent.click(within(screen.getByTestId('advanced-panel')).getByRole('button', { name: '应用' }))

    await waitFor(() => expect(searchUrls.length).toBe(2))
    expect(searchUrls[1]).toContain('intitle=')
    expect(decodeUrl(searchUrls[1])).toContain('intitle=指南')
    expect(decodeUrl(searchUrls[1])).toContain('phrase=use state')
    expect(decodeUrl(searchUrls[1])).toContain('exclude=class')

    // chips 显示 + 逐项清除（全部清完后基础搜索恢复）
    expect(screen.getByText('标题: 指南')).toBeInTheDocument()
    expect(screen.getByText('短语: “use state”')).toBeInTheDocument()
    expect(screen.getByText('排除: class')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '清除排除词「class」' }))
    await waitFor(() => expect(searchUrls.length).toBe(3))
    expect(decodeUrl(searchUrls[2])).not.toContain('exclude=')
    expect(screen.queryByText('排除: class')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '清除标题条件「指南」' }))
    await waitFor(() => expect(searchUrls.length).toBe(4))
    fireEvent.click(screen.getByRole('button', { name: '清除精确短语「use state」' }))
    await waitFor(() => expect(searchUrls.length).toBe(5))
    expect(decodeUrl(searchUrls[4])).not.toContain('intitle=')
    expect(decodeUrl(searchUrls[4])).not.toContain('phrase=')
  })

  it('空查询 + 仅高级条件：诚实提示「请输入至少一个搜索词」且不发请求', async () => {
    const searchUrls: string[] = []
    const fetchMock = mockSearchApiFetch(searchUrls)
    vi.stubGlobal('fetch', fetchMock)
    render(withProviders(<SearchPage />))
    fireEvent.click(screen.getByTestId('advanced-panel-toggle'))
    fireEvent.change(screen.getByLabelText('仅标题'), { target: { value: '指南' } })
    fireEvent.click(within(screen.getByTestId('advanced-panel')).getByRole('button', { name: '应用' }))
    expect(screen.getByTestId('advanced-needs-query')).toHaveTextContent('请输入至少一个搜索词')
    // 从未发出带高级参数的搜索请求
    expect(searchUrls.filter((u) => u.includes('intitle='))).toHaveLength(0)
  })
})

describe('SearchPage — F28 突出匹配词', () => {
  it('命中包裹 <mark>（大小写不敏感）；开关关闭无 mark；换词无残留', async () => {
    const searchUrls: string[] = []
    vi.stubGlobal(
      'fetch',
      mockSearchApiFetch(searchUrls, [{ entryRef: 's1', title: 'React 指南', snippet: '学习 react hooks' }]),
    )
    const { container } = render(withProviders(<SearchPage />))
    await submitQuery('react')
    // 高亮后标题被切分为 mark + 文本节点，用 mark 文本锚定结果已渲染
    await screen.findByText('React')
    // 标题与摘要均出现 mark（大小写不敏感）
    await waitFor(() => expect(container.querySelectorAll('mark').length).toBeGreaterThanOrEqual(2))
    const markTexts = [...container.querySelectorAll('mark')].map((m) => m.textContent)
    expect(markTexts).toContain('React')
    expect(markTexts).toContain('react')

    // 开关关闭：mark 全部消失，文本原样保留
    useAppSettings.getState().update({ searchHighlightMatches: false })
    await waitFor(() => expect(container.querySelectorAll('mark')).toHaveLength(0))
    expect(container.textContent).toContain('React 指南')

    // 换搜索词：无上一次 terms 的残留 mark
    useAppSettings.getState().update({ searchHighlightMatches: true })
    await submitQuery('指南')
    await waitFor(() => {
      const marks = [...container.querySelectorAll('mark')].map((m) => m.textContent)
      expect(marks).toContain('指南')
      expect(marks).not.toContain('React')
    })
  })
})

/** URLSearchParams 的 '+' 空格还原（decodeURIComponent 不处理 '+'）。 */
function decodeUrl(url: string): string {
  return decodeURIComponent(url.replace(/\+/g, ' '))
}

/** 带共享 URL 记录的搜索 fetch mock（默认一页结果）。 */
function mockSearchApiFetch(
  searchUrls: string[],
  items: Partial<SearchResponse['items'][number]>[] = [],
) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/search?')) {
      searchUrls.push(url)
      return Promise.resolve(jsonResponse(searchResponse(items)))
    }
    if (url.startsWith('/api/v1/search/views')) {
      return Promise.resolve(jsonResponse({ items: [] }))
    }
    if (url.startsWith('/api/v1/feeds')) return Promise.resolve(jsonResponse([]))
    return Promise.resolve(jsonResponse({}))
  })
}
