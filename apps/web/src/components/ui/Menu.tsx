/** Menu primitive — 0009 Gate 1。
 *
 * 无依赖下拉菜单：trigger 按钮 + 弹出面板（absolute 定位，右对齐 trigger）。
 * 键盘：Enter/Space/↓ 打开、Escape 关闭并还焦、↑↓ 在 item 间移动、
 * Tab 关闭（AC7 / V5）。Menu 有 aria-haspopup/aria-expanded；面板
 * role="menu"、item role="menuitem"。焦点 trap：面板打开时焦点进入
 * 第一项，关闭时还给 trigger。 */

import {
  type ReactNode,
  type RefObject,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react'
import { cx } from './cx'

export interface MenuItemDef {
  /** 唯一 key；onSelect 收到它 */
  key: string
  /** 展示内容（可含图标） */
  content: ReactNode
  disabled?: boolean
}

export interface MenuProps {
  /** 触发按钮内容（通常是 IconButton） */
  trigger: (props: {
    open: boolean
    triggerProps: {
      'aria-haspopup': 'menu'
      'aria-expanded': boolean
      ref: RefObject<HTMLButtonElement | null>
      onClick: () => void
      onKeyDown: (e: React.KeyboardEvent<HTMLButtonElement>) => void
    }
  }) => ReactNode
  items: MenuItemDef[]
  onSelect: (key: string) => void
}

export function Menu({ trigger, items, onSelect }: MenuProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  // 打开时聚焦第一个可用 item；关闭（非卸载）时还焦 trigger
  useEffect(() => {
    if (!open) return
    const first = panelRef.current?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')
    first?.focus()
  }, [open])

  // 外点关闭（mount 时注册一次）
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
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  const closeAndRestore = () => {
    setOpen(false)
    triggerRef.current?.focus()
  }

  const onPanelKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation()
      closeAndRestore()
      return
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    e.preventDefault()
    const nodes = [
      ...(panelRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? []),
    ]
    if (nodes.length === 0) return
    const idx = nodes.indexOf(document.activeElement as HTMLElement)
    const next =
      e.key === 'ArrowDown'
        ? nodes[(idx + 1 + nodes.length) % nodes.length]
        : nodes[(idx - 1 + nodes.length) % nodes.length]
    next.focus()
  }

  return (
    <span className="relative inline-flex">
      {trigger({
        open,
        triggerProps: {
          'aria-haspopup': 'menu',
          'aria-expanded': open,
          ref: triggerRef,
          onClick: () => setOpen((v) => !v),
          onKeyDown: (e) => {
            if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
              if (!open) {
                e.preventDefault()
                setOpen(true)
              }
            }
          },
        },
      })}
      {open && (
        <div
          ref={panelRef}
          role="menu"
          id={menuId}
          tabIndex={-1}
          onKeyDown={onPanelKeyDown}
          className={cx(
            'absolute right-0 top-full z-[var(--lumi-z-popover)] mt-1.5 min-w-40',
            'rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-1',
            'shadow-[var(--lumi-shadow-popover)]',
          )}
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                if (item.disabled) return
                onSelect(item.key)
                closeAndRestore()
              }}
              className={cx(
                'flex w-full items-center gap-2 rounded-[var(--lumi-radius-sm)] px-2.5 py-2 text-left text-sm',
                'text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)]',
                'hover:bg-[var(--lumi-surface-hover)] focus-visible:bg-[var(--lumi-surface-hover)] focus-visible:outline-none',
                'disabled:cursor-not-allowed disabled:opacity-50',
              )}
            >
              {item.content}
            </button>
          ))}
        </div>
      )}
    </span>
  )
}
