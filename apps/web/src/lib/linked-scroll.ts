/** linked-scroll — F053 双语关联滚动（纯逻辑核心，可单测）。
 *
 * - visibleIndex：计算当前可见块（data-lb-index 最大占比块）；
 * - counterpartScrollTo：原文 ↔ 翻译面板互查（数组下标一一对应，缺段
 *   时对方列表可能更短——返回 null，调用方不滚动，不抛错）；
 * - LoopGuard：同步窗口（600ms）内忽略回弹事件，防双向滚动死循环；
 * - 开关关闭 → 调用方不挂 scroll 监听（互不干扰）。
 */

export const LINKED_SCROLL_WINDOW_MS = 600

/** 容器内可见的 data-lb-index（最大可见面积者）；无可见解返回 null。 */
export function computeVisibleIndex(container: HTMLElement): number | null {
  const rect = container.getBoundingClientRect()
  const blocks = container.querySelectorAll<HTMLElement>('[data-lb-index]')
  let best: { index: number; ratio: number } | null = null
  blocks.forEach((block) => {
    const blockRect = block.getBoundingClientRect()
    const visibleTop = Math.max(blockRect.top, rect.top)
    const visibleBottom = Math.min(blockRect.bottom, rect.bottom)
    const visible = Math.max(0, visibleBottom - visibleTop)
    const height = Math.max(1, blockRect.height)
    const ratio = visible / height
    const index = Number(block.dataset.lbIndex)
    if (!Number.isFinite(index)) return
    if (best === null || ratio > best.ratio) best = { index, ratio }
  })
  return best === null ? null : (best as { index: number; ratio: number }).index
}

/** 反向映射：sourceIndex 在翻译块列表中的位置（原块 i ↔ 翻译块 i；
 * 长度不齐（缺段）→ null，不抛错）。 */
export function counterpartIndex(
  index: number,
  ownCount: number,
  otherCount: number,
): number | null {
  if (index < 0 || index >= ownCount || index >= otherCount) return null
  return index
}

/** 循环守卫：600ms 窗口内的回弹事件被忽略。 */
export class LoopGuard {
  private lastAt = Number.NEGATIVE_INFINITY

  /** 允许通过返回 true，并记录本次时间；窗口内（<600ms）返回 false。 */
  allow(now: number): boolean {
    if (now - this.lastAt < LINKED_SCROLL_WINDOW_MS) return false
    this.lastAt = now
    return true
  }

  /** 主动触发（用户直接滚动本侧）时调用：重置窗口。 */
  touch(now: number): void {
    this.lastAt = now
  }

  reset(): void {
    this.lastAt = Number.NEGATIVE_INFINITY
  }
}

/** 滚动到指定 index 的块（容器的第 index 个 [data-lb-index]）。 */
export function scrollToBlock(container: HTMLElement, index: number): boolean {
  const block = container.querySelector<HTMLElement>(`[data-lb-index="${index}"]`)
  if (block === null) return false
  block.scrollIntoView({ block: 'center', behavior: 'auto' })
  return true
}
