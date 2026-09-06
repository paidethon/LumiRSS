/** Menu primitive — Base UI 行为底座（原 0009 Gate 1 自研实现迁移）。
 *
 * 下拉菜单：trigger + 弹出面板。行为全部由 Base UI Menu 提供：外点关闭、
 * Escape 关闭并还焦、↑↓/Home/End/Enter/Space/typeahead 键盘导航、
 * Tab 关闭、portal + Floating UI 定位与视口碰撞翻转（取代旧实现
 * absolute right-0/top-full）、aria-haspopup/aria-expanded/role=menu/
 * menuitem 语义、item 高亮（data-highlighted，hover 与键盘统一）。
 * Lumi 只负责视觉：--lumi-* token 面板与 item 样式。 */

import { type ReactNode, useState } from 'react'
import { Menu as BaseMenu } from '@base-ui/react/menu'
// 纯类型导入（编译期擦除）：避免从根 barrel 拉入全部 Base UI 组件
import type { HTMLProps } from '@base-ui/react'
import { cx } from './cx'

export interface MenuItemDef {
  /** 唯一 key；onSelect 收到它 */
  key: string
  /** 展示内容（可含图标） */
  content: ReactNode
  disabled?: boolean
}

/** Base UI render prop 传给触发元素的 props（需整体展开到按钮上）。 */
export type MenuTriggerProps = HTMLProps<HTMLButtonElement>

export interface MenuProps {
  /** 触发按钮内容（通常是 IconButton）；triggerProps 需整体展开到按钮上 */
  trigger: (props: {
    open: boolean
    triggerProps: MenuTriggerProps
  }) => ReactNode
  items: MenuItemDef[]
  onSelect: (key: string) => void
}

export function Menu({ trigger, items, onSelect }: MenuProps) {
  const [open, setOpen] = useState(false)

  return (
    <span className="relative inline-flex">
      <BaseMenu.Root open={open} onOpenChange={setOpen} loopFocus>
        <BaseMenu.Trigger
          render={(triggerProps: MenuTriggerProps) => (
            <>
              {trigger({
                open,
                triggerProps: {
                  ...triggerProps,
                  'aria-haspopup': triggerProps['aria-haspopup'] ?? 'menu',
                },
              })}
            </>
          )}
        />
        <BaseMenu.Portal>
          <BaseMenu.Positioner
            side="bottom"
            align="end"
            sideOffset={6}
            collisionPadding={8}
            className="z-[var(--lumi-z-popover)]"
          >
            <BaseMenu.Popup
              className={cx(
                'min-w-40 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-1',
                'shadow-[var(--lumi-shadow-popover)]',
              )}
            >
              {items.map((item) => (
                <BaseMenu.Item
                  key={item.key}
                  disabled={item.disabled}
                  onClick={() => onSelect(item.key)}
                  className={cx(
                    'flex w-full cursor-pointer items-center gap-2 rounded-[var(--lumi-radius-sm)] px-2.5 py-2 text-left text-sm',
                    'text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)]',
                    'data-highlighted:bg-[var(--lumi-surface-hover)] data-highlighted:outline-none',
                    'data-disabled:cursor-not-allowed data-disabled:opacity-50',
                  )}
                >
                  {item.content}
                </BaseMenu.Item>
              ))}
            </BaseMenu.Popup>
          </BaseMenu.Positioner>
        </BaseMenu.Portal>
      </BaseMenu.Root>
    </span>
  )
}
