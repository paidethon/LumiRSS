/** reader-pagination — N052 分页阅读 / N053 点按翻页区的共享纯逻辑。
 *
 * 原则同 lib/reader-tools.ts：几何/DOM 副作用留在组件（ReaderPager），
 * 本模块只放可测试的常量与纯函数。
 *
 * 分页几何（CSS 多栏方案）：
 * - clip 容器（Reader 滚动容器）overflow hidden，水平 padding = page
 *   margin（每页左右留白，clip 边界在 padding box）；
 * - 多栏元素（正文 article）height = 容器内容高，column-width = 容器
 *   内容宽 - 2×margin，column-gap = 2×margin，column-fill: auto；
 * - 栏宽 + 栏距 = stride = 容器 clientWidth，第 k 栏未平移时起点 =
 *   k×stride + margin，平移 -k×stride 后恒定出现在 [margin, margin+W]；
 * - 栏数（页数）= round(article.scrollWidth / stride)：溢出栏使
 *   scrollWidth 恰为 N×stride（含左右 padding 相互抵消），round 吸收
 *   亚像素噪声。
 */

import { clamp } from './clamp'

/** 栏间空隙 = 2 × 页边距：翻页后每页两侧各留一个 margin 的视觉空白。 */
export function pagedColumnGap(pageMarginPx: number): number {
  return Math.max(0, pageMarginPx) * 2
}

export interface PagedLayout {
  /** 单栏宽度（= 每页正文宽度） */
  columnWidth: number
  columnGap: number
  /** 翻一页的位移步长 = columnWidth + columnGap（= 容器 clientWidth） */
  stride: number
  /** 总页数（≥1；内容为空/未量出时也是 1 页） */
  pageCount: number
}

/** 纯计算：由 clip 容器尺寸、页边距与多栏后的 scrollWidth 得出分页布局。
 * 任何非有限/非正输入都收敛为 1 页，绝不产生 NaN 布局。 */
export function computePagedLayout(input: {
  viewportWidth: number
  pageMarginPx: number
  /** 多栏样式应用后正文 article 的 scrollWidth */
  articleScrollWidth: number
}): PagedLayout {
  const viewport = Number.isFinite(input.viewportWidth) ? Math.max(0, input.viewportWidth) : 0
  const gap = pagedColumnGap(input.pageMarginPx)
  const columnWidth = Math.max(0, viewport - gap)
  const stride = columnWidth + gap
  const scrollWidth = Number.isFinite(input.articleScrollWidth)
    ? Math.max(0, input.articleScrollWidth)
    : 0
  const pageCount = stride > 0 && scrollWidth > 0 ? Math.max(1, Math.round(scrollWidth / stride)) : 1
  return { columnWidth, columnGap: gap, stride, pageCount }
}

/** 页码钳制到 [0, pageCount-1]（pageCount 非法时回到 0）。 */
export function clampPage(page: number, pageCount: number): number {
  const count = Number.isFinite(pageCount) && pageCount >= 1 ? Math.floor(pageCount) : 1
  return clamp(Math.floor(Number.isFinite(page) ? page : 0), 0, count - 1)
}

/** 翻页目标位移（px，translateX 取负值由组件施加）。 */
export function pageOffset(page: number, stride: number): number {
  return clampPage(page, Number.MAX_SAFE_INTEGER) * Math.max(0, stride)
}

// ---- N053：点按翻页区 ----

/** 区域大小档位 → 前后命中区占视口宽/高的比例（'off' 不命中）。 */
export const TAP_ZONE_RATIOS: Record<Exclude<'off' | 'small' | 'large', 'off'>, number> = {
  small: 0.22,
  large: 0.4,
} as const

export type TapZoneAxis = 'horizontal' | 'vertical'
export type TapZoneSize = 'off' | 'small' | 'large'

/** 纯计算：点按落在翻页区时的翻页方向。
 * horizontal：左 22%/40% → 上一页，右 → 下一页；vertical：上/下。
 * 中部（或 'off'）返回 null = 不翻页。 */
export function tapZoneDirection(input: {
  /** 点按点相对 clip 容器左上角的坐标 */
  x: number
  y: number
  width: number
  height: number
  axis: TapZoneAxis
  size: TapZoneSize
}): 1 | -1 | null {
  if (input.size === 'off') return null
  const ratio = TAP_ZONE_RATIOS[input.size]
  const { x, y, width, height } = input
  if (!Number.isFinite(x) || !Number.isFinite(y) || width <= 0 || height <= 0) return null
  if (input.axis === 'horizontal') {
    if (x < width * ratio) return -1
    if (x > width * (1 - ratio)) return 1
    return null
  }
  if (y < height * ratio) return -1
  if (y > height * (1 - ratio)) return 1
  return null
}

// ---- 页锚点（复用阅读位置 anchorText 机制）----

/** 正文块选择器（与 Reader.ANCHOR_SELECTOR / reading-position 同一契约，
 * 作用域限定在正文 article 内——分页只关心正文流，不含头部工具面板）。 */
export const PAGED_ANCHOR_SELECTOR = [
  'p',
  'li',
  'pre',
  'blockquote',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
]
  .map((tag) => `.article-content ${tag}`)
  .join(', ')

/** 纯计算：块在「未平移坐标系」中的页内 X（用于定位当前页首块 /
 * 块所在页）。articleRectLeft 为 article 自身视口左缘；currentPage 为
 * 当前已施加的平移页码（换算时抵消 translate）。 */
export function blockPageX(input: {
  blockLeft: number
  articleLeft: number
  currentPage: number
  stride: number
}): number {
  if (input.stride <= 0) return 0
  return input.blockLeft - input.articleLeft + input.currentPage * input.stride
}

export interface BlockHit {
  el: Element
  /** 未平移坐标系中的页内 X（blockPageX 结果） */
  pageX: number
  /** 视口 top（同栏内按纵向排序取最上方） */
  top: number
}

/** 纯计算：当前页的首个正文块（先按所在栏取最小 X，同栏取最上）。
 * 找不到（空正文/异常布局）返回 null——调用方诚实跳过锚定。 */
export function pickPageAnchor(blocks: BlockHit[], page: number, stride: number): Element | null {
  const start = page * stride
  const end = start + stride
  let best: BlockHit | null = null
  for (const hit of blocks) {
    if (hit.pageX < start - 1 || hit.pageX >= end) continue
    if (
      best === null ||
      hit.pageX < best.pageX - 1 ||
      (Math.abs(hit.pageX - best.pageX) <= 1 && hit.top < best.top)
    ) {
      best = hit
    }
  }
  return best?.el ?? null
}

/** 纯计算：锚点块所在的页码（钳制后返回；布局异常时 0）。 */
export function pageOfAnchor(input: { pageX: number; stride: number; pageCount: number }): number {
  if (input.stride <= 0) return 0
  return clampPage(Math.floor(input.pageX / input.stride), input.pageCount)
}
