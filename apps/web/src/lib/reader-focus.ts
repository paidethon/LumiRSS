/** reader-focus — 专注阅读模式（F17 系列 AaPanel 开关的纯逻辑部分）。
 *
 * 行为：正文视口中心最近的块元素标记为「正在阅读」（data 属性），
 * 其余块在 CSS 中降透明度。DOM 侵入只有 data 属性（无类名污染、
 * 不改文本），样式集中在 index.css 的 [data-lumi-focus] 规则。 */

/** 参与聚焦判定的正文块（与查找/朗读同族：段落级元素）。 */
export const FOCUS_BLOCK_SELECTOR =
  '.article-content :is(p, li, pre, blockquote, h1, h2, h3, h4, h5, h6, table, figure)'

export interface BlockRect {
  top: number
  bottom: number
}

/** 纯计算：中心离视口中心最近的块索引（并列取更靠前者；空数组 → -1）。 */
export function pickFocusIndex(
  rects: BlockRect[],
  viewportCenter: number,
): number {
  let best = -1
  let bestDistance = Number.POSITIVE_INFINITY
  for (let i = 0; i < rects.length; i += 1) {
    const rect = rects[i]!
    const center = (rect.top + rect.bottom) / 2
    const distance = Math.abs(center - viewportCenter)
    if (distance < bestDistance) {
      bestDistance = distance
      best = i
    }
  }
  return best
}

/** 标记当前聚焦块（滚动帧内调用；幂等）。 */
export function applyFocusActive(
  article: HTMLElement,
  viewportCenter: number,
): void {
  const blocks = Array.from(
    article.querySelectorAll<HTMLElement>(FOCUS_BLOCK_SELECTOR),
  )
  const index = pickFocusIndex(
    blocks.map((el) => {
      const rect = el.getBoundingClientRect()
      return { top: rect.top, bottom: rect.bottom }
    }),
    viewportCenter,
  )
  blocks.forEach((el, i) => {
    if (i === index) el.setAttribute('data-lumi-focus-active', '')
    else el.removeAttribute('data-lumi-focus-active')
  })
}

/** 关闭专注模式时清理全部标记与模式开关（幂等）。 */
export function clearFocusActive(article: HTMLElement): void {
  article.removeAttribute('data-lumi-focus')
  for (const el of article.querySelectorAll('[data-lumi-focus-active]')) {
    el.removeAttribute('data-lumi-focus-active')
  }
}
