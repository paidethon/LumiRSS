/** PaneSeparator — 三栏拖拽分隔条（0010 Gate C）。
 *
 * 借鉴 OrigRead-Desktop 分栏约束模式 + Folo 实测 separator 语义
 * （role="separator" + aria-valuenow/min/max，均为 inspired）：
 * - pointer 拖拽调宽（clamp min/max）；
 * - 键盘 ←/→ 微调 ±10px（focus 时）；
 * - 双击重置默认宽度；
 * - 视觉：4px 热区（hover/active 加宽到 accent），不占内容空间。
 *
 * FIX-271：拖拽释放不只靠 pointerup——pointercancel（来电/系统手势/
 * 触摸重置）与组件卸载同样必须移除 window 监听并复位 dragging，
 * 否则取消后分隔条永远跟随鼠标移动（界面被锁进拖拽态）。
 * FIX-272：拖拽期间在根元素挂 lumi-pane-dragging（user-select:none），
 * 跨过正文拖动不产生文本选区；pointerup/cancel 后恢复正常复制。 */

import { useEffect, useRef } from 'react'
import { clamp } from '../../lib/clamp'
import { cx } from './cx'

export interface PaneSeparatorProps {
  /** 当前宽度（px，aria-valuenow） */
  value: number
  min: number
  max: number
  /** 拖拽/键盘过程中的宽度更新（已 clamp 由调用方或本组件保证） */
  onChange: (width: number) => void
  /** 双击重置 */
  onReset: () => void
  /** a11y 名字（如「侧栏宽度」） */
  label: string
}

export function PaneSeparator({
  value,
  min,
  max,
  onChange,
  onReset,
  label,
}: PaneSeparatorProps) {
  const dragging = useRef(false)
  /** FIX-271：当前拖拽的 window 监听清理函数（pointerup/cancel/卸载共用）。 */
  const detachRef = useRef<(() => void) | null>(null)

  /** 统一释放：复位 dragging、摘掉选区抑制、移除全部 window 监听。 */
  const endDrag = () => {
    dragging.current = false
    document.documentElement.classList.remove('lumi-pane-dragging')
    if (detachRef.current !== null) {
      detachRef.current()
      detachRef.current = null
    }
  }

  // FIX-271：拖拽中途组件卸载（布局切换/关闭面板）也必须释放，
  // 不留下永远存活的 window pointermove 监听。
  useEffect(() => {
    return () => {
      if (detachRef.current !== null) detachRef.current()
      document.documentElement.classList.remove('lumi-pane-dragging')
    }
  }, [])

  /** pointer 拖拽：监听 window（拖出分隔条热区仍有效） */
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    if (dragging.current) return
    dragging.current = true
    // FIX-272：拖拽期间抑制文本选择（跨过内容拖动不产生选区）。
    document.documentElement.classList.add('lumi-pane-dragging')
    const startX = e.clientX
    const startWidth = value

    const onMove = (ev: PointerEvent) => {
      if (!dragging.current) return
      // 分隔条在栏右侧：向右拖 = 加宽
      onChange(clamp(startWidth + (ev.clientX - startX), min, max))
    }
    const onEnd = () => {
      endDrag()
    }
    window.addEventListener('pointermove', onMove)
    // FIX-271：pointercancel（来电/系统手势/浏览器接管触摸）后必须
    // 释放——只监听 pointerup 会让 dragging 卡在 true、监听器泄漏。
    window.addEventListener('pointerup', onEnd)
    window.addEventListener('pointercancel', onEnd)
    detachRef.current = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onEnd)
      window.removeEventListener('pointercancel', onEnd)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      onChange(clamp(value - 10, min, max))
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      onChange(clamp(value + 10, min, max))
    }
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      title={`${label}：拖拽调整，双击重置`}
      className={cx(
        'group relative z-10 w-1.5 shrink-0 cursor-col-resize self-stretch',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
      )}
    >
      {/* 视觉条（细线，hover/focus/drag 时 accent 高亮） */}
      <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-[var(--lumi-border)] transition-colors duration-[var(--lumi-motion-fast)] group-hover:bg-[var(--lumi-accent)] group-focus-visible:bg-[var(--lumi-accent)]" />
    </div>
  )
}
