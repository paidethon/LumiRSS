/** N060 — 正文版本切换定位。内容源切换（N032 版本条 / 提取试读）后：
 * findAnchorElement 命中原段落 → 回到原位（无提示）；匹配失败 → 按
 * 切换前滚动比例取最近标题 + 诚实提示「已定位到最近标题」；绝不到
 * 文末、绝不标记已读（Reader 级证明 PATCH 零调用）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import Reader from '../components/Reader'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'
import { forgetReadingPositionsForTest } from '../lib/reading-position'
import type { EntryDetail } from '../api/types'

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '版本文章',
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-24T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: '<p>正文</p>',
    contentText: '正文',
    ...overrides,
  } as unknown as EntryDetail
}

const OLD_HTML = '<h2>章节一</h2><p>开头段落甲</p><p>共享段落乙</p><p>结尾段落丙</p>'
const NEW_HTML_WITH_ANCHOR = '<h2>章节一</h2><p>共享段落乙</p><p>更多内容丁</p>'
const NEW_HTML_NO_ANCHOR =
  '<h2>新章一</h2><p>新甲段落</p><h2>新章二</h2><p>新乙段落</p><h2>新章三</h2><p>新丙段落</p><h2>新章四</h2><p>新丁段落</p>'

const OLD_ANCHOR_TOP: Array<[string, number]> = [
  ['章节一', 0],
  ['开头段落甲', 10],
  ['共享段落乙', 60],
  ['结尾段落丙', 500],
]

function stubRects(byText: Array<[string, number]>, scrollerTop = 0) {
  const original = Element.prototype.getBoundingClientRect
  Element.prototype.getBoundingClientRect = function (this: Element) {
    const text = (this.textContent ?? '').replace(/\s+/g, ' ').trim()
    for (const [prefix, top] of byText) {
      if (text.startsWith(prefix)) return { top, bottom: top, height: 0 } as DOMRect
    }
    return { top: scrollerTop, bottom: scrollerTop, height: 0 } as DOMRect
  }
  return () => {
    Element.prototype.getBoundingClientRect = original
  }
}

function stubScrollerLayout(node: HTMLElement, scrollTop: number) {
  Object.defineProperty(node, 'scrollHeight', { value: 1200, configurable: true })
  Object.defineProperty(node, 'clientHeight', { value: 600, configurable: true })
  Object.defineProperty(node, 'scrollTop', { value: scrollTop, writable: true, configurable: true })
}

function variantsOf(contentHtml: string) {
  return {
    triggered: true,
    currentLength: 10,
    maxLength: 5000,
    variants: [
      { kind: 'current', label: '上游当前', capturedAt: null, contentHtml: OLD_HTML, lengthChars: 10 },
      { kind: 'last_known_full', label: '上次完整版本', capturedAt: '2026-09-20T00:00:00Z', contentHtml, lengthChars: 5000 },
    ],
  }
}

function renderArticle(d: EntryDetail) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <div>
        <div className="lumi-reader-article">
          <ArticleContent detail={d} />
        </div>
      </div>
    </QueryClientProvider>,
  )
}

function scroller(): HTMLElement {
  return document.querySelector('.lumi-reader-article')!.parentElement!
}

beforeEach(() => {
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS, readerCodeHighlight: 'off' } })
  forgetReadingPositionsForTest()
  useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  const nav = window.navigator as unknown as Record<string, unknown>
  delete nav.clipboard
})

describe('N060 ArticleContent 版本切换重锚定', () => {
  it('切换后锚点段落仍存在 → 回到同一段落位置（无提示）', async () => {
    const restore = stubRects(OLD_ANCHOR_TOP)
    renderArticle(detail({ contentHtml: OLD_HTML, contentVariants: variantsOf(NEW_HTML_WITH_ANCHOR) }))
    expect(await screen.findByText('开头段落甲')).toBeInTheDocument()
    stubScrollerLayout(scroller(), 300)
    fireEvent.click(screen.getByTestId('variant-last-full'))

    // 新版本渲染完成后：锚点「共享段落乙」仍在 → top(60) − scroller.top(0)
    // + 当前 scrollTop(300) − 12
    await waitFor(() => expect(screen.getByText('更多内容丁')).toBeInTheDocument())
    await waitFor(() => expect(scroller().scrollTop).toBe(60 + 300 - 12))
    expect(screen.queryByTestId('anchor-notice')).toBeNull()
    restore()
  })

  it('锚点匹配失败 → 按比例取最近标题 + 「已定位到最近标题」提示（绝不到文末）', async () => {
    const restore = stubRects([
      ...OLD_ANCHOR_TOP,
      ['新章一', 0],
      ['新章二', 80],
      ['新章三', 160],
      ['新章四', 240],
    ])
    renderArticle(detail({ contentHtml: OLD_HTML, contentVariants: variantsOf(NEW_HTML_NO_ANCHOR) }))
    expect(await screen.findByText('开头段落甲')).toBeInTheDocument()
    stubScrollerLayout(scroller(), 300) // max = 600 → ratio = 0.5
    fireEvent.click(screen.getByTestId('variant-last-full'))

    await waitFor(() => expect(screen.getByText('新甲段落')).toBeInTheDocument())
    // ratio 0.5 × 4 个标题 → index 2 = 「新章三」；top(160) + 300 − 12 = 448
    await waitFor(() => expect(scroller().scrollTop).toBe(160 + 300 - 12))
    expect(screen.getByTestId('anchor-notice').textContent).toBe('已定位到最近标题')
    // 绝不到文末（max = 600）
    expect(scroller().scrollTop).toBeLessThan(600)
    restore()
  })
})

// ---- Reader 级：切换 + 重锚定绝不标记已读 ----

describe('N060 Reader 级：版本切换不标记已读', () => {
  it('已读 PATCH 全程零调用；重锚定后位置仍在本篇中部（不到文末哨兵）', async () => {
    let patchCalls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if ((init?.method ?? 'GET') === 'GET' && url === '/api/v1/entries/e1.a') {
          return Promise.resolve(
            new Response(
              JSON.stringify(
                detail({ contentHtml: OLD_HTML, contentVariants: variantsOf(NEW_HTML_NO_ANCHOR) }),
              ),
              { status: 200, headers: { 'content-type': 'application/json' } },
            ),
          )
        }
        if (init?.method === 'PATCH' && url.includes('/state')) {
          patchCalls += 1
          return Promise.resolve(new Response(null, { status: 204 }))
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )
    useAppSettings.setState({
      settings: { ...DEFAULT_APP_SETTINGS, readerAutoMarkRead: true, readerCodeHighlight: 'off' },
    })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={qc}>
        <Reader />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('开头段落甲', {}, { timeout: 5000 })).toBeInTheDocument()
    stubScrollerLayout(scroller(), 300)

    fireEvent.click(screen.getByTestId('variant-last-full'))
    await waitFor(() => expect(screen.getByText('新甲段落')).toBeInTheDocument())
    // 重锚定生效（落在按比例的最近标题上）
    await waitFor(() => expect(screen.getByTestId('anchor-notice')).toBeInTheDocument())
    // 全程零 PATCH：切换 + 重锚定不是「读完」语义
    expect(patchCalls).toBe(0)
    // 且位置在可滚动区间中部，绝未被推到文末（max = 600）
    expect(scroller().scrollTop).toBeLessThan(600)
  })
})
