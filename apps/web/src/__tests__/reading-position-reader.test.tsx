/** 阅读位置恢复 — Reader 集成回归（pool #01）。
 *
 * jsdom 没有布局：断言用「先渲染 → 手动撑起 scrollHeight → 切换触发
 * 恢复 effect」的顺序锁定可观察行为——返回已读文章时按保存的 ratio
 * 恢复 scrollTop，返回无记录文章时回到顶部；滚动会按当前 entryRef
 * 保存。已读状态不受滚动保存影响。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Reader from '../components/Reader'
import type { EntryDetail } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import {
  forgetReadingPositionsForTest,
  loadReadingPosition,
  saveReadingPosition,
} from '../lib/reading-position'

function detail(entryRef: string, title: string): EntryDetail {
  return {
    entryRef,
    title,
    feedTitle: '示例源',
    author: null,
    url: 'https://example.com/a',
    publishedAt: '2026-08-28T10:00:00Z',
    read: false,
    starred: false,
    contentText: '纯文本正文',
    contentHtml: `<p>${title}第一段</p><p>${title}第二段</p><p>${title}第三段</p>`,
  }
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

function renderReader() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <Reader />
    </QueryClientProvider>,
  )
}

function stubDetails() {
  const details: Record<string, EntryDetail> = {
    'e1.a': detail('e1.a', '文章甲'),
    'e1.b': detail('e1.b', '文章乙'),
  }
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      const ref = url.split('/api/v1/entries/')[1]
      return Promise.resolve(jsonResponse(details[ref]))
    }),
  )
}

function scroller(): HTMLElement {
  return document.querySelector('.lumi-reader')!.closest('div')!
}

function giveLayout(el: HTMLElement) {
  Object.defineProperty(el, 'scrollHeight', { value: 2000, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: 800, configurable: true })
}

beforeEach(() => {
  forgetReadingPositionsForTest()
  useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Reader 阅读位置', () => {
  it('返回已读文章时按保存的 ratio 恢复 scrollTop', async () => {
    stubDetails()
    saveReadingPosition('e1.a', {
      ratio: 0.4,
      anchorText: null,
      savedAt: '2026-09-17T00:00:00Z',
    })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    renderReader()
    await screen.findByText('文章甲')
    // 初始恢复发生在正文出现前（jsdom 无布局），先撑起布局再触发一次
    // 恢复（切走再切回）——真实浏览器里等价于「正文渲染完成后恢复」。
    giveLayout(scroller())
    useReaderUi.setState({ selectedEntryRef: 'e1.b' })
    await screen.findByText('文章乙')
    giveLayout(scroller())
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    await screen.findByText('文章甲')
    await waitFor(() => expect(scroller().scrollTop).toBe(480)) // 0.4 × (2000−800)
  })

  it('无保存记录的文章打开时回到顶部', async () => {
    stubDetails()
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    renderReader()
    await screen.findByText('文章甲')
    giveLayout(scroller())
    scroller().scrollTop = 777
    useReaderUi.setState({ selectedEntryRef: 'e1.b' })
    await screen.findByText('文章乙')
    await waitFor(() => expect(scroller().scrollTop).toBe(0))
  })

  it('滚动按当前 entryRef 保存位置；已读状态不被触碰', async () => {
    stubDetails()
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    renderReader()
    await screen.findByText('文章甲')
    giveLayout(scroller())
    scroller().scrollTop = 480
    fireEvent.scroll(scroller())
    await waitFor(() => {
      const saved = loadReadingPosition('e1.a')
      expect(saved).not.toBeNull()
      expect(saved!.ratio).toBeCloseTo(0.4, 5)
    })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
  })
})
