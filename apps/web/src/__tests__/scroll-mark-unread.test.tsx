/** 滚动标记已读正式化测试 — 0017 Gate 4。
 *
 * 用可控 IntersectionObserver mock 验证保守策略：
 * - 默认关闭：任何 intersect 都不产生标记；
 * - 开启后：先进入视口（seen）再完全滚出上方 + 400ms settle 停顿 → PATCH read:true；
 * - settle 窗口内滚回视口 → 取消（不标记）；
 * - 手动未读（列表数据 read true→false）的条目，在重新滚入视口前不被自动标记；
 * - 同一条目不重复派发。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EntryListResponse, EntryListItem } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import EntryList from '../components/EntryList'

const SETTLE_MS = 400

function item(ref: string, over: Partial<EntryListItem> = {}): EntryListItem {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: '2026-08-30T00:00:00Z',
    read: false,
    starred: false,
    ...over,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

type Record_ = IntersectionObserverEntry

class MockIO {
  static instances: MockIO[] = []
  cb: IntersectionObserverCallback
  elements = new Map<Element, boolean>()
  constructor(cb: IntersectionObserverCallback) {
    this.cb = cb
    MockIO.instances.push(this)
  }
  observe(el: Element) {
    this.elements.set(el, false)
  }
  unobserve(el: Element) {
    this.elements.delete(el)
  }
  disconnect() {
    this.elements.clear()
  }
  fire(entryRef: string, isIntersecting: boolean, bottom: number) {
    const el = [...this.elements.keys()].find(
      (k) => k.getAttribute('data-entry-row-ref') === entryRef,
    )
    if (!el) return
    const record = {
      target: el,
      isIntersecting,
      boundingClientRect: { bottom },
    } as unknown as Record_
    this.elements.set(el, isIntersecting)
    this.cb([record], this as unknown as IntersectionObserver)
  }
}

function fireForRef(entryRef: string, isIntersecting: boolean, bottom: number) {
  for (const io of MockIO.instances) {
    if ([...io.elements.keys()].some((k) => k.getAttribute('data-entry-row-ref') === entryRef)) {
      io.fire(entryRef, isIntersecting, bottom)
    }
  }
}

function setup(getEntries: () => EntryListItem[], statePatches: { url: string; init?: RequestInit }[]) {
  MockIO.instances = []
  vi.stubGlobal(
    'IntersectionObserver',
    MockIO as unknown as typeof IntersectionObserver,
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  useReaderUi.setState({
    section: 'home',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })

  const fetcher = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    // 状态写优先于列表 GET（/state PATCH 路径也以 /api/v1/entries 开头）
    if (init?.method === "PATCH" && url.includes("/state")) {
      statePatches.push({ url, init })
      return new Response(null, { status: 204 })
    }
    if (url.startsWith('/api/v1/feeds')) return jsonResponse([])
    if (url.startsWith('/api/v1/entries')) {
      return jsonResponse({ items: getEntries(), nextCursor: null } as EntryListResponse)
    }
    throw new Error(`unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)

  const renderResult = render(
    <QueryClientProvider client={qc}>
      <EntryList />
    </QueryClientProvider>,
  )
  return { qc, renderResult, fetcher }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

beforeEach(() => {
  localStorage.clear()
  useAppSettings.getState().reset()
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('scrollMarkUnread（0017 正式化）', () => {
  it('默认关闭：滚过也不标记', async () => {
    const patches: { url: string }[] = []
    setup(() => [item('a1'), item('a2')], patches)
    await screen.findAllByText('文章 a1')

    fireForRef('a1', true, 100)
    fireForRef('a1', false, -100)
    await sleep(SETTLE_MS + 200)
    expect(patches.filter((p) => p.url.includes('/state'))).toHaveLength(0)
  })

  it('开启：seen → 滚出上方 → settle 后标记 read:true', async () => {
    useAppSettings.getState().update({ scrollMarkUnread: true })
    const patches: { url: string; init?: RequestInit; at?: number }[] = []
    setup(() => [item('b1'), item('b2')], patches)
    await screen.findAllByText('文章 b1')

    fireForRef('b1', true, 100)
    fireForRef('b1', false, -100)
    // settle 窗口未到 → 尚未标记
    await sleep(100)
    expect(patches.filter((p) => p.url.includes('/state'))).toHaveLength(0)
    // 过 settle → 标记
    await waitFor(async () => {
      await sleep(SETTLE_MS + 100)
      expect(patches.filter((p) => p.url.includes('/state'))).toHaveLength(1)
    })
    const patch = patches.find((p) => p.url.includes('/state'))!
    expect(JSON.parse(String(patch.init?.body))).toEqual({ read: true })
  })

  it('settle 窗口内滚回视口 → 取消标记', async () => {
    useAppSettings.getState().update({ scrollMarkUnread: true })
    const patches: { url: string }[] = []
    setup(() => [item('c1'), item('c2')], patches)
    await screen.findAllByText('文章 c1')

    fireForRef('c1', true, 100)
    fireForRef('c1', false, -100)
    await sleep(150) // 未过 settle
    fireForRef('c1', true, 50) // 滚回
    await sleep(SETTLE_MS + 200)
    expect(patches.filter((p) => p.url.includes('/state'))).toHaveLength(0)
  })

  it('滚到下方（未离开上沿）不标记', async () => {
    useAppSettings.getState().update({ scrollMarkUnread: true })
    const patches: { url: string }[] = []
    setup(() => [item('d1'), item('d2')], patches)
    await screen.findAllByText('文章 d1')

    // 离开视口但还在视口下方（bottom > viewport，不会 < 0）
    fireForRef('d1', true, 100)
    fireForRef('d1', false, 900)
    await sleep(SETTLE_MS + 200)
    expect(patches.filter((p) => p.url.includes('/state'))).toHaveLength(0)
  })

  it('手动未读（read true→false）的条目重新滚出不自动标记', async () => {
    useAppSettings.getState().update({ scrollMarkUnread: true })
    const patches: { url: string }[] = []
    // 该条目先已读（用户曾滚过并被标记 / 手动已读），后变为未读（Reader 标记未读）
    let reads = true
    const { qc } = setup(
      () => [item('e1', { read: reads }), item('e2')],
      patches,
    )
    await screen.findAllByText('文章 e1')

    // 用户曾滚过它（seen）
    fireForRef('e1', true, 100)
    fireForRef('e1', false, -100) // 已读状态 → 不满足 read===false，不标记
    await sleep(SETTLE_MS + 100)
    expect(patches.filter((p) => p.url.includes('/state'))).toHaveLength(0)

    // 用户在 Reader 手动标记未读 → 数据 true→false（refetch）
    reads = false
    await qc.invalidateQueries({ queryKey: ['entries'] })
    await sleep(100)

    // 重新触发「滚出上方」记录（新 observer 初始回调 / 继续滚动）：
    // 受手动未读保护，不应自动标记
    fireForRef('e1', false, -120)
    await sleep(SETTLE_MS + 200)
    expect(patches.filter((p) => p.url.includes('/state'))).toHaveLength(0)

    // 重新滚入视口后再滚出（新一轮阅读）→ 可以标记
    fireForRef('e1', true, 100)
    fireForRef('e1', false, -120)
    await waitFor(async () => {
      await sleep(SETTLE_MS + 100)
      expect(patches.filter((p) => p.url.includes('/state'))).toHaveLength(1)
    })
  })
})
