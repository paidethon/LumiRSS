/** NEW-357 移动目录停靠 — 纯逻辑 + ArticleToc 停靠带（jsdom）。
 *
 * 覆盖：dock 纯函数（当前章下标 / 相邻章越界 / 带文案）；组件主路径
 * （≥2 章目录出现「停靠」开关 → 进入停靠收起 details、紧凑导航带出现
 * 且显示当前章；上一章/下一章 scrollIntoView 跳转；退出停靠导航带
 * 卸载恢复阅读区域；章节模式激活时停靠带让位）。
 *
 * DOM 结构与 ne1-chapters 同一契约：.lumi-reader-scroll >
 * .lumi-reader-article > (.article-content + toc 挂载点)。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ArticleToc from '../components/ArticleToc'
import { dockBandLabel, dockCurrentIndex, dockNeighbor } from '../lib/toc-dock'
import type { TocEntry } from '../lib/article-toc'

const TOC: TocEntry[] = [
  { id: 'toc-a', text: '第一章 起点', level: 2 },
  { id: 'toc-b', text: '第二章 中途', level: 2 },
  { id: 'toc-c', text: '第三章 终点', level: 2 },
]

/** 挂载真实结构；标题矩形按文档序钉定（jsdom 无布局），滚动跟随线
 * （视口顶+96px）落在第一章 → followId 确定性 = toc-a。 */
function mountReaderDom(): HTMLElement {
  const scroller = document.createElement('div')
  scroller.className = 'lumi-reader-scroll'
  const article = document.createElement('article')
  article.className = 'lumi-reader lumi-reader-article'
  const content = document.createElement('div')
  content.className = 'article-content'
  content.innerHTML = TOC.map((entry) => `<h2 id="${entry.id}">${entry.text}</h2>`).join('') + '<p>正文段</p>'
  article.appendChild(content)
  const tocMount = document.createElement('div')
  article.appendChild(tocMount)
  scroller.appendChild(article)
  document.body.appendChild(scroller)
  // jsdom 无布局：clientHeight/scrollHeight=0 会让「滚到底强制最后一章」
  // 恒真——钉定可滚动量让跟随语义确定性落在第一章。
  Object.defineProperty(scroller, 'clientHeight', { value: 800, configurable: true })
  Object.defineProperty(scroller, 'scrollHeight', { value: 5000, configurable: true })
  Element.prototype.scrollIntoView = vi.fn()
  const tops = new Map([
    ['toc-a', 0],
    ['toc-b', 2000],
    ['toc-c', 4000],
  ])
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    const top = tops.get(this.id) ?? 0
    return {
      top,
      bottom: top + 100,
      left: 0,
      right: 100,
      width: 100,
      height: 100,
      x: 0,
      y: top,
      toJSON: () => ({}),
    } as DOMRect
  })
  return tocMount
}

beforeEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('NEW-357 停靠纯逻辑', () => {
  it('当前章下标：followId 命中 / 未命中回退 0 / 空目录 -1', () => {
    expect(dockCurrentIndex(TOC, 'toc-b')).toBe(1)
    expect(dockCurrentIndex(TOC, 'missing')).toBe(0)
    expect(dockCurrentIndex(TOC, null)).toBe(0)
    expect(dockCurrentIndex([], null)).toBe(-1)
  })

  it('相邻章：越界 null（按钮禁用口径）', () => {
    expect(dockNeighbor(TOC, 'toc-a', -1)).toBeNull()
    expect(dockNeighbor(TOC, 'toc-a', 1)?.id).toBe('toc-b')
    expect(dockNeighbor(TOC, 'toc-c', 1)).toBeNull()
    expect(dockNeighbor(TOC, null, 1)).toBeNull()
  })

  it('停靠带文案与章节导航同一口径', () => {
    expect(dockBandLabel(1, 3, '第二章 中途')).toBe('第 2/3 章 · 第二章 中途')
  })
})

describe('NEW-357 停靠带（ArticleToc）', () => {
  it('停靠开关进入停靠：details 收起、导航带出现并显示当前章（跟随滚动）', () => {
    const mount = mountReaderDom()
    render(<ArticleToc toc={TOC} />, { container: mount })
    const details = document.querySelector('details.article-toc') as HTMLDetailsElement
    expect(details).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /停靠/ }))
    expect(screen.getByRole('navigation', { name: '目录停靠导航' })).toBeTruthy()
    expect(screen.getByText('第 1/3 章 · 第一章 起点')).toBeTruthy()
  })

  it('下一章跳转 scrollIntoView；首章时上一章禁用', () => {
    const mount = mountReaderDom()
    render(<ArticleToc toc={TOC} />, { container: mount })
    fireEvent.click(screen.getByRole('button', { name: /停靠/ }))
    const next = screen.getByRole('button', { name: '下一章' }) as HTMLButtonElement
    expect(next.disabled).toBe(false)
    fireEvent.click(next)
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    expect((screen.getByRole('button', { name: '上一章' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('退出停靠（按钮）：导航带卸载，恢复正常阅读区域（details 仍在）', () => {
    const mount = mountReaderDom()
    render(<ArticleToc toc={TOC} />, { container: mount })
    fireEvent.click(screen.getByRole('button', { name: /停靠/ }))
    expect(screen.getByRole('navigation', { name: '目录停靠导航' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '退出停靠' }))
    expect(screen.queryByRole('navigation', { name: '目录停靠导航' })).toBeNull()
    expect(document.querySelector('details.article-toc')).not.toBeNull()
  })

  it('章节模式激活时停靠带让位（两种浮带不同时叠加）', () => {
    const mount = mountReaderDom()
    render(<ArticleToc toc={TOC} />, { container: mount })
    fireEvent.click(screen.getByRole('button', { name: /停靠/ }))
    fireEvent.click(screen.getByRole('button', { name: /章节模式/ }))
    fireEvent.click(screen.getByRole('button', { name: '第一章 起点' }))
    expect(screen.queryByRole('navigation', { name: '目录停靠导航' })).toBeNull()
    expect(screen.getByRole('navigation', { name: '章节导航' })).toBeTruthy()
  })
})
