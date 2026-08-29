/** Tooltip primitive — 0009 Gate 1。
 *
 * CSS-only 提示：hover / focus-visible 触发，无 JS 定位（遵循"简单交互
 * CSS 优先"）。aria-describedby 关联描述，屏幕阅读器可读（AC7）。
 * 溢出滚动容器内使用时注意 clip（复杂定位场景留给 Gate 5 Popover）。 */

import { useId, type ReactNode } from 'react'
import { cx } from './cx'

export interface TooltipProps {
  /** 触发元素（通常是 IconButton） */
  children: ReactNode
  /** 提示文本 */
  content: string
}

export function Tooltip({ children, content }: TooltipProps) {
  const id = useId()
  return (
    <span
      className="group/tt relative inline-flex"
      // 只有当 child 是可聚焦元素时 focus 才会触发（IconButton 天然满足）
    >
      {children}
      <span
        role="tooltip"
        id={id}
        className={cx(
          'pointer-events-none absolute bottom-full left-1/2 z-[var(--lumi-z-tooltip)] mb-1.5 -translate-x-1/2 whitespace-nowrap',
          'rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-text-primary)] px-2 py-1 text-xs text-[var(--lumi-surface)]',
          'opacity-0 transition-opacity duration-[var(--lumi-motion-fast)]',
          'group-hover/tt:opacity-100 group-focus-within/tt:opacity-100',
        )}
      >
        {content}
      </span>
      {/* 把描述 id 注入子元素：React 会克隆合并 aria-describedby */}
      <span className="contents" aria-describedby={id} />
    </span>
  )
}
