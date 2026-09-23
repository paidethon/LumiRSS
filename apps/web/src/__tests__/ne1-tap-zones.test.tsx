/** N053 分页点按翻页区测试 — 轴向/大小纯函数 + 组件点击委托
 * （翻页区命中翻页；链接、文本选区、横向可滚元素绝不翻页；轴向切换）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRef } from 'react'
import { ReaderPager } from '../components/ReaderPager'
import { useAppSettings } from '../store/app-settings'
import { tapZoneDirection } from '../lib/reader-pagination'
import { forgetReadingPositionsForTest } from '../lib/reading-position'

function stubLayout(
  container: HTMLElement,
  article: HTMLElement,
  rect: { left: number; top: number; width: number; height: number },
) {
  Object.defineProperty(container, 'clientWidth', { value: rect.width, configurable: true })
  Object.defineProperty(container, 'clientHeight', { value: rect.height, configurable: true })
  Object.defineProperty(article, 'scrollWidth', { value: rect.width * 3, configurable: true })
  vi.stubGlobal(
    'getComputedStyle',
    () =>
      ({
        paddingLeft: '20px',
        getPropertyValue: () => '',
      }) as unknown as CSSStyleDeclaration,
  )
  vi.spyOn(container, 'getBoundingClientRect').mockReturnValue({
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
    right: rect.left + rect.width,
    bottom: rect.top + rect.height,
    x: rect.left,
    y: rect.top,
    toJSON: () => ({}),
  } as DOMRect)
}

beforeEach(() => {
  forgetReadingPositionsForTest()
  useAppSettings.setState({
    settings: {
      ...useAppSettings.getState().settings,
      readerReadingMode: 'paged',
      readerTapZoneAxis: 'horizontal',
      readerTapZoneSize: 'small',
    },
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  localStorage.clear()
  document.querySelectorAll('.lumi-reader-article').forEach((el) => {
    el.parentElement?.remove()
  })
})

describe('tapZoneDirection（纯函数）', () => {
  const base = { width: 800, height: 600, size: 'small' } as const

  it('horizontal：左右 22% 命中，中部不命中', () => {
    expect(tapZoneDirection({ ...base, x: 100, y: 300, axis: 'horizontal' })).toBe(-1)
    expect(tapZoneDirection({ ...base, x: 700, y: 300, axis: 'horizontal' })).toBe(1)
    expect(tapZoneDirection({ ...base, x: 400, y: 300, axis: 'horizontal' })).toBeNull()
  })

  it('vertical：上下命中；size off 永不命中；非法坐标收敛为 null', () => {
    expect(tapZoneDirection({ ...base, x: 400, y: 50, axis: 'vertical' })).toBe(-1)
    expect(tapZoneDirection({ ...base, x: 400, y: 550, axis: 'vertical' })).toBe(1)
    expect(tapZoneDirection({ ...base, x: 400, y: 550, axis: 'vertical', size: 'off' })).toBeNull()
    expect(tapZoneDirection({ ...base, x: NaN, y: 300, axis: 'horizontal' })).toBeNull()
  })

  it('large 档位（40%）比 small 命中范围更宽', () => {
    expect(tapZoneDirection({ ...base, x: 300, y: 300, axis: 'horizontal', size: 'small' })).toBeNull()
    expect(tapZoneDirection({ ...base, x: 300, y: 300, axis: 'horizontal', size: 'large' })).toBe(-1)
  })
})

describe('点按翻页（组件委托）', () => {
  function setup(axis: 'horizontal' | 'vertical', size: 'off' | 'small' | 'large' = 'small') {
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, readerTapZoneAxis: axis, readerTapZoneSize: size },
    })
    const container = document.createElement('div')
    const article = document.createElement('article')
    article.className = 'lumi-reader-article'
    article.innerHTML = '<div class="article-content"><p>第一段</p><p>第二段</p></div>'
    container.appendChild(article)
    document.body.appendChild(container)
    stubLayout(container, article, { left: 0, top: 0, width: 800, height: 600 })
    const containerRef = createRef<HTMLDivElement>()
    const articleRef = createRef<HTMLElement>()
    Object.defineProperty(containerRef, 'current', { value: container })
    Object.defineProperty(articleRef, 'current', { value: article })
    render(
      <ReaderPager
        enabled
        containerRef={containerRef as React.RefObject<HTMLDivElement>}
        articleRef={articleRef as React.RefObject<HTMLElement>}
        entryRef="e1"
      />,
    )
    return { container, article }
  }

  const indicator = () => document.querySelector('[data-lumi-pager-indicator]')?.textContent

  it('点按右缘翻下一页；点按中部不翻页', async () => {
    const { container } = setup('horizontal')
    await waitFor(() => expect(indicator()).toBe('1 / 3'))
    fireEvent.click(container, { clientX: 750, clientY: 300 })
    await waitFor(() => expect(indicator()).toBe('2 / 3'))
    fireEvent.click(container, { clientX: 400, clientY: 300 })
    expect(indicator()).toBe('2 / 3')
  })

  it('链接与按钮上的点按不翻页', async () => {
    const { container } = setup('horizontal')
    await waitFor(() => expect(indicator()).toBe('1 / 3'))
    const link = document.createElement('a')
    link.href = 'https://example.com'
    link.textContent = '外链'
    container.appendChild(link)
    fireEvent.click(link, { clientX: 750, clientY: 300 })
    expect(indicator()).toBe('1 / 3')
  })

  it('非空选区（选中文字后松手在翻页区）不翻页', async () => {
    const { container } = setup('horizontal')
    await waitFor(() => expect(indicator()).toBe('1 / 3'))
    vi.spyOn(window, 'getSelection').mockReturnValue({
      isCollapsed: false,
      anchorNode: container.firstChild,
    } as unknown as Selection)
    fireEvent.click(container, { clientX: 750, clientY: 300 })
    expect(indicator()).toBe('1 / 3')
  })

  it('横向可滚元素（表格/代码）上的点按不翻页', async () => {
    const { container } = setup('horizontal')
    await waitFor(() => expect(indicator()).toBe('1 / 3'))
    const scroller = document.createElement('table')
    Object.defineProperty(scroller, 'scrollWidth', { value: 1200, configurable: true })
    Object.defineProperty(scroller, 'clientWidth', { value: 300, configurable: true })
    container.appendChild(scroller)
    fireEvent.click(scroller, { clientX: 750, clientY: 300 })
    expect(indicator()).toBe('1 / 3')
  })

  it('轴向切换：上下模式点底缘下一页、顶缘上一页（左右不再命中）', async () => {
    const { container } = setup('vertical')
    await waitFor(() => expect(indicator()).toBe('1 / 3'))
    // 左右缘在 vertical 轴下不命中
    fireEvent.click(container, { clientX: 750, clientY: 300 })
    expect(indicator()).toBe('1 / 3')
    // 底缘 → 下一页；顶缘 → 上一页
    fireEvent.click(container, { clientX: 400, clientY: 550 })
    await waitFor(() => expect(indicator()).toBe('2 / 3'))
    fireEvent.click(container, { clientX: 400, clientY: 50 })
    await waitFor(() => expect(indicator()).toBe('1 / 3'))
  })

  it('size = off 时点按任何位置都不翻页（按钮仍可用）', async () => {
    const { container } = setup('horizontal', 'off')
    await waitFor(() => expect(indicator()).toBe('1 / 3'))
    fireEvent.click(container, { clientX: 750, clientY: 300 })
    expect(indicator()).toBe('1 / 3')
    // 可见翻页按钮始终保留（可访问性路径）
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(indicator()).toBe('2 / 3'))
  })
})
