/** useModalA11y — 复用的模态无障碍行为（0020 Gate 3 提取）。
 *
 *  encapsulates 打开时：
 * - 初始焦点落到面板内第一个可聚焦元素（无则面板自身）；
 * - 背景滚动锁定（body overflow hidden，关闭恢复原值）；
 * - Escape 关闭；
 * - Tab / Shift+Tab 焦点陷阱（在面板内循环）；
 * - 关闭时把焦点还给打开前的元素。
 *
 * 此前 Sheet 与 Dialog 各自内联同一套逻辑，而 MobileSettingsScreen 完全
 * 缺失（无 Escape / 焦点陷阱 / 还焦 / 滚动锁）。提取为共享 hook 后三者
 * 复用同一实现，避免"弱自定义模态"。遮罩点击关闭等组件特有交互仍由
 * 各组件自行处理（本 hook 只负责键盘/焦点/滚动）。 */

import { useEffect, type RefObject } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

export function useModalA11y(
  panelRef: RefObject<HTMLElement | null>,
  open: boolean,
  onClose: () => void,
): void {
  useEffect(() => {
    if (!open) return
    const panel = panelRef.current
    const lastActive = document.activeElement as HTMLElement | null
    // 初始焦点：第一个可聚焦元素（如 ✕ 关闭钮）；没有则面板自身
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? panel)?.focus()

    // 背景滚动锁定（关闭时恢复原值）
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      // 焦点 trap：Tab 在面板内循环
      const nodes = [...(panel?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])].filter(
        (n) => n.offsetParent !== null,
      )
      if (nodes.length === 0) return
      const firstNode = nodes[0]!
      const lastNode = nodes[nodes.length - 1]!
      if (e.shiftKey && document.activeElement === firstNode) {
        e.preventDefault()
        lastNode.focus()
      } else if (!e.shiftKey && document.activeElement === lastNode) {
        e.preventDefault()
        firstNode.focus()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.body.style.overflow = prevOverflow
      lastActive?.focus()
    }
  }, [open, onClose, panelRef])
}
