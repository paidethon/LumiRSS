/**
 * FIX-262 — 脚注往返链接经清洗不丢失（BASELINE_OK 运行时守卫）。
 *
 * 既有实现（F059 + FIX-262 语义）：
 * - 管线 transformFootnotes 把正文引用标记换成受控按钮
 *   （data-lumi-fn-key / data-lumi-fn-return 唯一序号），定义收进隐藏
 *   容器——往返关系由 **data 属性**承载（DOMPurify 默认放行 data-*，
 *   经 sanitize 不丢失；原站裸 `<a href="#fnref">` 反向链接按既定
 *   语义摘除，不依赖被清洗的裸锚点）；
 * - 点击引用 → 弹层显示再净化后的定义；弹层内「返回引用」按
 *   data-lumi-fn-return 找回触发标记：scrollIntoView + focus。
 *
 * 本守卫在渲染后的真实 DOM 上验证完整往返：打开脚注 → 返回引用后
 * 焦点回到原引用按钮（同一节点）。安全边界不动：定义内容弹层注入前
 * 再次 sanitizeArticleHtmlCached。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import ArticleContent from '../components/ArticleContent'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

const FOOTNOTE_HTML =
  '<p>正文一<sup><a href="#fn1">[1]</a></sup>，继续<sup><a href="#fn1">[1]</a></sup>。</p>' +
  '<ol><li id="fn1">脚注内容：出处说明。</li></ol>'

function detail(): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '标题',
    feedTitle: '源',
    author: null,
    url: 'https://blog.example.com/posts/hi',
    publishedAt: '2026-09-18T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: FOOTNOTE_HTML,
    contentText: '正文一。',
  } as unknown as EntryDetail
}

function withProviders(ui: ReactNode): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS, readerImageMode: 'all' } })
  vi.stubGlobal('fetch', vi.fn(() => new Response('{}', { status: 200 })))
  // jsdom 无 scrollIntoView（返回引用定位用）
  Element.prototype.scrollIntoView = vi.fn()
})

describe('FIX-262: 脚注往返（引用 → 定义 → 回到原引用）', () => {
  it('引用变为受控按钮；打开弹层后「返回引用」把焦点送回同一触发节点', async () => {
    const view = render(withProviders(<ArticleContent detail={detail()} />))
    const content = view.container.querySelector('.article-content') as HTMLElement

    // 管线异步：脚注按钮出现在 transform 完成后
    const refButtons = await waitFor(() => {
      const buttons = content.querySelectorAll<HTMLElement>('button[data-lumi-fn-ref]')
      expect(buttons.length).toBe(2)
      return buttons
    })
    const first = refButtons[0]!
    // 往返关系由 data 属性承载（可经 sanitize 存活），两处引用序号各自独立
    expect(first.getAttribute('data-lumi-fn-key')).toBe('1')
    expect(refButtons[1]!.getAttribute('data-lumi-fn-return')).not.toBe(
      first.getAttribute('data-lumi-fn-return'),
    )

    // 打开脚注弹层（净化后的定义 + 返回引用出口）
    first.focus()
    fireEvent.click(first)
    const dialog = await screen.findByRole('dialog', { name: '脚注 1' })
    expect(dialog.textContent).toContain('脚注内容')

    // 返回引用：焦点回到原触发按钮（同一节点），弹层关闭
    fireEvent.click(screen.getByRole('button', { name: '返回引用' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '脚注 1' })).toBeNull())
    expect(document.activeElement).toBe(first)

    // 第二处引用同样可达（各自返回位）
    const second = refButtons[1]!
    fireEvent.click(second)
    await screen.findByRole('dialog', { name: '脚注 1' })
    fireEvent.click(screen.getByRole('button', { name: '返回引用' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '脚注 1' })).toBeNull())
    expect(document.activeElement).toBe(second)
  })
})
