/** SettingsRow primitive — R3 共享契约 §2（Wave0 foundation）。
 *
 * 一行式设置行：label（2–8 汉字）+ 可选 help（一句话）+ 右侧控件插槽
 * + 可选可折叠 details + 可选 dangerous 语义。行布局对齐既有
 * SettingItem（components/settings/SettingItem.tsx）的 flex
 * justify-between 习惯，但不依赖其 SettingItemDef 判别联合——可独立
 * 使用，作为新设置界面的渐进采用行组件。
 *
 * a11y：controlId 传入时渲染 <label htmlFor>（文本控件自动关联）；
 * 开关类控件由消费方用 Switch 的 labelledby 关联（同 SettingItem 模式，
 * 此处不强制）。details 折叠是原生 button + aria-expanded/controls，
 * 无高度动画（尊重 prefers-reduced-motion 的最简实现）。 */

import { ChevronDown } from 'lucide-react'
import { type ReactNode, useId, useState } from 'react'
import { cx } from './cx'

export interface SettingsRowProps {
  /** 行标签（2–8 汉字，R14 文案规范） */
  label: string
  /** 帮助文案（一句话，18–28 汉字） */
  help?: string
  /** 右侧控件（Switch / Select / Button 等单控件） */
  children: ReactNode
  /** 可折叠详情（点击「详情」展开的补充说明/高级内容） */
  details?: ReactNode
  /** 破坏性语义：label 与 help 用 danger 色（如「清除数据」行） */
  dangerous?: boolean
  /** 控件 id：传入时 label 以 htmlFor 关联控件 */
  controlId?: string
  className?: string
}

export function SettingsRow({
  label,
  help,
  children,
  details,
  dangerous = false,
  controlId,
  className,
}: SettingsRowProps) {
  const detailId = useId()
  const [detailOpen, setDetailOpen] = useState(false)

  const labelElement = controlId !== undefined ? (
    <label
      htmlFor={controlId}
      className={cx(
        'text-sm font-medium leading-tight',
        dangerous ? 'text-[var(--lumi-danger)]' : 'text-[var(--lumi-text-primary)]',
      )}
    >
      {label}
    </label>
  ) : (
    <div
      className={cx(
        'text-sm font-medium leading-tight',
        dangerous ? 'text-[var(--lumi-danger)]' : 'text-[var(--lumi-text-primary)]',
      )}
    >
      {label}
    </div>
  )

  return (
    <div className={cx('py-1.5', className)}>
      <div className="flex min-h-11 items-center justify-between gap-4 py-1">
        <div className="min-w-0">
          {labelElement}
          {help !== undefined && (
            <p
              className={cx(
                'mt-0.5 text-xs leading-relaxed',
                dangerous
                  ? 'text-[var(--lumi-danger)] opacity-80'
                  : 'text-[var(--lumi-text-secondary)]',
              )}
            >
              {help}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2.5">{children}</div>
      </div>
      {details !== undefined && (
        <div>
          <button
            type="button"
            aria-expanded={detailOpen}
            aria-controls={detailId}
            onClick={() => setDetailOpen((v) => !v)}
            className={cx(
              'flex min-h-8 items-center gap-1 rounded-[var(--lumi-radius-md)] text-xs',
              'text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)]',
              'hover:text-[var(--lumi-text-primary)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            )}
          >
            <ChevronDown
              aria-hidden="true"
              className={cx(
                'size-3.5 transition-transform duration-[var(--lumi-motion-fast)]',
                detailOpen && 'rotate-180',
              )}
            />
            {detailOpen ? '收起详情' : '详情'}
          </button>
          {detailOpen && (
            <div id={detailId} className="pb-2 pt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              {details}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
