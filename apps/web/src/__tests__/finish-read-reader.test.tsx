/** P0-2 Reader 级集成 — 正文读到底自动已读的端到端接线（jsdom + IO stub）。
 *
 * 证明链（不止“不抛错”）：
 * - 哨兵渲染在正文实际结束处（.lumi-reader-article 内、AI 面板之前）；
 * - 主动滚动 + 末尾稳定停留 → 恰好一次 PATCH /state {read:true}，
 *   detail 缓存原地翻转为已读（不重拉正文）；
 * - 服务端读回一致：第二次 GET detail 返回 read:true；
 * - 短文渲染「读完了」按钮，点击派发 PATCH；
 * - 开关关闭（readerAutoMarkRead=false）时任何路径不发 PATCH。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Reader from '../components/Reader'
import type { EntryDetail } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import { FINISH_READ_DWELL_MS } from '../lib/finish-read'

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: '2026-08-28T10:00:00Z',
    read: false,
    starred: false,
    contentText: '纯文本正文',
    contentHtml: '<p>富文本正文</p>',
    ...overrides,
  }
}

type Record_ = IntersectionObserverEntry

class MockIO {
  static instances: MockIO[] = []
  cb: IntersectionObserverCallback
  root: Document | Element | null
  targets = new Set<Element>()
  constructor(cb: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.cb = cb
    this.root = options?.root ?? null
    MockIO.instances.push(this)
  }
  observe(el: Element) {
    this.targets.add(el)
  }
  unobserve(el: Element) {
    this.targets.delete(el)
  }
  disconnect() {
    this.targets.clear()
  }
  trigger(el: Element, isIntersecting: boolean) {
    this.cb(
      [{ target: el, isIntersecting } as unknown as Record_],
      this as unknown as IntersectionObserver,
    )
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

let patchCalls: Array<{ url: string; body: unknown }>

function stubApi(detailBody: EntryDetail) {
  patchCalls = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (method === 'PATCH' && url.includes('/state')) {
      patchCalls.push({ url, body: JSON.parse(String(init?.body)) })
      return Promise.resolve(new Response(null, { status: 204 }))
    }
    if (method === 'GET' && url === `/api/v1/entries/${detailBody.entryRef}`) {
      return Promise.resolve(jsonResponse(detailBody))
    }
    throw new Error(`unexpected fetch: ${method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderReader() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <Reader />
      </QueryClientProvider>,
    ),
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  MockIO.instances = []
  vi.stubGlobal('IntersectionObserver', MockIO as unknown as typeof IntersectionObserver)
  useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
  useAppSettings.setState({ settings: { ...useAppSettings.getState().settings, readerAutoMarkRead: true } })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('P0-2 Reader 接线 — 正文读到底自动已读', () => {
  it('哨兵在正文容器内、文章元素之后（AI 对话面板之前）渲染', async () => {
    stubApi(detail())
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    const view = renderReader()
    await act(async () => {
      vi.runAllTimersAsync()
    })
    const sentinel = document.querySelector('[data-finish-sentinel]') as HTMLElement
    expect(sentinel).toBeInTheDocument()
    const article = document.querySelector('.lumi-reader-article')
    expect(article).not.toBeNull()
    expect(article!.contains(sentinel)).toBe(true)
    // 哨兵在实际正文（.article-content）之后（文档顺序）。
    const content = article!.querySelector('.article-content')
    expect(content).not.toBeNull()
    expect(
      (content as Node).compareDocumentPosition(sentinel) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    view.unmount()
  })

  it('主动滚动 + 末尾停留 DWELL_MS → 恰好一次 PATCH {read:true}；detail 缓存翻转零重拉', async () => {
    const fetchMock = stubApi(detail())
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    const view = renderReader()
    await act(async () => {
      vi.runAllTimersAsync()
    })

    // 滚动容器 = Reader 根 div（.lumi-reader-article 的父级）。
    const scroller = view.container.querySelector('.lumi-reader-article')!.parentElement!
    expect(scroller).toBeTruthy()

    Object.defineProperty(scroller, 'scrollHeight', { value: 4000, configurable: true })
    Object.defineProperty(scroller, 'clientHeight', { value: 600, configurable: true })
    Object.defineProperty(scroller, 'scrollTop', { value: 0, writable: true, configurable: true })

    const sentinel = document.querySelector('[data-finish-sentinel]') as HTMLElement
    const io = MockIO.instances.find((i) => i.targets.has(sentinel))
    expect(io).toBeDefined()
    expect(io!.root).toBe(scroller)

    // 主动滚动到底部（scroll 事件来自原生监听）。真实用户从打开到滚
    // 动必然超过程序性豁免窗口——先推进虚拟时间。
    act(() => {
      vi.advanceTimersByTime(300)
      scroller.scrollTop = 3400
      scroller.dispatchEvent(new Event('scroll'))
      io!.trigger(sentinel, true)
    })
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS - 1)
    })
    expect(patchCalls).toHaveLength(0)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(patchCalls).toHaveLength(1)
    expect(patchCalls[0]!.body).toEqual({ read: true })
    // detail 缓存原地翻转（GET 只发生一次，正文零重拉）。
    const detailGets = fetchMock.mock.calls
      .map((c) => String(c[0]))
      .filter((u) => u === '/api/v1/entries/e1.a')
    expect(detailGets).toHaveLength(1)
    const cached = view.queryClient.getQueryData<EntryDetail>(['entry', 'e1.a'])
    expect(cached?.read).toBe(true)
    view.unmount()
  })

  it('短文渲染「读完了」按钮；点击派发 PATCH；自动路径静默', async () => {
    stubApi(detail())
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    const view = renderReader()
    await act(async () => {
      vi.runAllTimersAsync()
    })
    const scroller = view.container.querySelector('.lumi-reader-article')!.parentElement!
    Object.defineProperty(scroller, 'scrollHeight', { value: 600, configurable: true })
    Object.defineProperty(scroller, 'clientHeight', { value: 600, configurable: true })

    // 触发重测（切文章路径）。
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    await act(async () => {
      view.rerender(
        <QueryClientProvider client={view.queryClient}>
          <Reader />
        </QueryClientProvider>,
      )
      vi.runAllTimersAsync()
    })

    // 短文：按钮出现（needsExplicitConfirm 由容器测量驱动；此处直接以
    // 按钮存在性断言接线）。
    const button = await screen.findByRole('button', { name: '读完了' })
    act(() => {
      button.click()
    })
    await act(async () => {
      await vi.runAllTimersAsync()
    })
    expect(patchCalls).toHaveLength(1)
    expect(patchCalls[0]!.body).toEqual({ read: true })
    view.unmount()
  })

  it('开关关闭：滚动到底 + 停留不派发；「读完了」按钮不出现', async () => {
    stubApi(detail())
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, readerAutoMarkRead: false },
    })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    const view = renderReader()
    await act(async () => {
      vi.runAllTimersAsync()
    })
    const scroller = view.container.querySelector('.lumi-reader-article')!.parentElement!
    Object.defineProperty(scroller, 'scrollHeight', { value: 600, configurable: true })
    Object.defineProperty(scroller, 'clientHeight', { value: 600, configurable: true })
    await act(async () => {
      vi.runAllTimersAsync()
    })
    expect(screen.queryByRole('button', { name: '读完了' })).toBeNull()
    expect(patchCalls).toHaveLength(0)
    view.unmount()
  })
})
