/** N051 章节化阅读测试 — 章节划分、显隐切换、上一章/下一章/退出、
 * 退出恢复滚动位置、段落深链进入正确章节。
 *
 * 真实 DOM 结构（jsdom）：.lumi-reader-scroll > .lumi-reader-article >
 * div > .article-content（与 Reader 渲染契约一致），ArticleToc 挂在同一
 * article 内，closest 链路真实成立。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ArticleToc from '../components/ArticleToc'
import type { TocEntry } from '../lib/article-toc'
import {
  applyChapterVisibility,
  containingChapterId,
  findChapterSection,
} from '../lib/article-chapters'

const ARTICLE_HTML = [
  '<p id="intro">导语段落</p>',
  '<h2 id="toc-第一章">第一章</h2>',
  '<p id="p1a">第一章段落 A</p>',
  '<p id="p1b">第一章段落 B</p>',
  '<h2 id="toc-第二章">第二章</h2>',
  '<p id="p2a">第二章段落 A</p>',
  '<h3 id="toc-小节">小节</h3>',
  '<p id="p2b">小节段落 B</p>',
  '<h2 id="toc-第三章">第三章</h2>',
  '<p id="p3a">第三章段落 A</p>',
].join('')

const TOC: TocEntry[] = [
  { id: 'toc-第一章', text: '第一章', level: 2 },
  { id: 'toc-第二章', text: '第二章', level: 2 },
  { id: 'toc-小节', text: '小节', level: 3 },
  { id: 'toc-第三章', text: '第三章', level: 2 },
]

function mountArticle(): { content: HTMLElement; scroller: HTMLElement } {
  const scroller = document.createElement('div')
  scroller.className = 'lumi-reader-scroll'
  scroller.scrollTop = 0
  const article = document.createElement('article')
  article.className = 'lumi-reader lumi-reader-article'
  const content = document.createElement('div')
  content.className = 'article-content'
  content.innerHTML = ARTICLE_HTML
  article.appendChild(content)
  const tocMount = document.createElement('div')
  article.appendChild(tocMount)
  scroller.appendChild(article)
  document.body.appendChild(scroller)
  return { content, scroller }
}

function renderToc() {
  const mountPoint = document.querySelectorAll('.lumi-reader-article > div')[1]
  render(<ArticleToc toc={TOC} />, { container: mountPoint as HTMLElement })
}

function hiddenIds(content: HTMLElement): string[] {
  return Array.from(content.querySelectorAll(':scope > .lumi-chapter-hidden')).map(
    (el) => el.id,
  )
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  document
    .querySelectorAll('.lumi-reader-scroll')
    .forEach((el) => el.remove())
})

describe('article-chapters 章节划分（纯 DOM）', () => {
  it('h2 章节到下一个 h2 为止；h3 小节到下一个同级或更高级标题为止', () => {
    const { content } = mountArticle()
    const ch1 = findChapterSection(content, 'toc-第一章')
    expect(ch1?.blocks.map((b) => b.id)).toEqual(['p1a', 'p1b'])
    const sec = findChapterSection(content, 'toc-小节')
    expect(sec?.blocks.map((b) => b.id)).toEqual(['p2b'])
    // 末章到文档结尾
    const ch3 = findChapterSection(content, 'toc-第三章')
    expect(ch3?.blocks.map((b) => b.id)).toEqual(['p3a'])
  })

  it('不存在的标题 id → null（不猜章节）；选中章节外的块被隐藏，null 还原', () => {
    const { content } = mountArticle()
    expect(findChapterSection(content, 'toc-不存在')).toBeNull()
    expect(applyChapterVisibility(content, 'toc-不存在')).toBe(0)
    expect(hiddenIds(content)).toEqual([])

    applyChapterVisibility(content, 'toc-第二章')
    // 只显示第二章 + 小节；导语/第一章/第三章全部隐藏
    expect(hiddenIds(content)).toEqual(['intro', 'toc-第一章', 'p1a', 'p1b', 'toc-第三章', 'p3a'])
    applyChapterVisibility(content, null)
    expect(hiddenIds(content)).toEqual([])
  })

  it('containingChapterId：目标块归属最近的前置章节头', () => {
    const { content } = mountArticle()
    const p2b = content.querySelector('#p2b')!
    expect(containingChapterId(content, p2b)).toBe('toc-小节')
    const intro = content.querySelector('#intro')!
    // 首章之前的内容归第一个章节
    expect(containingChapterId(content, intro)).toBe('toc-第一章')
  })
})

describe('ArticleToc 章节模式（组件）', () => {
  it('少于 2 个标题不渲染目录，也不提供章节模式', () => {
    mountArticle()
    const mountPoint = document.querySelectorAll('.lumi-reader-article > div')[1]
    render(<ArticleToc toc={[TOC[0]]} />, { container: mountPoint as HTMLElement })
    expect(screen.queryByText(/目录/)).toBeNull()
    expect(screen.queryByRole('button', { name: /章节模式/ })).toBeNull()
  })

  it('开启章节模式并选择章节 → 只显示该章节的块', () => {
    const { content } = mountArticle()
    renderToc()
    fireEvent.click(screen.getByRole('button', { name: /章节模式/ }))
    fireEvent.click(screen.getByRole('button', { name: '第二章' }))
    expect(hiddenIds(content)).toEqual(['intro', 'toc-第一章', 'p1a', 'p1b', 'toc-第三章', 'p3a'])
    // 目录项标记当前章节
    expect(screen.getByRole('button', { name: '第二章' })).toHaveAttribute(
      'aria-current',
      'true',
    )
    // 浮动章节导航出现
    expect(screen.getByLabelText('章节导航')).toBeInTheDocument()
    expect(screen.getByText('第 2/4 章 · 第二章')).toBeInTheDocument()
  })

  it('上一章/下一章正确移动；边界禁用', () => {
    const { content } = mountArticle()
    renderToc()
    fireEvent.click(screen.getByRole('button', { name: /章节模式/ }))
    fireEvent.click(screen.getByRole('button', { name: '第二章' }))

    // 下一章 → 小节（h3 也算一章）→ 第三章；到末章后「下一章」禁用
    fireEvent.click(screen.getByLabelText('下一章'))
    expect(hiddenIds(content)).toEqual([
      'intro',
      'toc-第一章',
      'p1a',
      'p1b',
      'toc-第二章',
      'p2a',
      'toc-第三章',
      'p3a',
    ])
    expect(screen.getByText('第 3/4 章 · 小节')).toBeInTheDocument()
    expect(screen.getByLabelText('下一章')).not.toBeDisabled()

    fireEvent.click(screen.getByLabelText('下一章'))
    expect(screen.getByText('第 4/4 章 · 第三章')).toBeInTheDocument()
    expect(screen.getByLabelText('下一章')).toBeDisabled()
    expect(screen.getByLabelText('上一章')).not.toBeDisabled()

    // 上一章 ×3 → 第一章；到首章后「上一章」禁用
    fireEvent.click(screen.getByLabelText('上一章'))
    fireEvent.click(screen.getByLabelText('上一章'))
    fireEvent.click(screen.getByLabelText('上一章'))
    expect(hiddenIds(content)).toEqual([
      'intro',
      'toc-第二章',
      'p2a',
      'toc-小节',
      'p2b',
      'toc-第三章',
      'p3a',
    ])
    expect(screen.getByText('第 1/4 章 · 第一章')).toBeInTheDocument()
    expect(screen.getByLabelText('上一章')).toBeDisabled()
  })

  it('退出章节还原全部块 + 进入前的滚动位置', () => {
    const { content, scroller } = mountArticle()
    scroller.scrollTop = 520
    renderToc()
    fireEvent.click(screen.getByRole('button', { name: /章节模式/ }))
    fireEvent.click(screen.getByRole('button', { name: '第二章' }))
    expect(hiddenIds(content)).not.toEqual([])
    expect(scroller.scrollTop).toBe(0)

    fireEvent.click(screen.getByLabelText('退出章节'))
    expect(hiddenIds(content)).toEqual([])
    expect(scroller.scrollTop).toBe(520)
    // 导航条收起，章节模式开关复位
    expect(screen.queryByLabelText('章节导航')).toBeNull()
    expect(screen.getByRole('button', { name: /章节模式/ })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('段落深链进入正确章节：位于其它章节的目标段落触发换章', () => {
    const { content } = mountArticle()
    renderToc()
    fireEvent.click(screen.getByRole('button', { name: /章节模式/ }))
    fireEvent.click(screen.getByRole('button', { name: '第一章' }))
    expect(hiddenIds(content)).toEqual(['intro', 'toc-第二章', 'p2a', 'toc-小节', 'p2b', 'toc-第三章', 'p3a'])

    // ArticleContent 定位段落成功后派发（目标 = 小节段落 p2b）
    fireEvent(
      document,
      new CustomEvent('lumi:para-navigate', {
        detail: { element: content.querySelector('#p2b') },
      }),
    )
    expect(hiddenIds(content)).toEqual([
      'intro',
      'toc-第一章',
      'p1a',
      'p1b',
      'toc-第二章',
      'p2a',
      'toc-第三章',
      'p3a',
    ])
    expect(screen.getByText('第 3/4 章 · 小节')).toBeInTheDocument()
  })

  it('章节模式未开启时目录项走锚点滚动（不隐藏任何块）', () => {
    const { content } = mountArticle()
    renderToc()
    fireEvent.click(screen.getByRole('button', { name: '第二章' }))
    expect(hiddenIds(content)).toEqual([])
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })
})
