/** Slider primitive — 连续 range 控件（0017 Reader Power UX）。
 *
 * - 原生 <input type="range">：键盘方向键/Home/End/翻页键免费获得；
 * - label + <output> 关联：值变化自动播报（无障碍）；
 * - 可选 A− / A+ 步进按钮（44px touch target，字号式快捷微调）；
 * - 视觉：填充式轨道（accent 渐变 + 百分比），thumb token 化；
 * - 每步 onChange：拖动即生效（WYSIWYG，不等待保存）。 */

import { useId } from 'react'
import { cx } from './cx'

export interface SliderProps {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
  /** 当前值显示格式化（如 "17px" / "1.85" / "0.85em"）。 */
  formatValue?: (value: number) => string
  /** A− / A+ 步进按钮（字样式微调；不传则不渲染）。 */
  steppers?: boolean
  /** 可选说明文案（label 下方小字）。 */
  description?: string
  disabled?: boolean
  className?: string
}

export function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  formatValue,
  steppers = false,
  description,
  disabled = false,
  className,
}: SliderProps) {
  const inputId = useId()
  const display = formatValue !== undefined ? formatValue(value) : String(value)
  const percent = max > min ? ((value - min) / (max - min)) * 100 : 0
  const displayId = `${inputId}-value`

  const stepBy = (direction: 1 | -1) => {
    const next = Math.round((value + direction * step) / step) * step
    onChange(Number(Math.min(max, Math.max(min, next)).toFixed(3)))
  }

  return (
    <div className={cx('flex flex-col gap-1.5', className)}>
      <div className="flex items-baseline justify-between gap-3">
        <label
          htmlFor={inputId}
          className="text-sm text-[var(--lumi-text-primary)]"
        >
          {label}
        </label>
        <output
          htmlFor={inputId}
          id={displayId}
          aria-live="polite"
          className="shrink-0 font-mono text-xs tabular-nums text-[var(--lumi-text-secondary)]"
        >
          {display}
        </output>
      </div>
      <div className="flex min-h-11 items-center gap-2">
        {steppers && (
          <button
            type="button"
            aria-label={`${label}减小`}
            disabled={disabled || value <= min}
            onClick={() => stepBy(-1)}
            className={cx(
              'flex size-9 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]',
              'text-sm font-medium text-[var(--lumi-text-secondary)]',
              'transition-colors duration-[var(--lumi-motion-fast)]',
              'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              'disabled:cursor-not-allowed disabled:opacity-40',
            )}
          >
            A−
          </button>
        )}
        <input
          id={inputId}
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          aria-valuetext={display}
          onChange={(e) => onChange(Number(e.target.value))}
          className="lumi-slider"
          style={{
            background: `linear-gradient(to right, var(--lumi-accent) ${percent}%, var(--lumi-surface-pressed) ${percent}%)`,
          }}
        />
        {steppers && (
          <button
            type="button"
            aria-label={`${label}增大`}
            disabled={disabled || value >= max}
            onClick={() => stepBy(1)}
            className={cx(
              'flex size-9 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]',
              'text-base font-medium text-[var(--lumi-text-secondary)]',
              'transition-colors duration-[var(--lumi-motion-fast)]',
              'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              'disabled:cursor-not-allowed disabled:opacity-40',
            )}
          >
            A+
          </button>
        )}
      </div>
      {description !== undefined && (
        <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          {description}
        </p>
      )}
    </div>
  )
}
