/** RadioGroup primitive — Base UI 行为底座（0021 base-ui 迁移新增）。
 *
 * 单选组：替代业务组件手写的 role="radiogroup"/role="radio" 按钮。
 * Base UI 提供 radiogroup/radio 语义、aria-checked、↑↓/←→ 键盘移动、
 * roving tabindex。视觉由调用方定制（色板 / 列表行等），激活态用
 * data-checked 变体表达；children 可接收 (checked) 渲染函数。 */

import { type CSSProperties, type ReactNode } from 'react'
import { RadioGroup as BaseRadioGroup } from '@base-ui/react/radio-group'
import { Radio as BaseRadio } from '@base-ui/react/radio'
import { cx } from './cx'

export interface RadioGroupProps<T extends string> {
  /** 可访问名称（radiogroup 的 aria-label） */
  'aria-label': string
  value: T
  onValueChange: (value: T) => void
  children: ReactNode
  className?: string
}

export function RadioGroup<T extends string>({ 'aria-label': ariaLabel, value, onValueChange, children, className }: RadioGroupProps<T>) {
  return (
    <BaseRadioGroup
      value={value}
      onValueChange={onValueChange}
      aria-label={ariaLabel}
      className={className}
    >
      {children}
    </BaseRadioGroup>
  )
}

export interface RadioOptionProps<T extends string> {
  value: T
  /** 静态内容，或按选中态渲染 */
  children?: ReactNode | ((checked: boolean) => ReactNode)
  className?: string
  style?: CSSProperties
  'aria-label'?: string
}

export function RadioOption<T extends string>({ value, children, className, style, 'aria-label': ariaLabel }: RadioOptionProps<T>) {
  return (
    <BaseRadio.Root
      value={value}
      aria-label={ariaLabel}
      className={cx(
        'cursor-pointer focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        className,
      )}
      style={style}
      render={(props, state) => (
        // Base UI 期望非 <button> 渲染目标（radio 语义/键盘全部由
        // Base UI 注入），原生 button 反而触发 nativeButton 契约警告。
        <span {...props}>
          {typeof children === 'function' ? children(state.checked) : children}
        </span>
      )}
    />
  )
}
