/** reader-para-focus — F062 逐段专注模式（纯逻辑部分；DOM 侵入仅 data 属性）。
 *
 * 与 lib/reader-focus（滚动居中自动打标）互补：本模式是显式步进——
 * 点击段落或键盘 j/k 移动「当前段」，其余段落 CSS 降透明；Esc 退出。
 * 当前段索引由 Reader（会话状态）持有，滚动只是视觉跟随，不反向改判定。
 * 样式集中在 index.css 的 [data-lumi-para-focus] 规则（同 reader-focus
 * 模式：不污染类名、不改文本）。 */

import { FOCUS_BLOCK_SELECTOR } from './reader-focus'

/** 参与逐段专注的正文块（与滚动专注/查找/朗读同一族：段落级元素）。 */
export const PARA_FOCUS_BLOCK_SELECTOR = FOCUS_BLOCK_SELECTOR

/** 收集正文块（文档序）。 */
export function getParaFocusBlocks(article: HTMLElement): HTMLElement[] {
  return Array.from(article.querySelectorAll<HTMLElement>(PARA_FOCUS_BLOCK_SELECTOR))
}

/** 纯计算：j/k 步进后的当前段索引（首段前 k → 0 末段后 j → 末段钳制；
 * 未选中（-1）时 j → 0 / k → 末段；空正文恒 -1）。 */
export function moveParaFocusIndex(
  blockCount: number,
  current: number,
  delta: 1 | -1,
): number {
  if (blockCount <= 0) return -1
  if (current < 0) return delta === 1 ? 0 : blockCount - 1
  return Math.min(blockCount - 1, Math.max(0, current + delta))
}

/** 标记当前段（幂等；其余块清除标记）。 */
export function applyParaFocusIndex(blocks: HTMLElement[], index: number): void {
  blocks.forEach((el, i) => {
    if (i === index) el.setAttribute('data-lumi-para-focus-active', '')
    else el.removeAttribute('data-lumi-para-focus-active')
  })
}

/** 退出时清理全部标记与模式开关（幂等）。 */
export function clearParaFocus(article: HTMLElement): void {
  article.removeAttribute('data-lumi-para-focus')
  for (const el of article.querySelectorAll('[data-lumi-para-focus-active]')) {
    el.removeAttribute('data-lumi-para-focus-active')
  }
}

/** 点击目标是否允许「点击段即聚焦」：链接/按钮/批注 UI/非空选区一律
 * 让位（批注点击与逐段专注共存——专注监听不吞事件，只决定自己是否
 * 响应；不 preventDefault / 不 stopPropagation）。 */
export function paraFocusClickAllowed(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  if (
    target.closest(
      'a, button, input, textarea, select, [contenteditable="true"], [role="textbox"], [data-lumi-annotation], .lumi-annotation-popover, .lumi-para-link',
    ) !== null
  ) {
    return false
  }
  const selection =
    typeof window.getSelection === 'function' ? window.getSelection() : null
  if (selection !== null && !selection.isCollapsed && selection.anchorNode !== null) {
    return false
  }
  return true
}

/** 键盘事件是否允许被逐段专注消费（输入框/模态打开时不抢键）。 */
export function paraFocusKeyAllowed(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  if (
    target.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]') !==
    null
  ) {
    return false
  }
  // 真实模态打开时 j/k/Esc 归浮层（与全局快捷键的 isModalOpen 同语义）
  return document.querySelector('[aria-modal="true"]') === null
}
