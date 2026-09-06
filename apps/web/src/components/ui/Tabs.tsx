/** Tabs primitive — Base UI 行为底座（0021 base-ui 迁移新增）。
 *
 * 替代业务组件自研的 role="tablist" + roving focus 键盘处理。Base UI
 * Tabs 提供：role=tablist/tab/tabpanel 语义、aria-selected/aria-controls、
 * ←/→/↑/↓/Home/End 键盘导航（roving tabindex）、方向性激活。视觉保持
 * Lumi：surface 分段容器 + 选中 elevated 底 + focus-ring token。
 * panels 按值全量传入，仅渲染激活面板（与受控 open 语义一致）。 */

import { type ReactNode } from 'react'
import { Tabs as BaseTabs } from '@base-ui/react/tabs'
import { cx } from './cx'

export interface TabsOption<T extends string> {
  value: T
  label: ReactNode
}

export interface TabsProps<T extends string> {
  /** 可访问名称（tablist 的 aria-label） */
  'aria-label': string
  value: T
  onValueChange: (value: T) => void
  options: ReadonlyArray<TabsOption<T>>
  /** 每个 tab 的面板内容；仅渲染 value 对应面板 */
  panels: { [K in T]: ReactNode }
  className?: string
}

export function Tabs<T extends string>({ 'aria-label': ariaLabel, value, onValueChange, options, panels, className }: TabsProps<T>) {
  return (
    <BaseTabs.Root
      value={value}
      onValueChange={(next) => onValueChange(next as T)}
      className={className}
    >
      <BaseTabs.List
        aria-label={ariaLabel}
        className="mb-4 flex gap-1 rounded-[var(--lumi-radius-lg)] bg-[var(--lumi-surface)] p-1"
      >
        {options.map((option) => (
          <BaseTabs.Tab
            key={option.value}
            value={option.value}
            className={cx(
              'min-h-11 flex-1 rounded-[var(--lumi-radius-md)] px-2 py-2 text-xs font-medium',
              'transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
              'data-selected:bg-[var(--lumi-surface-elevated)] data-selected:text-[var(--lumi-text-primary)] data-selected:shadow-[var(--lumi-shadow-sm)]',
            )}
          >
            {option.label}
          </BaseTabs.Tab>
        ))}
      </BaseTabs.List>
      <BaseTabs.Panel value={value} className="flex flex-col">
        {panels[value]}
      </BaseTabs.Panel>
    </BaseTabs.Root>
  )
}
