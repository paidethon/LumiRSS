/** F055 消费端 — per-source 阅读样式覆盖（readerStyle 三键）合并进
 * 阅读样式管线：
 * - 覆盖仅作用于匹配来源的 entry（其它来源/无配置 → 全局，零内联变量）；
 * - 全局仍是基础：未覆盖的键不内联（继承根节点全局 CSS 变量）；
 * - width 移动端忽略（桌面端应用）；
 * - 越界/非法值不应用（诚实退回全局）。 */

import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Reader from '../components/Reader'
import type { EntryDetail } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import {
  readerStyleCssVars,
  resolveSourceReaderStyle,
} from '../lib/source-reader-style'

// ---- 纯函数：合并语义 ----

describe('F055 resolveSourceReaderStyle 合并语义', () => {
  const overrides = [
    { feedUrl: 'https://a.example/feed.xml', readerStyle: { fontSize: 21, lineHeight: 2.2, width: 900 } },
    { feedUrl: 'https://b.example/feed.xml', readerStyle: { fontSize: 13 } },
    { feedUrl: 'https://c.example/feed.xml', readerStyle: null },
  ]

  it('F055: 覆盖仅作用于匹配来源的 entry；其它来源/无覆盖 → null（跟随全局）', () => {
    const hit = resolveSourceReaderStyle('https://a.example/feed.xml', overrides, { isMobile: false })
    expect(hit).toEqual({ fontSize: 21, lineHeight: 2.2, width: 900 })
    // 未出现在覆盖列表中的来源 → 全局
    expect(resolveSourceReaderStyle('https://other.example/feed.xml', overrides, { isMobile: false })).toBeNull()
    // 匹配但 readerStyle 为 null（恢复跟随全局）→ null
    expect(resolveSourceReaderStyle('https://c.example/feed.xml', overrides, { isMobile: false })).toBeNull()
    // feedUrl 缺失 / 列表未加载 → null
    expect(resolveSourceReaderStyle(null, overrides, { isMobile: false })).toBeNull()
    expect(resolveSourceReaderStyle('https://a.example/feed.xml', undefined, { isMobile: false })).toBeNull()
  })

  it('F055: width 移动端忽略，桌面端应用；子集逐键生效', () => {
    const desktop = resolveSourceReaderStyle('https://a.example/feed.xml', overrides, { isMobile: false })
    expect(desktop?.width).toBe(900)
    const mobile = resolveSourceReaderStyle('https://a.example/feed.xml', overrides, { isMobile: true })
    expect(mobile).toEqual({ fontSize: 21, lineHeight: 2.2 })
    // 仅覆盖宽度 → 移动端等于没有任何覆盖
    const onlyWidth = [{ feedUrl: 'w', readerStyle: { width: 1000 } }]
    expect(resolveSourceReaderStyle('w', onlyWidth, { isMobile: true })).toBeNull()
    expect(resolveSourceReaderStyle('w', onlyWidth, { isMobile: false })).toEqual({ width: 1000 })
  })

  it('F055: 越界/非法值不应用（与 BFF validate_reader_style 区间一致）', () => {
    const bad = [
      { feedUrl: 'x', readerStyle: { fontSize: 99, lineHeight: 0.5, width: 'auto' } },
    ] as unknown as [{ feedUrl: string; readerStyle: Record<string, number> }]
    expect(resolveSourceReaderStyle('x', bad, { isMobile: false })).toBeNull()
    const partial = [{ feedUrl: 'y', readerStyle: { fontSize: 44, lineHeight: 1.8 } }] as unknown as [{ feedUrl: string; readerStyle: Record<string, number> }]
    // fontSize 越界丢弃，lineHeight 合法保留（逐键防御）
    expect(resolveSourceReaderStyle('y', partial, { isMobile: false })).toEqual({ lineHeight: 1.8 })
  })

  it('F055: readerStyleCssVars 只内联覆盖的键（全局仍是基础）', () => {
    expect(readerStyleCssVars(null)).toEqual({})
    expect(readerStyleCssVars({ fontSize: 21 })).toEqual({ '--lumi-reader-font-size': '21px' })
    expect(readerStyleCssVars({ fontSize: 21, lineHeight: 2.2, width: 900 })).toEqual({
      '--lumi-reader-font-size': '21px',
      '--lumi-reader-line-height': '2.2',
      '--lumi-reader-content-width': '900px',
    })
  })
})

// ---- 组件级：Reader 打开条目时按 feed 匹配 ----

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: '作者甲',
    url: 'https://example.com/a',
    publishedAt: '2026-08-28T10:00:00Z',
    read: false,
    starred: false,
    contentText: '纯文本正文 A',
    contentHtml: '<p>富文本正文 <strong>A</strong></p>',
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderReader() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <Reader />
    </QueryClientProvider>,
  )
}

function stubApis(overridesBody: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url === '/api/v1/entries/e1.a') {
        return jsonResponse(detail({ feedUrl: 'https://a.example/feed.xml' }))
      }
      if (method === 'GET' && url === '/api/v1/sources/overrides') {
        return jsonResponse(overridesBody)
      }
      if (method === 'PATCH' && url.includes('/state')) {
        return new Response(null, { status: 204 })
      }
      // 其余查询（进度等）→ 空 200，避免测试噪声
      return jsonResponse({})
    }),
  )
}

beforeEach(() => {
  useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F055 Reader 消费端接线', () => {
  it('F055: 打开匹配来源的 entry → 正文容器内联覆盖变量；非匹配来源 entry 不受影响', async () => {
    stubApis({
      items: [
        {
          feedUrl: 'https://a.example/feed.xml',
          readerStyle: { fontSize: 21, lineHeight: 2.2, width: 900 },
        },
        { feedUrl: 'https://z.example/feed.xml', readerStyle: { fontSize: 13 } },
      ],
    })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    const { container } = renderReader()
    await screen.findByText('文章 A')
    const article = await waitFor(() => {
      const el = container.querySelector('article.lumi-reader-article') as HTMLElement | null
      expect(el).not.toBeNull()
      return el as HTMLElement
    })
    // F055：匹配来源的覆盖以内联 CSS 变量作用于本篇
    expect(article.style.getPropertyValue('--lumi-reader-font-size')).toBe('21px')
    expect(article.style.getPropertyValue('--lumi-reader-line-height')).toBe('2.2')
    // jsdom 无 matchMedia → 视为移动端 → width 被忽略
    expect(article.style.getPropertyValue('--lumi-reader-content-width')).toBe('')
    expect(article.style.maxWidth).toContain('var(--lumi-reader-content-width')
  })

  it('F055: 覆盖属于其它来源 → 打开本篇不内联任何覆盖变量（诚实跟随全局）', async () => {
    stubApis({
      items: [
        { feedUrl: 'https://z.example/feed.xml', readerStyle: { fontSize: 13 } },
      ],
    })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    const { container } = renderReader()
    await screen.findByText('文章 A')
    await waitFor(() => {
      const el = container.querySelector('article.lumi-reader-article') as HTMLElement | null
      expect(el).not.toBeNull()
      expect(el?.style.getPropertyValue('--lumi-reader-font-size')).toBe('')
    })
  })
})
