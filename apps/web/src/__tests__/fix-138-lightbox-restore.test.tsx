/** FIX-138 — 放大图片后返回不丢正文位置/焦点，也不误标已读。
 *
 * 行为核验（实现见 ArticleContent：打开前 savedScrollRef + focusReturnRef，
 * 关闭统一 restoreScrollAndFocus）：
 * - 打开灯箱：正文 scrollTop 不被移动；
 * - 关闭灯箱：scrollTop 还原到打开前的值，焦点归还触发图片；
 * - 全程零网络请求——finish-read（Reader 级：末尾哨兵可见 + 主动向下
 *   推进 ≥ 阈值 + 稳定停留）的输入不因开/关灯箱变化，结构上不可能
 *   被触发；这里以「无任何 fetch」锁住“无标读副作用”。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

function detail(): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '放大文章',
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-28T00:00:00Z',
    read: false,
    starred: false,
    contentHtml:
      '<p>开头</p>' +
      '<figure><img src="https://cdn.example.com/a.png" alt="图A"><figcaption>图A</figcaption></figure>' +
      '<p>结尾</p>',
    contentText: '正文',
  } as unknown as EntryDetail
}

function scroller(): HTMLElement {
  return document.querySelector('[data-testid="fix138-scroller"]')!
}

describe('FIX-138 灯箱开/关：滚动与焦点还原，零标读副作用', () => {
  beforeEach(() => {
    useAppSettings.setState({
      settings: { ...DEFAULT_APP_SETTINGS, readerCodeHighlight: 'off', readerImageMode: 'all' },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  })

  it('打开不动 scrollTop；关闭还原 scrollTop + 焦点回触发图；全程零 fetch', async () => {
    const fetchCalls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        fetchCalls.push(String(input))
        return Promise.resolve(new Response('{}', { status: 200 }))
      }),
    )

    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <div data-testid="fix138-scroller">
        <div className="lumi-reader lumi-reader-article">
          <ArticleContent detail={detail()} />
        </div>
      </div>,
      { wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider> },
    )

    // jsdom 无布局：手动撑起滚动几何并落在正文中部
    const box = scroller()
    Object.defineProperty(box, 'scrollHeight', { value: 3000, configurable: true })
    Object.defineProperty(box, 'clientHeight', { value: 1000, configurable: true })
    box.scrollTop = 500

    const trigger = await screen.findByRole('img', { name: '图A' })
    fireEvent.click(trigger)
    await screen.findByRole('dialog', { name: '图片查看' })
    // 打开灯箱本身不移动正文位置
    expect(box.scrollTop).toBe(500)
    // 灯箱打开期间的任何位置漂移，关闭时都被还原到打开前快照
    box.scrollTop = 1200
    expect(box.scrollTop).toBe(1200)

    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '图片查看' })).toBeNull(),
    )
    // 关闭后：滚动位置还原 + 焦点归还触发图片
    expect(box.scrollTop).toBe(500)
    expect(document.activeElement).toBe(trigger)
    // 开/关全程零网络请求：没有任何标读/进度副作用
    expect(fetchCalls).toEqual([])
  })
})
