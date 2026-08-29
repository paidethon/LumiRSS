/** Switch primitive — 0009 Gate 1。
 *
 * 开关：role="switch" + aria-checked、键盘 Space 切换、label 关联。
 * 纯受控（checked + onCheckedChange）。 */

import { useId } from 'react'
import { cx } from './cx'

export interface SwitchProps {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  /** 开关旁的可见标签 */
  label: string
  disabled?: boolean
}

export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled = false,
}: SwitchProps) {
  const labelId = useId()
  return (
    <label
      className={cx(
        'inline-flex items-center gap-2.5 text-sm text-[var(--lumi-text-primary)]',
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
      )}
    >
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        disabled={disabled}
        onClick={() => onCheckedChange(!checked)}
        className={cx(
          'relative inline-flex h-6 w-11 shrink-0 items-center rounded-[var(--lumi-radius-full)]',
          'transition-colors duration-[var(--lumi-motion-fast)]',
          checked
            ? 'bg-[var(--lumi-accent)]'
            : 'bg-[var(--lumi-surface-pressed)]',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        )}
      >
        <span
          className={cx(
            'absolute size-4.5 rounded-full bg-white shadow-sm',
            'left-0.5 transition-transform duration-[var(--lumi-motion-fast)]',
            checked && 'translate-x-5',
          )}
        />
      </button>
      <span id={labelId}>{label}</span>
    </label>
  )
}
