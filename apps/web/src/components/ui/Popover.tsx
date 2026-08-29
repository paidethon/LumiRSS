/** Popover primitive — 0009 Gate 1。
 *
 * 通用浮层容器（trigger + absolute 面板，右对齐）。与 Menu 的区别：
 * 内容自由（表单/设置面板），键盘要求宽松（Escape 关闭 + 还焦；
 * 内容内自身可聚焦）。未来 AI 浮窗 / 阅读设置的基座。 */

import { type ReactNode, type RefObject, useEffect, useRef, useState } from 'react'
import { cx } from './cx'

export interface PopoverProps {
  trigger: (props: {
    open: boolean
    triggerProps: {
      'aria-expanded': boolean
      ref: RefObject<HTMLButtonElement | null>
      onClick: () => void
    }
  }) => ReactNode
  /** 面板内容；close() 供内容主动关闭并还焦 */
  children: (close: () => void) => ReactNode
  /** 面板最小宽度（px） */
  width?: number
}

export function Popover({ trigger, children, width = 260 }: PopoverProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (
        !panelRef.current?.contains(e.target as Node) &&
        !triggerRef.current?.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <span className="relative inline-flex">
      {trigger({
        open,
        triggerProps: {
          'aria-expanded': open,
          ref: triggerRef,
          onClick: () => setOpen((v) => !v),
        },
      })}
      {open && (
        <div
          ref={panelRef}
          className={cx(
            'absolute right-0 top-full z-[var(--lumi-z-popover)] mt-1.5 p-3',
            'rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)]',
            'shadow-[var(--lumi-shadow-popover)]',
          )}
          style={{ minWidth: `${width}px` }}
        >
          {children(() => {
            setOpen(false)
            triggerRef.current?.focus()
          })}
        </div>
      )}
    </span>
  )
}
