/** Toolbar primitive — R3 共享契约 §2（Wave0 foundation）。
 *
 * 横向工具行容器：左侧 segmented 子件插槽（常驻内联）+ 右侧按钮位。
 * 窄屏（useIsMobile，非 desktop 档）时超出 maxInlineOnNarrow 的动作收进
 * 「更多」菜单（复用 Menu primitive → Base UI，键盘/Escape/外点行为
 * 全部继承），桌面档全部内联。按钮位按数组顺序即优先级——排前的保留
 * 内联。
 *
 * 溢出按数量而非像素测量：jsdom 无几何（项目既有测试约定），像素测量
 * 只能靠 ResizeObserver 抖动重排；数量上限让消费方以「动作优先级」
 * 表达同一意图，且行为可确定性测试。
 *
 * 触控目标：窄屏动作按钮 min-h-11（44px）；icon-only 动作用 IconButton
 * + touch（命中区外扩 44×44，视觉尺寸不变）。 */

import { MoreHorizontal } from 'lucide-react'
import type { ReactNode } from 'react'
import { useIsMobile } from '../../lib/use-is-mobile'
import { Button } from './Button'
import { cx } from './cx'
import { IconButton } from './IconButton'
import { Menu } from './Menu'

export interface ToolbarAction {
  /** 稳定 id（菜单 onSelect 回传） */
  id: string
  /** 文案：内联按钮的标签 / icon-only 时的可访问名称 / 菜单项文案 */
  label: string
  icon?: ReactNode
  onSelect: () => void
  /** 只渲染图标（IconButton；label 作 aria-label） */
  iconOnly?: boolean
  /** 破坏性动作：内联 danger 变体 / 菜单项 danger 色 */
  danger?: boolean
  disabled?: boolean
}

export interface ToolbarProps {
  /** segmented 子件插槽（Tabs 等分段控件），始终内联不参与溢出 */
  segmented?: ReactNode
  /** 按钮位（顺序 = 优先级：窄屏时排前的保留内联） */
  actions?: ToolbarAction[]
  /** 窄屏内联保留的动作数，其余收进「更多」（默认 1） */
  maxInlineOnNarrow?: number
  /** 「更多」按钮文案（默认 更多） */
  moreLabel?: string
  className?: string
  /** 工具行可访问名称 */
  'aria-label'?: string
}

export function Toolbar({
  segmented,
  actions = [],
  maxInlineOnNarrow = 1,
  moreLabel = '更多',
  className,
  'aria-label': ariaLabel,
}: ToolbarProps) {
  const isMobile = useIsMobile()

  const inlineCount = isMobile ? Math.max(0, maxInlineOnNarrow) : actions.length
  const inline = actions.slice(0, inlineCount)
  const overflow = actions.slice(inlineCount)

  const renderInline = (action: ToolbarAction) => {
    if (action.iconOnly) {
      return (
        <IconButton
          key={action.id}
          icon={action.icon}
          label={action.label}
          disabled={action.disabled}
          touch={isMobile}
          onClick={action.onSelect}
          className={action.danger ? 'text-[var(--lumi-danger)]' : undefined}
        />
      )
    }
    return (
      <Button
        key={action.id}
        variant={action.danger ? 'danger' : 'secondary'}
        size="sm"
        disabled={action.disabled}
        onClick={action.onSelect}
        className={cx(isMobile && 'min-h-11')}
      >
        {action.icon}
        {action.label}
      </Button>
    )
  }

  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cx('flex min-w-0 items-center gap-1.5', className)}
    >
      {segmented !== undefined && <div className="flex min-w-0 shrink items-center">{segmented}</div>}
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {inline.map(renderInline)}
        {overflow.length > 0 && (
          <Menu
            items={overflow.map((action) => ({
              key: action.id,
              content: (
                <span
                  className={cx(
                    'flex items-center gap-2',
                    action.danger && 'text-[var(--lumi-danger)]',
                  )}
                >
                  {action.icon}
                  {action.label}
                </span>
              ),
              disabled: action.disabled,
            }))}
            onSelect={(key) => {
              const action = overflow.find((a) => a.id === key)
              action?.onSelect()
            }}
            trigger={({ open, triggerProps }) => (
              <Button
                variant="ghost"
                size="sm"
                aria-expanded={open}
                className={cx(isMobile && 'min-h-11')}
                {...triggerProps}
              >
                <MoreHorizontal aria-hidden="true" className="size-4 shrink-0" />
                {moreLabel}
              </Button>
            )}
          />
        )}
      </div>
    </div>
  )
}
