/** Switch primitive — Base UI 行为底座（原 0009 Gate 1 自研实现迁移）。
 *
 * 开关：Base UI Switch 提供 role="switch" + aria-checked、隐藏原生
 * input（表单可用、键盘 Space 切换、label 关联点击）、disabled 语义。
 * 纯受控（checked + onCheckedChange）。视觉保持 Lumi：token 轨道与
 * thumb、透明伪元素把可点区域撑到 ≥44×44 触摸目标（不改布局）。
 *
 * 可见文字与无障碍名称分离（Gate：删除开关旁重复可见文案）：
 * - 本组件只渲染控件本体，绝不渲染可见文字；
 * - `label` 只作为无障碍名称（aria-label）；行内已有可见标题时用
 *   `labelledby` 关联标题元素 id（优先），并把 `id` 交给标题的
 *   htmlFor —— 点击标题即可切换；
 * - 需要独立可见名称的开关由调用方在旁边自行渲染文字。 */

import { Switch as BaseSwitch } from '@base-ui/react/switch'
import { cx } from './cx'

export interface SwitchProps {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  /** 无障碍名称（aria-label）；传入 labelledby 时仅作回退。 */
  label: string
  /** 行内已有可见标题：aria-labelledby 关联标题元素 id。 */
  labelledby?: string
  /** 控件 id；行内标题用 <label htmlFor> 指向它即可点击切换。 */
  id?: string
  disabled?: boolean
}

export function Switch({
  checked,
  onCheckedChange,
  label,
  labelledby,
  id,
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
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        aria-labelledby={labelledby}
        aria-label={labelledby ? undefined : label}
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
    </label>
  )
}
