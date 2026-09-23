/** N031/N032/N034/N040 — 采集可靠性 Web 侧行为测试。
 *
 * - N031：修订面板（有修订 → 入口+计数+摘要行；无修订 → 零渲染）；
 * - N032：正文明显变短 → 版本选择条；切换到「上次完整版本」经同一
 *   sanitize 管线渲染（脚本内容不出现——DOMPurify 边界不变）；
 * - N034：时间存疑徽标（tooltip 说明哪类异常）；排序切换到「按接收
 *   时间」→ 请求真实携带 sort=received（服务端执行）；
 * - N040：采集三时点行 + 最大延迟环节提示；FreshRSS 未提供 →
 *   「未提供 by upstream」。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import EntryRevisionsPanel from '../components/EntryRevisionsPanel'
import EntryRow from '../components/EntryRow'
import { VolumeOverview } from '../components/VolumeOverview'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail, EntryListItem } from '../api/types'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '标题',
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-18T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: '<p>正文内容。</p>',
    contentText: '正文内容。',
    ...overrides,
  } as unknown as EntryDetail
}

function entryItem(overrides: Partial<EntryListItem> = {}): EntryListItem {
  return {
    entryRef: 'e1.x',
    title: '文章 X',
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

function renderUi(node: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>)
}

afterEach(() => {
  vi.unstubAllGlobals()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

// ---------------------------------------------------------------------------
// N031 修订面板
// ---------------------------------------------------------------------------

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    getEntryRevisions: vi.fn(),
  }
})

import { getEntryRevisions } from '../api/client'
import { timeCredibilityExplanation } from '../lib/time-credibility'

describe('N031 EntryRevisionsPanel', () => {
  it('有修订 → 入口 + 计数 + 摘要行（含改前/改后摘录）', async () => {
    vi.mocked(getEntryRevisions).mockResolvedValue({
      entryRef: 'e1.a',
      revisions: [
        {
          id: 2,
          capturedAt: '2026-09-21T08:00:00Z',
          titleChanged: false,
          prevTitle: null,
          newTitle: null,
          summary: {
            basis: 'retained_variant',
            headingsChanged: -1,
            paragraphsChanged: 1,
            linksChanged: 0,
            excerptPrev: '旧的第二段内容',
            excerptNew: '修订后的第二段内容',
          },
          prevHash: 'aa',
          newHash: 'bb',
        },
      ],
    } as never)
    renderUi(<EntryRevisionsPanel entryRef="e1.a" />)
    await waitFor(() => expect(screen.getByTestId('entry-revisions-count')).toBeDefined())
    fireEvent.click(screen.getByTestId('entry-revisions-trigger'))
    const items = await screen.findAllByTestId('entry-revision-item')
    expect(items).toHaveLength(1)
    expect(screen.getByTestId('revision-paragraphsChanged').textContent).toContain('+1')
    expect(screen.getByTestId('revision-headingsChanged').textContent).toContain('-1')
    expect(screen.getByText('修订后的第二段内容')).toBeDefined()
  })

  it('无修订 → 零渲染（不占空间）', async () => {
    vi.mocked(getEntryRevisions).mockResolvedValue({
      entryRef: 'e1.a',
      revisions: [],
    } as never)
    const { container } = renderUi(<EntryRevisionsPanel entryRef="e1.a" />)
    await waitFor(() =>
      expect(vi.mocked(getEntryRevisions)).toHaveBeenCalled(),
    )
    await waitFor(() => expect(container.querySelector('details')).toBeNull())
  })
})

// ---------------------------------------------------------------------------
// N032 内容变体切换（同一 sanitize 管线）
// ---------------------------------------------------------------------------

describe('N032 ArticleContent 版本选择', () => {
  it('明显变短 → 提示条 + 切换到上次完整版本渲染其内容', async () => {
    const d = detail({
      contentHtml: '<p>只剩一小段。</p>',
      contentVariants: {
        triggered: true,
        currentLength: 10,
        maxLength: 5000,
        variants: [
          { kind: 'current', label: '上游当前', capturedAt: null, contentHtml: '<p>只剩一小段。</p>', lengthChars: 10 },
          {
            kind: 'last_known_full',
            label: '上次完整版本',
            capturedAt: '2026-09-20T00:00:00Z',
            contentHtml: '<p>完整版本第一段。</p><p>完整版本第二段。</p>',
            lengthChars: 5000,
          },
        ],
      },
    } as Partial<EntryDetail>)
    useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
    renderUi(<ArticleContent detail={d} />)
    expect(screen.getByTestId('content-variants-bar').textContent).toContain('当前正文明显变短')
    // 默认渲染当前版本
    expect(screen.getByText('只剩一小段。').textContent).toBeDefined()
    fireEvent.click(screen.getByTestId('variant-last-full'))
    await waitFor(() =>
      expect(screen.getByText('完整版本第二段。')).toBeDefined(),
    )
    // 提示条如实显示两个选项（capturedAt 日期出现在按钮文案）
    expect(screen.getByTestId('variant-last-full').textContent).toContain('2026-09-20')
  })

  it('脚本内容在两种版本下都被清洗（同一 sanitize 边界）', async () => {
    const d = detail({
      contentHtml: '<p>短的当前版本</p>',
      contentVariants: {
        triggered: true,
        currentLength: 8,
        maxLength: 500,
        variants: [
          { kind: 'current', label: '上游当前', capturedAt: null, contentHtml: '<p>短的当前版本</p>', lengthChars: 8 },
          {
            kind: 'last_known_full',
            label: '上次完整版本',
            capturedAt: '2026-09-20T00:00:00Z',
            contentHtml: '<p>完整正文</p><script>window.alert(1)</script>',
            lengthChars: 500,
          },
        ],
      },
    } as Partial<EntryDetail>)
    renderUi(<ArticleContent detail={d} />)
    fireEvent.click(screen.getByTestId('variant-last-full'))
    await waitFor(() => expect(screen.getByText('完整正文')).toBeDefined())
    expect(document.querySelector('.article-content script')).toBeNull()
  })

  it('未触发 → 无提示条', () => {
    renderUi(<ArticleContent detail={detail()} />)
    expect(screen.queryByTestId('content-variants-bar')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// N034 时间存疑徽标 + 按接收时间排序
// ---------------------------------------------------------------------------

describe('N034 时间可信度', () => {
  it('异常 → 徽标 + tooltip 说明哪类；正常 → 无徽标', () => {
    const bad = renderUi(
      <EntryRow item={entryItem({ timeCredibility: 'future' })} selected={false} />,
    )
    const badge = screen.getByTestId('time-credibility-badge')
    expect(badge.getAttribute('title')).toContain('发布时间在未来')
    bad.unmount()
    renderUi(<EntryRow item={entryItem({})} selected={false} />)
    expect(screen.queryByTestId('time-credibility-badge')).toBeNull()
  })

  it('组合异常代码展开为可读解释', () => {
    expect(timeCredibilityExplanation('missing,no_timezone')).toBe(
      '发布时间缺失；发布时间未标明时区',
    )
  })

  it('排序切换到「按接收时间」→ 请求真实携带 sort=received', async () => {
    const entryUrls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/v1/entries?')) entryUrls.push(url)
        if (url.includes('/api/v1/feeds')) return Promise.resolve(jsonResponse([]))
        return Promise.resolve(jsonResponse({ items: [], nextCursor: null, filteredCount: null }))
      }),
    )
    useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
    const EntryList = (await import('../components/EntryList')).default
    const view = renderUi(<EntryList />)
    const toggle = await view.findByTestId('timeline-order-toggle')
    // 最新优先 → 最早优先（客户端重排）
    fireEvent.click(toggle)
    // 最早优先 → 按接收时间（服务端排序）
    fireEvent.click(toggle)
    expect(screen.getByTestId('timeline-order-received-note')).toBeDefined()
    await waitFor(() =>
      expect(entryUrls.some((u) => u.includes('sort=received'))).toBe(true),
    )
    expect(toggle.textContent).toContain('按接收时间')
  })
})

// ---------------------------------------------------------------------------
// N040 采集时点面板
// ---------------------------------------------------------------------------

describe('N040 VolumeOverview 三时点块', () => {
  function stubVolume(item: unknown) {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/v1/sources/volume')) {
          return Promise.resolve(jsonResponse({ items: [item], days: 7 }))
        }
        return Promise.resolve(jsonResponse({}))
      }),
    )
  }

  it('三个时点行 + 最大延迟环节提示', async () => {
    stubVolume({
      feedUrl: 'https://t.example/rss',
      title: '科技源',
      publishedCount: 3,
      lastPublishedAt: '2026-09-03T00:00:00Z',
      lastSyncedAt: '2026-09-04T02:00:00Z',
      collectionTiming: {
        upstreamPublishedLatest: '2026-09-03T00:00:00Z',
        freshrssFetchedLatest: '2026-09-03T12:00:00Z',
        freshrssFetchedBasis: 'crawlTimestampMsec（FreshRSS 首次收录，非周期抓取时间）',
        lumiProjectedLatest: '2026-09-04T02:00:00Z',
        latencyHint: 'FreshRSS 收录→Lumi 投影 ≈14.0 小时',
      },
    })
    const view = renderUi(<VolumeOverview />)
    fireEvent.click(view.getByText('收件量概览'))
    const timing = await view.findByTestId('collection-timing')
    expect(timing.textContent).toContain('上游发布')
    expect(timing.textContent).toContain('FreshRSS 收录')
    expect(timing.textContent).toContain('Lumi 投影')
    expect(screen.getByTestId('timing-freshrss').textContent).toContain('2026-09-03')
    expect(screen.getByTestId('timing-hint').textContent).toContain('≈14.0 小时')
  })

  it('FreshRSS 未提供收录时间 → 「未提供 by upstream」，无环节提示', async () => {
    stubVolume({
      feedUrl: 'https://n.example/rss',
      title: '无收录时间源',
      publishedCount: 1,
      lastPublishedAt: '2026-09-01T00:00:00Z',
      lastSyncedAt: '2026-09-02T00:00:00Z',
      collectionTiming: {
        upstreamPublishedLatest: '2026-09-01T00:00:00Z',
        freshrssFetchedLatest: null,
        freshrssFetchedBasis: '未提供 by upstream',
        lumiProjectedLatest: '2026-09-02T00:00:00Z',
        latencyHint: null,
      },
    })
    const view = renderUi(<VolumeOverview />)
    fireEvent.click(view.getByText('收件量概览'))
    await view.findByTestId('collection-timing')
    expect(screen.getByTestId('timing-freshrss').textContent).toContain('未提供 by upstream')
    expect(screen.queryByTestId('timing-hint')).toBeNull()
  })
})
