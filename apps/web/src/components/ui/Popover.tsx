/** Popover primitive — Base UI 行为底座（原 0009 Gate 1 自研实现迁移）。
 *
 * 通用浮层容器（trigger + 定位面板，内容自由如表单/设置面板）。行为由
 * Base UI Popover 提供：外点关闭、Escape 关闭并还焦、portal + Floating
 * UI 定位与视口碰撞翻转（取代旧实现 absolute right-0/top-full，修复
 * 屏幕边缘溢出）；与 Menu 的区别：键盘要求宽松，内容可含可聚焦控件。
 * 视觉保持 Lumi 原样：--lumi-* token 面板、右对齐、6px 间距、minWidth。 */

import { type ReactNode, useState } from 'react'
import type { ComponentProps } from 'react'
import { Popover as BasePopover } from '@base-ui/react/popover'
import { cx } from './cx'

export interface PopoverProps {
  trigger: (props: {
    open: boolean
    triggerProps: {
      'aria-expanded': boolean
      ref: ComponentProps<'button'>['ref']
      onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void
    }
  }) => ReactNode
  /** 面板内容；close() 供内容主动关闭并还焦 */
  children: (close: () => void) => ReactNode
  /** 面板最小宽度（px） */
  width?: number
}

export function Popover({ trigger, children, width = 260 }: PopoverProps) {
  const [open, setOpen] = useState(false)

  return (
    <span className="relative inline-flex">
      <BasePopover.Root open={open} onOpenChange={setOpen}>
        <BasePopover.Trigger
          render={(triggerProps: ComponentProps<'button'>) => (
            <>
              {trigger({
                open,
                triggerProps: {
                  ref: triggerProps.ref,
                  onClick: triggerProps.onClick,
                  'aria-expanded':
                    triggerProps['aria-expanded'] === true ||
                    triggerProps['aria-expanded'] === 'true',
                },
              })}
            </>
          )}
        />
        <BasePopover.Portal>
          <BasePopover.Positioner
            side="bottom"
            align="end"
            sideOffset={6}
            collisionPadding={8}
            className="z-[var(--lumi-z-popover)]"
          >
            <BasePopover.Popup
              className={cx(
                'p-3',
                'rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)]',
                'shadow-[var(--lumi-shadow-popover)]',
              )}
              style={{ minWidth: `${width}px` }}
            >
              {children(() => setOpen(false))}
            </BasePopover.Popup>
          </BasePopover.Positioner>
        </BasePopover.Portal>
      </BasePopover.Root>
    </span>
  )
}
