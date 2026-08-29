/** Skeleton primitive — 0009 Gate 1。
 *
 * 加载占位：低透明度脉冲块（animate-pulse 是 Tailwind 内置，无需新 CSS）。
 * 颜色用 surface-selected token（自动适配双主题），不再硬编码 bg-gray-100。 */

import { cx } from './cx'

export interface SkeletonProps {
  className?: string
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cx(
        'animate-pulse rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-surface-selected)]',
        className,
      )}
    />
  )
}
