/** Dialog primitive — 0009 Gate 1。
 *
 * 模态对话框：role="dialog" + aria-modal、Escape 关闭、焦点 trap
 * （Tab 循环在对话框内）、关闭时还焦 trigger（AC7 / V5）。渲染在
 * document.body 之外的 fixed 遮罩层；深色遮罩 + dialog 阴影 token。 */

import { type ReactNode, useEffect, useId, useRef } from 'react'
import { cx } from './cx'

export interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  /** 底部操作区（按钮等）；由调用方组装 */
  footer?: ReactNode
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

export function Dialog({ open, onClose, title, children, footer }: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  // 关闭时还焦：记录打开前焦点（trigger 在 DOM 别处，不在本组件内）
  const lastActiveRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return
    lastActiveRef.current = document.activeElement as HTMLElement
    const panel = panelRef.current
    // 初始焦点：第一个可聚焦元素（没有则面板自身）
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? panel)?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      // 焦点 trap：Tab 在对话框内循环
      const nodes = [
        ...(panel?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []),
      ].filter((n) => n.offsetParent !== null)
      if (nodes.length === 0) return
      const firstNode = nodes[0]
      const lastNode = nodes[nodes.length - 1]
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
      lastActiveRef.current?.focus()
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[var(--lumi-z-dialog)] flex items-center justify-center p-4"
      onPointerDown={(e) => {
        // 遮罩点击关闭（面板内部点击不冒泡到这里）
        if (e.target === e.currentTarget) onClose()
      }}
    >
      {/* 遮罩 */}
      <div
        className="absolute inset-0 bg-[var(--lumi-text-primary)]/30"
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cx(
          'relative w-full max-w-md p-5',
          'rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)]',
          'shadow-[var(--lumi-shadow-dialog)]',
        )}
      >
        <h2
          id={titleId}
          className="mb-3 text-base font-semibold text-[var(--lumi-text-primary)]"
        >
          {title}
        </h2>
        <div className="text-sm text-[var(--lumi-text-primary)]">{children}</div>
        {footer && (
          <div className="mt-5 flex justify-end gap-2">{footer}</div>
        )}
      </div>
    </div>
  )
}
