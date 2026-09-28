/** Select primitive — 0009 Gate 1。
 *
 * 原生 <select> 的语义封装（键盘/移动端行为免费获得），样式 token 化。
 * 值受控：value + onChange。占位用第一项 disabled option。 */

import type { SelectHTMLAttributes } from 'react'
import { cx } from './cx'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface SelectProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  options: SelectOption[]
}

export function Select({ options, className, ...rest }: SelectProps) {
  return (
    <select
      // FIX-293：焦点环由 [data-lumi-focus-ring]（index.css，unlayered）承载，
      // 消费侧 className 不可覆盖（与 Button/IconButton 同一合并规则）。
      data-lumi-focus-ring=""
      className={cx(
        'min-h-9 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 text-sm',
        'text-[var(--lumi-text-primary)]',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        'hover:border-[var(--lumi-text-tertiary)]',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...rest}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  )
}
