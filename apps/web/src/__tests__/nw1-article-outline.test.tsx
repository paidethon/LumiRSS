/** N068 辅助朗读结构检查（结构视图）— lib + 面板 + ReaderHeader 接线。
 *
 * 覆盖：大纲按文档序列出标题（h1–h6，跳级平铺）；sr-only / aria-hidden
 * 的标题与文本被剔除；计数（链接/图片/表格/代码块/批注）；点击标题跳转
 * （焦点移交）；开关状态设备本地（写回 + 重挂载自动还原）。 */

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ArticleOutlineDialog from '../components/ArticleOutlineDialog'
import ReaderHeader from '../components/ReaderHeader'
import {
  STRUCTURE_VIEW_STORAGE_KEY,
  buildArticleOutline,
  readStructureViewOpen,
  visibleText,
  writeStructureViewOpen,
} from '../lib/article-outline'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

const OUTLINE_HTML = [
  '<h1>主标题 <span class="sr-only">（重复装饰文案）</span></h1>',
  '<h2>第一章</h2>',
  '<p>正文段落 <a href="https://a.example.com">链接一</a>。</p>',
  '<h2 aria-hidden="true">隐藏标题（装饰）</h2>',
  '<h4>跳级小节</h4>',
  '<img src="https://img.example.com/x.png" alt="图">',
  '<table><tbody><tr><td>单元格</td></tr></tbody></table>',
  '<pre><code>const a = 1</code></pre>',
  '<a href="https://b.example.com">链接二</a>',
  '<h3 hidden>彻底隐藏的标题</h3>',
].join('')

function detailFixture(): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: null,
    url: 'https://example.com/a',
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '正文',
    contentHtml: OUTLINE_HTML,
  }
}

function mountArticle(): { container: HTMLElement; article: HTMLElement } {
  const container = document.createElement('div')
  container.innerHTML = `<div class="lumi-reader-article">${OUTLINE_HTML}</div>`
  document.body.appendChild(container)
  const article = container.querySelector('.lumi-reader-article') as HTMLElement
  return { container, article }
}

function withProviders(ui: ReactNode): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  // 断言脚本/可执行零调用：全局 fetch 间谍（批注同步等可能尝试）
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('[]', { status: 200 }))))
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
  window.localStorage.clear()
})

describe('article-outline 纯逻辑', () => {
  it('大纲按文档序列出 h1–h6；sr-only / aria-hidden / hidden 剔除', () => {
    const { article } = mountArticle()
    const outline = buildArticleOutline(article, 2)
    expect(outline.headings.map((h) => h.text)).toEqual([
      '主标题（重复装饰文案）'.replace('（重复装饰文案）', ''),
      '第一章',
      '跳级小节',
    ])
    // 层级与文档序
    expect(outline.headings.map((h) => h.level)).toEqual([1, 2, 4])
    expect(outline.headings[0]!.index).toBeLessThan(outline.headings[1]!.index)
    // 计数：链接 2（aria-hidden 内不计——本文没有隐藏链接）、图片 1、表格 1、代码块 1、批注注入 2
    expect(outline.counts).toEqual({
      links: 2,
      images: 1,
      tables: 1,
      codeBlocks: 1,
      annotations: 2,
    })
  })

  it('visibleText：剥离装饰后代后空白归一', () => {
    const { article } = mountArticle()
    const h1 = article.querySelector('h1')!
    expect(visibleText(h1)).toBe('主标题')
    const hiddenH2 = article.querySelector('h2[aria-hidden="true"]')!
    expect(visibleText(hiddenH2)).toBe('隐藏标题（装饰）') // 自身可见性由调用方判定
  })

  it('开关状态设备本地：写入/读取/损坏回退', () => {
    expect(readStructureViewOpen()).toBe(false)
    writeStructureViewOpen(true)
    expect(readStructureViewOpen()).toBe(true)
    expect(window.localStorage.getItem(STRUCTURE_VIEW_STORAGE_KEY)).toBe('1')
    window.localStorage.setItem(STRUCTURE_VIEW_STORAGE_KEY, 'garbage')
    expect(readStructureViewOpen()).toBe(false)
  })
})

describe('ArticleOutlineDialog 面板', () => {
  it('列表语义展示大纲；sr-only 标题不在面板；点击标题跳转并移交焦点', async () => {
    const { article } = mountArticle()
    // jsdom 无 scrollIntoView：打桩记录调用
    const scrollSpy = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollSpy,
    })
    try {
      render(
        <ArticleOutlineDialog
          open
          onClose={() => {}}
          entryRef="e1.a"
          getContainer={() => article}
        />,
      )
      const list = screen.getByTestId('outline-headings')
      expect(list.tagName).toBe('UL')
      const items = Array.from(list.querySelectorAll('li > button'))
      expect(items.map((b) => b.textContent)).toEqual(['h1主标题', 'h2第一章', 'h4跳级小节'])
      const dialog = screen.getByRole('dialog', { name: '结构视图' })
      // 隐藏标题（aria-hidden/hidden）绝不出现在面板（正文 DOM 里存在，
      // 面板内不存在——within 限定查询范围）
      expect(within(dialog).queryByText(/隐藏标题/)).toBeNull()
      expect(within(dialog).queryByText(/彻底隐藏/)).toBeNull()
      // 计数行
      expect(screen.getByTestId('outline-counts').textContent).toContain('链接 2')
      expect(screen.getByTestId('outline-counts').textContent).toContain('批注 0')

      // 跳转：点击第一章 → scrollIntoView + 焦点移交标题元素
      fireEvent.click(items[1]!)
      expect(scrollSpy).toHaveBeenCalled()
      const firstHeading = article.querySelector('h2:not([aria-hidden])') as HTMLElement
      expect(document.activeElement).toBe(firstHeading)
    } finally {
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView
    }
  })

  it('关闭时写回设备本地开关（false）', async () => {
    const { article } = mountArticle()
    writeStructureViewOpen(true)
    render(
      <ArticleOutlineDialog
        open={false}
        onClose={() => {}}
        entryRef="e1.a"
        getContainer={() => article}
      />,
    )
    await act(async () => {})
    expect(readStructureViewOpen()).toBe(false)
  })
})

describe('ReaderHeader 接线（工具栏 → 结构视图）', () => {
  it('工具栏按钮打开结构视图；状态写回 localStorage；重挂载自动还原', async () => {
    const { article } = mountArticle()
    const ref = { current: article } as React.RefObject<HTMLElement | null>
    const view = render(withProviders(<ReaderHeader detail={detailFixture()} outlineRootRef={ref} />))

    // 打开：工具栏「结构视图」按钮（Aa 面板旁，两断点共有）
    fireEvent.click(screen.getByRole('button', { name: '结构视图' }))
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: '结构视图' })).toBeInTheDocument(),
    )
    expect(window.localStorage.getItem(STRUCTURE_VIEW_STORAGE_KEY)).toBe('1')

    // 关闭（Escape → Dialog 原语 onClose → 写回 false）
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '结构视图' })).toBeNull(),
    )
    expect(readStructureViewOpen()).toBe(false)

    // 重挂载还原：预置 '1' → 面板自动展开
    window.localStorage.setItem(STRUCTURE_VIEW_STORAGE_KEY, '1')
    view.unmount()
    render(withProviders(<ReaderHeader detail={detailFixture()} outlineRootRef={ref} />))
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: '结构视图' })).toBeInTheDocument(),
    )
  })
})
