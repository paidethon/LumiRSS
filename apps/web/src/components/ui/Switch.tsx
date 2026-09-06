/** Switch primitive — Base UI 行为底座（原 0009 Gate 1 自研实现迁移）。
 *
 * 开关：Base UI Switch 提供 role="switch" + aria-checked、隐藏原生
 * input（表单可用、键盘 Space 切换、label 关联点击）、disabled 语义。
 * 纯受控（checked + onCheckedChange）。视觉保持 Lumi：token 轨道与
 * thumb、透明伪元素把可点区域撑到 ≥44×44 触摸目标（不改布局）。 */

import { Switch as BaseSwitch } from '@base-ui/react/switch'
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
  return (
    <label
      className={cx(
        'inline-flex items-center gap-2.5 text-sm text-[var(--lumi-text-primary)]',
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
      )}
    >
      <BaseSwitch.Root
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className={cx(
          'relative inline-flex h-6 w-11 shrink-0 items-center rounded-[var(--lumi-radius-full)]',
          'transition-colors duration-[var(--lumi-motion-fast)]',
          // 0020 Gate 3（触摸目标）：视觉轨道保持 24×44，但用透明伪元素
          // 把可点区域向上下各撑 10px → ≥44×44 的触达目标（不改布局/观感）。
          'after:absolute after:-inset-y-2.5 after:inset-x-0 after:content-[""]',
          'bg-[var(--lumi-surface-pressed)] data-checked:bg-[var(--lumi-accent)]',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        )}
      >
        <BaseSwitch.Thumb
          className={cx(
            'absolute size-4.5 rounded-full bg-white shadow-sm',
            'left-0.5 transition-transform duration-[var(--lumi-motion-fast)]',
            'data-checked:translate-x-5',
          )}
        />
      </BaseSwitch.Root>
      <span>{label}</span>
    </label>
  )
}
