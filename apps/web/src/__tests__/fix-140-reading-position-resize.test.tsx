/** FIX-140 — 阅读位置恢复在字体/窗口尺寸变化后不错位。
 *
 * 存储层（lib/reading-position）从设计上就是 fraction + 文本锚点：
 * `ratio` ∈ 0..1 + `anchorText`（段落文本前缀），绝无原始像素偏移。
 * Reader 恢复（restorePosition）：锚点优先（与几何无关）；ratio 回退时
 * 用**当前** scrollHeight−clientHeight 重算 `Math.round(ratio × max)`。
 * 本套件锁住关键场景：字体放大/窗口变化改变了正文总高度后，恢复仍落
 * 在同一阅读比例（原始像素恢复会错位到错误位置）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
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

function scroller(): HTMLElement {
  return document.querySelector('.lumi-reader')!.closest('div')!
}

function giveLayout(el: HTMLElement, scrollHeight: number) {
  Object.defineProperty(el, 'scrollHeight', { value: scrollHeight, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: 800, configurable: true })
}

beforeEach(() => {
  forgetReadingPositionsForTest()
  useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-140 阅读位置：fraction 恢复抗字体/尺寸变化', () => {
  it('保存 50% 后 scrollHeight 变化（字体放大），恢复落在新几何的 ~50%，不是旧像素', async () => {
    const details: Record<string, EntryDetail> = {
      'e1.a': detail('e1.a', '文章甲'),
      'e1.b': detail('e1.b', '文章乙'),
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const ref = String(input).split('/api/v1/entries/')[1]
        return Promise.resolve(jsonResponse(details[ref]))
      }),
    )
    // 字体 A：总高 2000，可视 800 → 可滚 1200；50% = 600（旧像素值）
    saveReadingPosition('e1.a', {
      ratio: 0.5,
      anchorText: null,
      savedAt: '2026-09-28T00:00:00Z',
    })
    expect(loadReadingPosition('e1.a')!.ratio).toBe(0.5)

    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Reader />
      </QueryClientProvider>,
    )
    await screen.findByText('文章甲')
    giveLayout(scroller(), 2000)
    // 切走再切回触发恢复；期间字体放大（总高 3200 → 可滚 2400），
    // 50% = 1200。若按保存时的原始像素 600 恢复会错位到 25%。
    useReaderUi.setState({ selectedEntryRef: 'e1.b' })
    await screen.findByText('文章乙')
    giveLayout(scroller(), 3200)
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    await screen.findByText('文章甲')
    await waitFor(() => expect(scroller().scrollTop).toBe(1200)) // 0.5 × (3200−800)
  })

  it('存储结构不含原始像素字段（ratio + anchorText 才是契约）', () => {
    saveReadingPosition('e1.a', {
      ratio: 0.42,
      anchorText: '第二段的开头文本',
      savedAt: '2026-09-28T00:00:00Z',
    })
    const saved = loadReadingPosition('e1.a')!
    expect(Object.keys(saved).sort()).toEqual(['anchorText', 'ratio', 'savedAt'])
    expect(saved.ratio).toBe(0.42)
    expect(saved.anchorText).toBe('第二段的开头文本')
  })
})
