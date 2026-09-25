/** N064 — 公式专注视图：管线渲染的公式（有 TeX 原文 data-lumi-tex）可
 * 点击/回车放大 → 专注面板重渲同一公式（trust:false）+「复制 LaTeX」
 * 复制 TeX 源；无 TeX 源的公式诚实不可交互；关闭还原滚动 + 焦点归还。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import { clearArticleHtmlCaches } from '../lib/article-pipeline'
import type { EntryDetail } from '../api/types'

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '公式文章',
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

function renderArticle(contentHtml: string, wrap = false) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const content = (
    <div className="lumi-reader-article">
      <ArticleContent detail={detail({ contentHtml })} />
    </div>
  )
  return render(
    wrap ? (
      <QueryClientProvider client={qc}>
        <div>
          <div>{content}</div>
        </div>
      </QueryClientProvider>
    ) : (
      <QueryClientProvider client={qc}>{content}</QueryClientProvider>
    ),
  )
}

beforeEach(() => {
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS, readerCodeHighlight: 'off' } })
  clearArticleHtmlCaches()
})

afterEach(() => {
  vi.unstubAllGlobals()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  clearArticleHtmlCaches()
  const nav = window.navigator as unknown as Record<string, unknown>
  delete nav.clipboard
})

const MATH_CONTENT = '<p>质能公式 $E = mc^2$ 内联与块级：</p><p>$$\\int_0^1 x\\,dx$$</p>'

describe('N064 公式专注视图', () => {
  it('管线公式获得放大入口；点击打开专注视图并重渲同一公式', async () => {
    renderArticle(MATH_CONTENT)
    // 管线异步渲染后，公式带 data-lumi-tex 且被接线为可交互
    const formula = await waitFor(() => {
      const el = document.querySelector<HTMLElement>('[data-lumi-formula-ready]')
      expect(el).not.toBeNull()
      return el!
    })
    expect(formula.getAttribute('data-lumi-tex')).toBe('E = mc^2')
    expect(formula.getAttribute('role')).toBe('button')
    expect(formula.getAttribute('aria-label')).toBe('放大公式')

    fireEvent.click(formula)
    const dialog = await screen.findByRole('dialog', { name: '公式查看' })
    // 同一 TeX（渲染管线同源 katex-render）在专注面板里重渲
    await waitFor(() => {
      expect(dialog.querySelector('.lumi-formula-focus .katex')).not.toBeNull()
    })
    // 内联公式保持内联模式（无 katex-display）
    expect(dialog.querySelector('.lumi-formula-focus .katex-display')).toBeNull()
  })

  it('复制 LaTeX 写入剪贴板的是 TeX 源', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(window.navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderArticle(MATH_CONTENT)
    fireEvent.click(
      await waitFor(() => {
        const el = document.querySelector<HTMLElement>('[data-lumi-formula-ready]')
        expect(el).not.toBeNull()
        return el!
      }),
    )
    await screen.findByRole('dialog', { name: '公式查看' })
    fireEvent.click(screen.getByRole('button', { name: '复制 LaTeX' }))
    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('E = mc^2')
    })
    expect(await screen.findByText('已复制 LaTeX')).toBeInTheDocument()
  })

  it('块级公式（$$…$$）在专注视图中保持 displayMode', async () => {
    renderArticle(MATH_CONTENT)
    // 等两个公式都接线（内联 + 块级）
    await waitFor(() => {
      expect(document.querySelectorAll('[data-lumi-formula-ready]').length).toBe(2)
    })
    const block = Array.from(document.querySelectorAll<HTMLElement>('[data-lumi-formula-ready]')).find(
      (el) => el.getAttribute('data-lumi-tex') === '\\int_0^1 x\\,dx',
    )!
    fireEvent.click(block)
    const dialog = await screen.findByRole('dialog', { name: '公式查看' })
    await waitFor(() => {
      expect(dialog.querySelector('.lumi-formula-focus .katex-display')).not.toBeNull()
    })
  })

  it('无 TeX 源的公式（上游自带 KaTeX HTML）不接线、不可交互（诚实）', async () => {
    const content =
      '<p>正常段落</p><p><span class="katex"><span class="katex-html">x</span></span></p>'
    renderArticle(content)
    expect(await screen.findByText('正常段落')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 30))
    // 装饰完成后：无 data-lumi-tex 的公式没有交互语义
    const upstream = document.querySelector('.katex')
    expect(upstream).not.toBeNull()
    expect(upstream!.getAttribute('data-lumi-formula-ready')).toBeNull()
    expect(upstream!.getAttribute('role')).toBeNull()
    fireEvent.click(upstream as HTMLElement)
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.queryByRole('dialog', { name: '公式查看' })).toBeNull()
  })

  it('关闭还原滚动位置并归还焦点到公式', async () => {
    renderArticle(
      MATH_CONTENT,
      true,
    )
    const formula = await waitFor(() => {
      const el = document.querySelector<HTMLElement>('[data-lumi-formula-ready]')
      expect(el).not.toBeNull()
      return el!
    })
    const scroller = document.querySelector('.lumi-reader-article')!.parentElement!
    Object.defineProperty(scroller, 'scrollHeight', { value: 4000, configurable: true })
    Object.defineProperty(scroller, 'clientHeight', { value: 600, configurable: true })
    Object.defineProperty(scroller, 'scrollTop', { value: 222, writable: true, configurable: true })

    fireEvent.click(formula)
    await screen.findByRole('dialog', { name: '公式查看' })
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '公式查看' })).toBeNull()
    })
    expect(scroller.scrollTop).toBe(222)
    expect(document.activeElement).toBe(formula)
  })
})
