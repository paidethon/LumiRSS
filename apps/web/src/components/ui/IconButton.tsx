/** IconButton primitive — 0009 Gate 1；0021 base-ui 迁移扩展 size。
 *
 * 图标按钮：lucide 图标、label 必填（aria-label / visually-hidden 文本
 * 二选一，AC7：icon-only 控件必须有 accessible name）。size 三档：
 * sm 28px（紧凑行内）、md 32px 默认（工具栏，Folo 实测规格）、
 * lg 44px（移动端全屏壳的 ✕/返回）。 */

import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cx } from './cx'

export interface IconButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** 图标（通常是 lucide-react 图标元素） */
  icon: ReactNode
  /** accessible name：传 aria-label，或在 children 放 visually-hidden 文本 */
  label?: string
  /** 视觉尺寸：sm 28 / md 32（默认）/ lg 44 */
  size?: 'sm' | 'md' | 'lg'
  /** 手机上需要 ≥44px 触摸目标时打开（铺满 44px 点击区，视觉仍 32px） */
  touch?: boolean
}

const sizeClasses = {
  sm: 'size-7',
  md: 'size-8',
  lg: 'size-11',
} as const

export function IconButton({
  icon,
  label,
  size = 'md',
  touch = false,
  type = 'button',
  className,
  children,
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      className={cx(
        'inline-flex items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-secondary)]',
        sizeClasses[size],
        'transition-colors duration-[var(--lumi-motion-fast)]',
        'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
        'active:bg-[var(--lumi-surface-pressed)]',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        'disabled:cursor-not-allowed disabled:opacity-50 disabled:pointer-events-none',
        touch && 'min-h-11 min-w-11',
        className,
      )}
      {...rest}
    >
      {icon}
      {children /* visually-hidden 文本兜底 */}
    </button>
  )
}
