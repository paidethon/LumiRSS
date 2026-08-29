/** Sheet primitive — 0009 Gate 1。
 *
 * 移动端侧滑抽屉（Drawer）：底部小屏导航/表单用。Escape 关闭、
 * 遮罩点击关闭、关闭还焦、进入时焦点入面板（AC7 / V5）。宽度由
 * className 控制（默认 80vw / max 320px）。桌面 Drawer 场景复用同一
 * 组件（side="right"）。 */

import { type ReactNode, useEffect, useId, useRef } from 'react'
import { cx } from './cx'

export interface SheetProps {
  open: boolean
  onClose: () => void
  /** 抽屉标题（aria-labelledby） */
  label: string
  children: ReactNode
  /** 滑出方向：left = 侧边导航抽屉；bottom = 底部 sheet */
  side?: 'left' | 'bottom'
}

export function Sheet({ open, onClose, label, children, side = 'left' }: SheetProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const labelId = useId()
  const lastActiveRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return
    lastActiveRef.current = document.activeElement as HTMLElement
    panelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      lastActiveRef.current?.focus()
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className={cx(
        'fixed inset-0 z-[var(--lumi-z-dialog)]',
        side === 'left' ? 'flex' : 'flex items-end',
      )}
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="absolute inset-0 bg-[var(--lumi-text-primary)]/30"
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
        tabIndex={-1}
        className={cx(
          'relative bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-dialog)]',
          'duration-[var(--lumi-motion-slow)]',
          side === 'left' &&
            'h-full w-4/5 max-w-80 border-r border-[var(--lumi-border)]',
          side === 'bottom' &&
            'max-h-[85dvh] w-full rounded-t-[var(--lumi-radius-xl)] border-t border-[var(--lumi-border)]',
        )}
      >
        <h2 id={labelId} className="sr-only">
          {label}
        </h2>
        {children}
      </div>
    </div>
  )
}
