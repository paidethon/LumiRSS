/** ReaderPager — N052 分页阅读 + N053 点按翻页区（Reader 集成组件）。
 *
 * 分页实现（CSS 多栏，几何契约见 lib/reader-pagination.ts）：
 * - clip = Reader 滚动容器：挂 .lumi-paged-clip（overflow hidden），
 *   每页左右留白由容器既有 padding（page margin 变量）提供；
 * - track = 正文 article：内联 height / column-width / column-gap /
 *   column-fill:auto（.lumi-paged-track），transform 位移翻页；
 * - 页数 = round(article.scrollWidth / stride)，末页 column-fill:auto
 *   自然收尾不截断；
 * - 字号/行距/宽度/边距/视口变化 → 重测量，并用阅读位置的 anchorText
 *   机制把当前页首块重新锚定到新页码（近似位置，±1 页内）；
 * - 页码变化经既有 reading-position 存储按 ratio + anchorText 保存，
 *   切走再回来时大致落在原页；
 * - 减少动效偏好下位移无过渡（CSS 侧瞬时跳页）。
 *
 * N053 点按翻页区（仅分页模式生效）：
 * - 设置 readerTapZoneAxis（左右/上下）× readerTapZoneSize（关/小/大）；
 * - 点击命中前后翻页区 → 翻页；命中链接、非空选区、横向可滚元素
 *   （表格/代码块）绝不翻页；可见翻页按钮始终保留（可访问性）。
 *
 * 上一页/下一页按钮 + 左右方向键 + 页码指示 n/N；44px 触控目标。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useAppSettings } from '../store/app-settings'
import { captureAnchorText, findAnchorElement, loadReadingPosition, saveReadingPosition } from '../lib/reading-position'
import {
  PAGED_ANCHOR_SELECTOR,
  blockPageX,
  clampPage,
  computePagedLayout,
  pageOfAnchor,
  pageOffset,
  pickPageAnchor,
  tapZoneDirection,
} from '../lib/reader-pagination'
import { IconButton } from './ui/IconButton'

/** 章节可见性变化（N051）会改变正文流——分页需要重测量。事件名与
 * ArticleToc（派发方）保持同一常量语义。 */
const CHAPTER_CHANGE_EVENT = 'lumi:chapter-change'

interface PagedState {
  page: number
  pageCount: number
}

export interface ReaderPagerProps {
  /** 是否启用分页（阅读模式 = 分页） */
  enabled: boolean
  /** Reader 滚动容器（clip） */
  containerRef: React.RefObject<HTMLDivElement | null>
  /** 正文 article（多栏 track） */
  articleRef: React.RefObject<HTMLElement | null>
  /** 当前文章（切换时回到第 1 页并按既有位置记录恢复近似页） */
  entryRef: string | null
}

/** 判断事件目标是否在交互控件内（方向键/点按都不应劫持）。 */
function isInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  if (target.closest('input, textarea, select, button, a, [contenteditable="true"], [role="textbox"]') !== null) {
    return true
  }
  return false
}

/** 目标到 clip 之间存在横向可滚元素（表格/代码块）→ 点按交给其自身滚动。 */
function hasHorizontalScroller(target: Element, stop: Element | null): boolean {
  let node: Element | null = target
  while (node !== null && node !== stop) {
    if (node.scrollWidth > node.clientWidth + 1 && node.clientWidth > 0) return true
    node = node.parentElement
  }
  return false
}

export function ReaderPager({ enabled, containerRef, articleRef, entryRef }: ReaderPagerProps) {
  const settings = useAppSettings((s) => s.settings)
  const tapAxis = settings.readerTapZoneAxis
  const tapSize = settings.readerTapZoneSize
  const [state, setState] = useState<PagedState>({ page: 0, pageCount: 1 })
  const stateRef = useRef(state)
  stateRef.current = state
  /** 重测量锁：测量 effect 与页码 effect 都会写 transform，避免互踢。 */
  const suppressPageEffectRef = useRef(false)

  /** 收集正文块命中信息（未平移坐标系，可指定页码覆盖；jsdom 无布局 →
   * 全 0 → 块都落在指定页，真实浏览器拿到真实几何）。 */
  const collectBlocks = useCallback(
    (pageOverride?: number): { stride: number; page: number; blocks: { el: Element; pageX: number; top: number }[] } | null => {
      const article = articleRef.current
      const container = containerRef.current
      if (article === null || container === null) return null
      const stride = Math.max(1, container.clientWidth)
      const page = pageOverride ?? stateRef.current.page
      const articleLeft = article.getBoundingClientRect().left
      const blocks = Array.from(article.querySelectorAll(PAGED_ANCHOR_SELECTOR)).map((el) => ({
        el,
        pageX: blockPageX({
          blockLeft: el.getBoundingClientRect().left,
          articleLeft,
          currentPage: page,
          stride,
        }),
        top: el.getBoundingClientRect().top,
      }))
      return { stride, page, blocks }
    },
    [articleRef, containerRef],
  )

  /** 页码状态落库（stateRef 同步更新——同一提交内后跑的 effect 读到的
   * 不能是旧页码，否则恢复/锚定会被过期值覆盖）。 */
  const commitState = useCallback((next: PagedState) => {
    stateRef.current = next
    setState(next)
  }, [])

  /** 测量并应用分页布局；keepAnchor = 重排前记住当前页首块，重排后落回
   * 其所在页（字号/旋转/章节切换 → 位置近似保持）。 */
  const measure = useCallback(
    (opts: { keepAnchor: boolean; resetToSaved: boolean }) => {
      const article = articleRef.current
      const container = containerRef.current
      if (article === null || container === null) return
      const viewportWidth = container.clientWidth
      const viewportHeight = container.clientHeight
      if (viewportWidth <= 0 || viewportHeight <= 0) return

      // 重排前：记住当前页首块的锚文本（若需要保持位置）
      let anchorText: string | null = null
      if (opts.keepAnchor) {
        const current = collectBlocks()
        const anchorEl = current === null ? null : pickPageAnchor(current.blocks, current.page, current.stride)
        anchorText = captureAnchorText(anchorEl)
      }

      // 先铺多栏（高度/栏宽/栏距），随后实测 scrollWidth 收敛页数。
      const margin = (() => {
        const cs = window.getComputedStyle(article)
        const parsed = Number.parseFloat(cs.paddingLeft)
        return Number.isFinite(parsed) ? parsed : 0
      })()
      article.style.height = `${viewportHeight}px`
      article.style.columnWidth = `${Math.max(0, viewportWidth - margin * 2)}px`
      article.style.columnGap = `${margin * 2}px`
      article.style.columnFill = 'auto'

      const layout = computePagedLayout({
        viewportWidth,
        pageMarginPx: margin,
        articleScrollWidth: article.scrollWidth,
      })

      let page = 0
      if (opts.resetToSaved && entryRef !== null) {
        // 进入分页：按既有阅读位置记录近似恢复（锚点优先，ratio 回退）
        const saved = loadReadingPosition(entryRef)
        if (saved !== null) {
          const anchorEl = findAnchorElement(article, saved.anchorText)
          if (anchorEl !== null) {
            const articleLeft = article.getBoundingClientRect().left
            page = pageOfAnchor({
              pageX: blockPageX({
                blockLeft: anchorEl.getBoundingClientRect().left,
                articleLeft,
                currentPage: 0,
                stride: layout.stride,
              }),
              stride: layout.stride,
              pageCount: layout.pageCount,
            })
          } else if (layout.pageCount > 1) {
            page = clampPage(Math.round(saved.ratio * (layout.pageCount - 1)), layout.pageCount)
          }
        }
      } else if (opts.keepAnchor && anchorText !== null) {
        const anchorEl = findAnchorElement(article, anchorText)
        if (anchorEl !== null) {
          const articleLeft = article.getBoundingClientRect().left
          page = pageOfAnchor({
            pageX: blockPageX({
              blockLeft: anchorEl.getBoundingClientRect().left,
              articleLeft,
              currentPage: stateRef.current.page,
              stride: layout.stride,
            }),
            stride: layout.stride,
            pageCount: layout.pageCount,
          })
        } else {
          page = clampPage(stateRef.current.page, layout.pageCount)
        }
      } else {
        page = clampPage(stateRef.current.page, layout.pageCount)
      }
      page = clampPage(page, layout.pageCount)

      suppressPageEffectRef.current = true
      article.style.transform = `translateX(-${pageOffset(page, layout.stride)}px)`
      commitState({ page, pageCount: layout.pageCount })
    },
    [articleRef, containerRef, collectBlocks, commitState, entryRef],
  )

  // 启用/禁用：挂多栏样式与 clip 类；禁用或卸载时完整还原内联样式。
  useEffect(() => {
    const article = articleRef.current
    const container = containerRef.current
    if (!enabled || article === null || container === null) return
    container.classList.add('lumi-paged-clip')
    article.classList.add('lumi-paged-track')
    measure({ keepAnchor: false, resetToSaved: true })
    return () => {
      container.classList.remove('lumi-paged-clip')
      article.classList.remove('lumi-paged-track')
      article.style.height = ''
      article.style.columnWidth = ''
      article.style.columnGap = ''
      article.style.columnFill = ''
      article.style.transform = ''
      commitState({ page: 0, pageCount: 1 })
    }
    // entryRef 变化 = 换文章（Reader 按 entryRef 重挂载正文，样式会随
    // innerHTML 重设而失效）→ 重新进入分页并按位置记录恢复。
  }, [enabled, entryRef, articleRef, containerRef, measure, commitState])

  // 排版/视口变化重测量（字号/行距/宽度/边距/窗口尺寸/章节切换），
  // 位置经锚点近似保持（±1 页内）。
  useEffect(() => {
    if (!enabled) return
    measure({ keepAnchor: true, resetToSaved: false })
    const onResize = () => measure({ keepAnchor: true, resetToSaved: false })
    window.addEventListener('resize', onResize)
    document.addEventListener(CHAPTER_CHANGE_EVENT, onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      document.removeEventListener(CHAPTER_CHANGE_EVENT, onResize)
    }
  }, [
    enabled,
    measure,
    settings.readerFontSize,
    settings.readerLineHeight,
    settings.readerContentWidth,
    settings.readerPageMargin,
    settings.readerJustify,
    settings.readerTextIndent,
  ])

  /** 施加页码位移（翻页/键盘）。 */
  const goTo = useCallback(
    (page: number) => {
      const article = articleRef.current
      const container = containerRef.current
      if (!enabled || article === null || container === null) return
      const layout = computePagedLayout({
        viewportWidth: container.clientWidth,
        pageMarginPx: (() => {
          const parsed = Number.parseFloat(window.getComputedStyle(article).paddingLeft)
          return Number.isFinite(parsed) ? parsed : 0
        })(),
        articleScrollWidth: article.scrollWidth,
      })
      const next = clampPage(page, layout.pageCount)
      const current = stateRef.current.page
      if (next === current) return
      article.style.transform = `translateX(-${pageOffset(next, layout.stride)}px)`
      suppressPageEffectRef.current = true
      // 先落 ref 再收集锚块：锚点按新页码坐标系取（页码变化写入既有
      // 阅读位置记录，ratio + 锚文本，切走再回来近似还原）。
      commitState({ ...stateRef.current, page: next })
      if (entryRef !== null) {
        const currentBlocks = collectBlocks(next)
        const anchorEl =
          currentBlocks === null ? null : pickPageAnchor(currentBlocks.blocks, next, layout.stride)
        saveReadingPosition(entryRef, {
          ratio: layout.pageCount <= 1 ? 0 : next / (layout.pageCount - 1),
          anchorText: captureAnchorText(anchorEl),
          savedAt: new Date().toISOString(),
        })
      }
    },
    [enabled, articleRef, containerRef, collectBlocks, commitState, entryRef],
  )

  const pageBy = useCallback(
    (direction: 1 | -1) => {
      goTo(stateRef.current.page + direction)
    },
    [goTo],
  )

  // 左右方向键翻页（输入控件内不劫持；系统修饰键组合放过）。
  useEffect(() => {
    if (!enabled) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return
      if (isInteractiveTarget(event.target)) return
      if (event.key === 'ArrowRight') {
        event.preventDefault()
        pageBy(1)
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault()
        pageBy(-1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled, pageBy])

  // N053：点按翻页区（容器上的点击委托；链接/选区/横向滚动元素不翻页）。
  useEffect(() => {
    if (!enabled) return
    const container = containerRef.current
    if (container === null) return
    const onClick = (event: MouseEvent) => {
      const target = event.target
      if (!(target instanceof Element)) return
      // 翻页区让位：链接、可见按钮、文本选区、横向可滚元素（表格/代码）
      if (target.closest('a, button') !== null) return
      const selection = typeof window.getSelection === 'function' ? window.getSelection() : null
      if (selection !== null && !selection.isCollapsed && selection.anchorNode !== null) {
        return
      }
      if (hasHorizontalScroller(target, container)) return
      const rect = container.getBoundingClientRect()
      const direction = tapZoneDirection({
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
        width: rect.width,
        height: rect.height,
        axis: tapAxis,
        size: tapSize,
      })
      if (direction === null) return
      pageBy(direction)
    }
    container.addEventListener('click', onClick)
    return () => container.removeEventListener('click', onClick)
  }, [enabled, containerRef, tapAxis, tapSize, pageBy])

  // 页码状态 → transform（measure 已写过的帧不重复写）。
  useEffect(() => {
    if (suppressPageEffectRef.current) {
      suppressPageEffectRef.current = false
      return
    }
    const article = articleRef.current
    const container = containerRef.current
    if (!enabled || article === null || container === null) return
    const layout = computePagedLayout({
      viewportWidth: container.clientWidth,
      pageMarginPx: (() => {
        const parsed = Number.parseFloat(window.getComputedStyle(article).paddingLeft)
        return Number.isFinite(parsed) ? parsed : 0
      })(),
      articleScrollWidth: article.scrollWidth,
    })
    article.style.transform = `translateX(-${pageOffset(state.page, layout.stride)}px)`
  }, [enabled, state, articleRef, containerRef])

  if (!enabled) return null

  return (
    <div
      className="absolute bottom-6 right-4 z-10 flex flex-col items-end gap-1.5"
      data-lumi-pager-nav=""
    >
      {/* F061：分页迷你地图——当前页/总页可视化 + 拖动/点击跳页条。
          原生 range：拖动、点击定位、键盘方向键/Home/End 免费获得；
          goTo 内部钳制页码并保存阅读位置。 */}
      <div className="flex items-center rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] px-2.5 py-1.5 shadow-[var(--lumi-shadow-popover)]">
        <input
          type="range"
          dir="ltr"
          min={1}
          max={state.pageCount}
          step={1}
          value={Math.min(state.page + 1, state.pageCount)}
          aria-label="跳页（当前页 / 总页）"
          aria-valuetext={`第 ${state.page + 1} 页，共 ${state.pageCount} 页`}
          data-lumi-pager-map=""
          onChange={(event) => {
            const page = Number.parseInt(event.target.value, 10)
            if (Number.isFinite(page)) goTo(page - 1)
          }}
          className="lumi-slider w-40 min-h-11"
        />
      </div>
      <output
        aria-live="polite"
        aria-label="页码"
        data-lumi-pager-indicator=""
        className="rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] px-2.5 py-1 text-xs tabular-nums text-[var(--lumi-text-secondary)] shadow-[var(--lumi-shadow-popover)]"
      >
        {state.page + 1} / {state.pageCount}
      </output>
      <div className="flex flex-col gap-1.5">
        <IconButton
          size="lg"
          icon={<ChevronLeft aria-hidden className="size-5" />}
          label="上一页"
          disabled={state.page <= 0}
          onClick={() => pageBy(-1)}
          className="border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-popover)]"
        />
        <IconButton
          size="lg"
          icon={<ChevronRight aria-hidden className="size-5" />}
          label="下一页"
          disabled={state.page >= state.pageCount - 1}
          onClick={() => pageBy(1)}
          className="border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-popover)]"
        />
      </div>
      {/* 点按翻页区委托挂在 clip 容器上（见上方 effect）——
          说明文案给键盘/触屏用户可发现的提示。 */}
      <p
        role="note"
        aria-label="点按翻页区说明"
        className="max-w-40 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-2 py-1 text-right text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)] shadow-md"
      >
        {tapSize === 'off'
          ? '点按翻页已关闭，使用按钮或左右方向键。'
          : tapAxis === 'horizontal'
            ? '点按页面左右边缘翻页。'
            : '点按页面上下边缘翻页。'}
      </p>
    </div>
  )
}

export default ReaderPager
