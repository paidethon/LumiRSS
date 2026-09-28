/** FIX-267 — 文中锚链接只滚动当前正文。
 *
 * 两层：
 * 1. lib/article-toc：withHeadingIds 不再无条件改写 h2–h4 的源 id——
 *    源 id 保留（文内 `<a href="#…">` 的跳转目标不悬空）；仅源 id 与
 *    既有 id 冲突时回退 toc-slug 去重 id；
 * 2. ArticleContent：点击正文内纯 hash 链接 → preventDefault + 页内
 *    scrollIntoView，不改 location.hash（默认导航会新增历史条目，
 *    Back 会触发 nav-history 恢复旧快照；在自定义滚动容器里原生
 *    锚点滚动也不可靠）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import { withHeadingIds } from '../lib/article-toc'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

describe('withHeadingIds：标题源 id 保留（锚点目标不悬空）', () => {
  it('既有 id 的标题保留原 id，无 id 的标题照常生成 toc-slug', () => {
    const { toc, html } = withHeadingIds(
      '<h2 id="section-1">第一节</h2><h2>第二节</h2>',
    )
    expect(toc.map((t) => t.id)).toEqual(['section-1', 'toc-第二节'])
    expect(html).toContain('<h2 id="section-1">')
    expect(html).toContain('id="toc-第二节"')
  })

  it('重复的源 id 不复制（第二个回退 toc-slug 去重 id）', () => {
    const { toc } = withHeadingIds('<h2 id="dup">甲</h2><h2 id="dup">乙</h2>')
    const ids = toc.map((t) => t.id)
    expect(ids[0]).toBe('dup')
    expect(ids[1]).not.toBe('dup')
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('重新提取结果稳定（源 id 保留语义下锚点仍稳定）', () => {
    const input = '<h2 id="keep">甲</h2><h2>甲</h2>'
    const first = withHeadingIds(input)
    const second = withHeadingIds(input)
    expect(second.toc.map((t) => t.id)).toEqual(first.toc.map((t) => t.id))
  })

  it('空标题（不进目录）的既有 id 也占位，不与后续生成 id 撞车', () => {
    const { toc } = withHeadingIds('<h2 id="toc-甲">   </h2><h2>甲</h2>')
    expect(toc.map((t) => t.id)).toEqual(['toc-甲-2'])
  })
})

describe('ArticleContent：正文 hash 链接页内滚动', () => {
  const CONTENT_HTML =
    '<p><a href="#section-1">跳到第一节</a></p>' +
    '<h2 id="section-1">第一节</h2>' +
    '<p>正文。</p>' +
    '<p><a href="#">空锚</a></p>'

  function renderContent() {
    useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
    const detail = {
      entryRef: 'e1.a',
      title: '标题',
      feedTitle: '源',
      author: null,
      url: null,
      publishedAt: '2026-09-18T00:00:00Z',
      read: false,
      starred: false,
      contentHtml: CONTENT_HTML,
      contentText: '正文',
    } as unknown as EntryDetail
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={qc}>
        <ArticleContent detail={detail} />
      </QueryClientProvider>,
    )
  }

  // jsdom 无 scrollIntoView（仓库既有测试同一打桩模式）：直接赋值，
  // afterEach 还原。
  const scrolled: Element[] = []
  const originalScrollIntoView = Element.prototype.scrollIntoView as
    | ((options?: ScrollIntoViewOptions) => void)
    | undefined
  function stubScrollIntoView(): void {
    scrolled.length = 0
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this)
    }
  }

  afterEach(() => {
    if (originalScrollIntoView === undefined) {
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
    } else {
      Element.prototype.scrollIntoView = originalScrollIntoView
    }
    window.location.hash = ''
  })

  it('点击 #section-1 → 目标标题 scrollIntoView，location.hash 不变', () => {
    const { container, getByText } = renderContent()
    // 源 id 保留：锚点目标仍在 DOM 上
    expect(container.querySelector('h2#section-1')).not.toBeNull()
    stubScrollIntoView()
    window.location.hash = ''
    fireEvent.click(getByText('跳到第一节'))
    expect(scrolled).toHaveLength(1)
    expect(scrolled[0]).toBe(container.querySelector('h2#section-1'))
    // 未发生 hash 导航（不新增历史条目）
    expect(window.location.hash).toBe('')
  })

  it('空 hash（href="#"）只拦截默认导航，不滚动、不报错', () => {
    const { getByText } = renderContent()
    stubScrollIntoView()
    window.location.hash = ''
    expect(() => fireEvent.click(getByText('空锚'))).not.toThrow()
    expect(scrolled).toHaveLength(0)
    expect(window.location.hash).toBe('')
  })

  it('外链不受影响（hash 分支不吞非 hash 链接）', () => {
    const { container, getByText } = renderContent()
    const external = document.createElement('a')
    external.setAttribute('href', 'https://example.com/out')
    external.textContent = '站外链接'
    container.querySelector('.article-content')?.appendChild(external)
    stubScrollIntoView()
    fireEvent.click(getByText('站外链接'))
    expect(scrolled).toHaveLength(0)
    // hash 分支对同容器内的 hash 链接照常工作
    fireEvent.click(getByText('跳到第一节'))
    expect(scrolled).toHaveLength(1)
  })
})
