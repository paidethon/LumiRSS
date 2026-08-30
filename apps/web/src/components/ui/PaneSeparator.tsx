/** PaneSeparator — 三栏拖拽分隔条（0010 Gate C）。
 *
 * 借鉴 OrigRead-Desktop 分栏约束模式 + Folo 实测 separator 语义
 * （role="separator" + aria-valuenow/min/max，均为 inspired）：
 * - pointer 拖拽调宽（clamp min/max）；
 * - 键盘 ←/→ 微调 ±10px（focus 时）；
 * - 双击重置默认宽度；
 * - 视觉：4px 热区（hover/active 加宽到 accent），不占内容空间。 */

import { useCallback, useRef } from 'react'
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

  const clamp = useCallback(
    (w: number) => Math.min(max, Math.max(min, Math.round(w))),
    [min, max],
  )

  /** pointer 拖拽：监听 window（拖出分隔条热区仍有效） */
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    dragging.current = true
    const startX = e.clientX
    const startWidth = value

    const onMove = (ev: PointerEvent) => {
      if (!dragging.current) return
      // 分隔条在栏右侧：向右拖 = 加宽
      onChange(clamp(startWidth + (ev.clientX - startX)))
    }
    const onUp = () => {
      dragging.current = false
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      onChange(clamp(value - 10))
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      onChange(clamp(value + 10))
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
