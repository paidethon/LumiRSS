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
      className={cx(
        'min-h-9 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 text-sm',
        'text-[var(--lumi-text-primary)]',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        'hover:border-[var(--lumi-text-tertiary)]',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
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
