/** ReaderKeyNav — N070 纯键盘阅读定位（组件接线 + 位置指示 chip）。
 *
 * 设置开启（readerKeyNav，设备本地）后监听 window keydown：
 * - Alt+↓/↑ 类别内循环跳转，Alt+Shift+↓/↑ 切换类别（顺序会话粘滞）；
 * - 跳转 = scrollIntoView + 焦点移交（读屏跟随），绝不触碰已读状态；
 * - 左下角指示 chip（aria-live）：「链接 3/12」，换文重置。
 * 守卫复用全局快捷键同源判定（IME / 可编辑元素 / 模态打开）。 */

import { useEffect, useRef, useState } from 'react'
import {
  KEYNAV_CATEGORIES,
  annotationTargetElements,
  collectKeyNavTargets,
  cycleIndex,
  keyNavEventAction,
  keyNavEventAllowed,
  loadKeyNavCategory,
  saveKeyNavCategory,
  switchCategory,
  type KeyNavCategoryKey,
} from '../lib/reader-keynav'

export interface KeyNavPosition {
  category: KeyNavCategoryKey
  categoryLabel: string
  index: number
  total: number
  /** 类别为空时的诚实提示（0 目标）。 */
  empty: boolean
}

/** 换文章重置由调用方以 key=entryRef 重挂载承载（位置状态随组件重建；
 * 类别序仍按会话粘滞读取）。 */
export function ReaderKeyNav({
  entryRef,
  enabled,
  containerRef,
}: {
  entryRef: string
  enabled: boolean
  /** Reader 滚动容器（.lumi-reader-article 的父级）。 */
  containerRef: React.RefObject<HTMLElement | null>
}) {
  const [position, setPosition] = useState<KeyNavPosition | null>(null)
  const categoryRef = useRef<KeyNavCategoryKey>(loadKeyNavCategory())
  const indexRef = useRef(-1)

  useEffect(() => {
    if (!enabled || entryRef === null) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (!keyNavEventAllowed(event)) return
      const action = keyNavEventAction(event)
      if (action === null) return
      const article = containerRef.current?.querySelector('.lumi-reader-article')
      if (!(article instanceof HTMLElement)) return

      if (action.kind === 'switch') {
        const next = switchCategory(categoryRef.current, action.direction)
        categoryRef.current = next
        saveKeyNavCategory(next)
        indexRef.current = -1
      }

      const category = categoryRef.current
      const label = KEYNAV_CATEGORIES.find((c) => c.key === category)?.label ?? category
      const targets = collectKeyNavTargets(
        article,
        category,
        category === 'annotation' ? annotationTargetElements(article, entryRef) : [],
      )
      const nextIndex = cycleIndex(indexRef.current, targets.length, action.direction)
      if (nextIndex === null) {
        // 空类别：诚实提示（0 目标），不假装跳转
        setPosition({ category, categoryLabel: label, index: -1, total: 0, empty: true })
        return
      }
      indexRef.current = nextIndex
      const target = targets[nextIndex]
      if (target instanceof HTMLElement) {
        target.scrollIntoView({ block: 'center' })
        if (target.tabIndex < 0) target.tabIndex = -1
        target.focus({ preventScroll: true })
      }
      setPosition({
        category,
        categoryLabel: label,
        index: nextIndex,
        total: targets.length,
        empty: false,
      })
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled, entryRef, containerRef])

  if (!enabled || position === null) return null

  return (
    <div
      data-testid="keynav-indicator"
      role="status"
      aria-live="polite"
      className="fixed bottom-24 left-4 z-30 rounded-full border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] px-3 py-1.5 text-xs text-[var(--lumi-text-secondary)] shadow-[var(--lumi-shadow-popover)] print:hidden"
    >
      {position.empty
        ? `${position.categoryLabel}（无目标）`
        : `${position.categoryLabel} ${position.index + 1}/${position.total}`}
    </div>
  )
}

export default ReaderKeyNav
