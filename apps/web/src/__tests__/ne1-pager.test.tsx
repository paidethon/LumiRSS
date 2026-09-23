/** N052 分页阅读测试 — 纯几何（栏宽/栏距/页数/位移）、翻页交互
 * （按钮/左右方向键/页码指示）、位置记录恢复与重排锚定（mock 尺寸）。
 *
 * jsdom 无布局：clientWidth/clientHeight/scrollWidth/getBoundingClientRect
 * 全部以 defineProperty 打桩；getComputedStyle 打桩返回页边距。 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRef } from 'react'
import { ReaderPager } from '../components/ReaderPager'
import { useAppSettings } from '../store/app-settings'
import {
  clampPage,
  computePagedLayout,
  pageOfAnchor,
  pageOffset,
} from '../lib/reader-pagination'
import { saveReadingPosition, forgetReadingPositionsForTest } from '../lib/reading-position'

function stubLayout(
  container: HTMLElement,
  article: HTMLElement,
  opts: { width: number; height: number; scrollWidth: number; margin?: number },
) {
  Object.defineProperty(container, 'clientWidth', { value: opts.width, configurable: true })
  Object.defineProperty(container, 'clientHeight', { value: opts.height, configurable: true })
  Object.defineProperty(article, 'scrollWidth', { value: opts.scrollWidth, configurable: true })
  vi.stubGlobal(
    'getComputedStyle',
    () =>
      ({
        paddingLeft: `${opts.margin ?? 20}px`,
        getPropertyValue: () => '',
      }) as unknown as CSSStyleDeclaration,
  )
}

function mountReaderDom() {
  const container = document.createElement('div')
  const article = document.createElement('article')
  article.className = 'lumi-reader-article'
  article.innerHTML = '<div class="article-content"><p>第一段</p><p>第二段</p><p>第三段</p></div>'
  container.appendChild(article)
  document.body.appendChild(container)
  return { container, article }
}

beforeEach(() => {
  forgetReadingPositionsForTest()
  useAppSettings.setState({
    settings: {
      ...useAppSettings.getState().settings,
      readerReadingMode: 'paged',
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
  document.querySelectorAll('.lumi-reader-article').forEach((el) => {
    el.parentElement?.remove()
  })
})

describe('分页几何（computePagedLayout / clampPage / pageOffset）', () => {
  it('栏宽 = 视口 - 2×页边距，栏距 = 2×页边距，页数 = round(scrollWidth/stride)', () => {
    const layout = computePagedLayout({ viewportWidth: 800, pageMarginPx: 20, articleScrollWidth: 2400 })
    expect(layout).toEqual({ columnWidth: 760, columnGap: 40, stride: 800, pageCount: 3 })
    // 非整除 → round 吸收亚像素噪声；空内容 → 至少 1 页
    expect(computePagedLayout({ viewportWidth: 800, pageMarginPx: 20, articleScrollWidth: 2005 }).pageCount).toBe(3)
    expect(computePagedLayout({ viewportWidth: 800, pageMarginPx: 20, articleScrollWidth: 0 }).pageCount).toBe(1)
    // 非法输入收敛，不产生 NaN
    expect(computePagedLayout({ viewportWidth: NaN, pageMarginPx: NaN, articleScrollWidth: NaN }).pageCount).toBe(1)
  })

  it('页码钳制与位移', () => {
    expect(clampPage(-1, 3)).toBe(0)
    expect(clampPage(7, 3)).toBe(2)
    expect(clampPage(1, 0)).toBe(0)
    expect(pageOffset(2, 800)).toBe(1600)
  })

  it('pageOfAnchor：按未平移 pageX 落页并钳制', () => {
    expect(pageOfAnchor({ pageX: 0, stride: 800, pageCount: 3 })).toBe(0)
    expect(pageOfAnchor({ pageX: 950, stride: 800, pageCount: 3 })).toBe(1)
    expect(pageOfAnchor({ pageX: 9999, stride: 800, pageCount: 3 })).toBe(2)
    expect(pageOfAnchor({ pageX: -50, stride: 800, pageCount: 3 })).toBe(0)
  })
})

describe('ReaderPager 组件（mock 布局）', () => {
  function setup(scrollWidth = 2400, entryRef: string | null = 'e1') {
    const { container, article } = mountReaderDom()
    stubLayout(container, article, { width: 800, height: 600, scrollWidth })
    const containerRef = createRef<HTMLDivElement>()
    const articleRef = createRef<HTMLElement>()
    Object.defineProperty(containerRef, 'current', { value: container })
    Object.defineProperty(articleRef, 'current', { value: article })
    render(<ReaderPager enabled containerRef={containerRef as React.RefObject<HTMLDivElement>} articleRef={articleRef as React.RefObject<HTMLElement>} entryRef={entryRef} />)
    return { container, article }
  }

  it('启用后铺多栏样式，页数/页码指示正确；禁用还原样式', async () => {
    const { container, article } = setup(2400)
    await waitFor(() => expect(screen.getByText('1 / 3')).toBeInTheDocument())
    expect(article.style.height).toBe('600px')
    expect(article.style.columnWidth).toBe('760px')
    expect(article.style.columnGap).toBe('40px')
    expect(article.style.columnFill).toBe('auto')
    expect(article.style.transform).toBe('translateX(-0px)')
    expect(container.classList.contains('lumi-paged-clip')).toBe(true)
    expect(article.classList.contains('lumi-paged-track')).toBe(true)
  })

  it('禁用（阅读模式 = 滚动）时零渲染且不留分页样式', async () => {
    const { container, article } = mountReaderDom()
    stubLayout(container, article, { width: 800, height: 600, scrollWidth: 2400 })
    const containerRef = createRef<HTMLDivElement>()
    const articleRef = createRef<HTMLElement>()
    Object.defineProperty(containerRef, 'current', { value: container })
    Object.defineProperty(articleRef, 'current', { value: article })
    const { rerender } = render(
      <ReaderPager enabled containerRef={containerRef as React.RefObject<HTMLDivElement>} articleRef={articleRef as React.RefObject<HTMLElement>} entryRef="e1" />,
    )
    await waitFor(() => expect(article.classList.contains('lumi-paged-track')).toBe(true))
    rerender(
      <ReaderPager enabled={false} containerRef={containerRef as React.RefObject<HTMLDivElement>} articleRef={articleRef as React.RefObject<HTMLElement>} entryRef="e1" />,
    )
    expect(screen.queryByLabelText('页码')).toBeNull()
    expect(container.classList.contains('lumi-paged-clip')).toBe(false)
    expect(article.classList.contains('lumi-paged-track')).toBe(false)
    expect(article.style.transform).toBe('')
    expect(article.style.columnWidth).toBe('')
  })

  it('下一页/上一页平移 + 页码指示；末页「下一页」禁用不被截断', async () => {
    setup(2400)
    await waitFor(() => expect(screen.getByText('1 / 3')).toBeInTheDocument())
    const article = document.querySelector('.lumi-reader-article') as HTMLElement

    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(screen.getByText('2 / 3')).toBeInTheDocument())
    expect(article.style.transform).toBe('translateX(-800px)')

    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(screen.getByText('3 / 3')).toBeInTheDocument())
    expect(article.style.transform).toBe('translateX(-1600px)')
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '上一页' })).not.toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '上一页' }))
    await waitFor(() => expect(screen.getByText('2 / 3')).toBeInTheDocument())
  })

  it('左右方向键翻页；页码变化写入既有阅读位置记录（ratio + 锚文本）', async () => {
    setup(2400)
    await waitFor(() => expect(screen.getByText('1 / 3')).toBeInTheDocument())
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    await waitFor(() => expect(screen.getByText('2 / 3')).toBeInTheDocument())
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    await waitFor(() => expect(screen.getByText('3 / 3')).toBeInTheDocument())
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    await waitFor(() => expect(screen.getByText('2 / 3')).toBeInTheDocument())

    const saved = JSON.parse(
      localStorage.getItem('lumirss-reading-positions') ?? '{}',
    ) as { byRef?: Record<string, { ratio: number; anchorText: string | null }> }
    expect(saved.byRef?.e1?.ratio).toBeCloseTo(0.5)
    expect(saved.byRef?.e1?.anchorText).toBeTruthy()
  })

  it('进入分页时按既有阅读位置记录近似恢复（ratio → 页码）', async () => {
    saveReadingPosition('e9', {
      ratio: 0.5,
      anchorText: null,
      savedAt: '2026-09-23T00:00:00Z',
    })
    setup(2400, 'e9')
    await waitFor(() => expect(screen.getByText('2 / 3')).toBeInTheDocument())
  })

  it('字号/视口变化（resize）重算页数，位置保持在 ±1 页内', async () => {
    const { article } = setup(2400)
    await waitFor(() => expect(screen.getByText('1 / 3')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(screen.getByText('2 / 3')).toBeInTheDocument())

    // 旋转/字号变化：内容重排为 6 页（4800 = 6 × 800）
    Object.defineProperty(article, 'scrollWidth', { value: 4800, configurable: true })
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })
    // jsdom 零矩形下锚点落回原页码（位移 0 页，满足 ±1 页内）；
    // 页数已按新内容重算。
    await waitFor(() => expect(screen.getByText('2 / 6')).toBeInTheDocument())
  })
})
