/** EmptyState primitive — 0009 Gate 1。
 *
 * 空状态：图标 + 标题 + 说明 + 可选操作。用于列表空 / 无结果场景，
 * 替代各组件自定义的空态文案块。 */

import type { ReactNode } from 'react'
import { cx } from './cx'

export interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: string
  /** 可选操作（如"重试"按钮） */
  action?: ReactNode
  className?: string
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cx(
        'flex flex-col items-center justify-center gap-2 px-6 py-10 text-center',
        className,
      )}
    >
      {icon && (
        <div
          aria-hidden="true"
          className="text-[var(--lumi-text-tertiary)] [&_svg]:size-10"
        >
          {icon}
        </div>
      )}
      <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
        {title}
      </p>
      {description && (
        <p className="max-w-60 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
