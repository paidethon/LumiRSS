/** ActionMenu primitive — R3 共享契约 §2（Wave0 foundation）。
 *
 * 动作菜单：与 ui/Menu.tsx 同一套 Base UI Menu 底座（外点关闭、Escape
 * 关闭还焦、↑↓/Home/End/typeahead 键盘导航、portal + 碰撞定位全部由
 * Base UI 提供），在其上扩展 ActionMenu 语义条目：
 *
 *   { type: 'section', label }  → 分组小标题（Base UI Group/GroupLabel，
 *                                 键盘导航自动跳过，仅 menuitem 可聚焦）
 *   { type: 'item', label, icon?, onSelect, danger?, disabled? }
 *   { type: 'sep' }             → 分组分隔线
 *
 * 行高 min-h-11（44px 触控目标下限）；danger 项用 danger token 色，
 * hover/键盘高亮仍走统一 surface-hover。与 Menu 的差异只有「条目模型 +
 * 分组 + 44px 行高」——纯菜单（扁平 items + onSelect(key)）继续用 Menu。 */

import { type ReactNode, useState } from 'react'
import { Menu as BaseMenu } from '@base-ui/react/menu'
import type { HTMLProps } from '@base-ui/react'
import { cx } from './cx'

export type ActionMenuEntry =
  | { type: 'section'; label: string }
  | {
      type: 'item'
      label: string
      icon?: ReactNode
      onSelect: () => void
      danger?: boolean
      disabled?: boolean
    }
  | { type: 'sep' }

/** Base UI render prop 传给触发元素的 props（需整体展开到按钮上）。 */
export type ActionMenuTriggerProps = HTMLProps<HTMLButtonElement>

export interface ActionMenuProps {
  /** 触发按钮内容；triggerProps 需整体展开到按钮上 */
  trigger: (props: {
    open: boolean
    triggerProps: ActionMenuTriggerProps
  }) => ReactNode
  entries: ActionMenuEntry[]
}

type ActionMenuItem = Extract<ActionMenuEntry, { type: 'item' }>

function ActionMenuItemRow({ item, index }: { item: ActionMenuItem; index: number }) {
  return (
    <BaseMenu.Item
      key={`${index}-${item.label}`}
      disabled={item.disabled}
      onClick={item.onSelect}
      className={cx(
        'flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-[var(--lumi-radius-sm)] px-2.5 py-1.5 text-left text-sm',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        item.danger ? 'text-[var(--lumi-danger)]' : 'text-[var(--lumi-text-primary)]',
        'data-highlighted:bg-[var(--lumi-surface-hover)] data-highlighted:outline-none',
        'data-disabled:cursor-not-allowed data-disabled:opacity-50',
      )}
    >
      {item.icon}
      {item.label}
    </BaseMenu.Item>
  )
}

/** 把条目序列折叠成渲染块：section 起新组（带小标题），无小标题条目
 * 归入裸 Group（语义分组，无标题），sep 断组并渲染分隔线。 */
function buildBlocks(entries: ActionMenuEntry[]): ReactNode[] {
  const blocks: ReactNode[] = []
  let sectionLabel: string | undefined
  let items: ActionMenuItem[] = []
  let seq = 0

  const flush = () => {
    // 空段（连续 section / 尾随 section）直接丢弃，不留悬空小标题
    if (items.length === 0) return
    blocks.push(
      <BaseMenu.Group key={`group-${seq}`}>
        {sectionLabel !== undefined && (
          <BaseMenu.GroupLabel className="px-2.5 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--lumi-text-tertiary)] first:pt-1">
            {sectionLabel}
          </BaseMenu.GroupLabel>
        )}
        {items.map((item, i) => (
          <ActionMenuItemRow key={`${i}-${item.label}`} item={item} index={i} />
        ))}
      </BaseMenu.Group>,
    )
    seq += 1
    sectionLabel = undefined
    items = []
  }

  for (const entry of entries) {
    if (entry.type === 'section') {
      flush()
      sectionLabel = entry.label
    } else if (entry.type === 'item') {
      items.push(entry)
    } else {
      flush()
      blocks.push(
        <div
          key={`sep-${seq}`}
          role="separator"
          className="mx-2 my-1 border-t border-[var(--lumi-separator)]"
        />,
      )
      seq += 1
    }
  }
  flush()
  return blocks
}

export function ActionMenu({ trigger, entries }: ActionMenuProps) {
  const [open, setOpen] = useState(false)

  return (
    <span className="relative inline-flex">
      <BaseMenu.Root open={open} onOpenChange={setOpen} loopFocus>
        <BaseMenu.Trigger
          render={(triggerProps: ActionMenuTriggerProps) => (
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
                'min-w-44 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-1',
                'shadow-[var(--lumi-shadow-popover)]',
              )}
            >
              {buildBlocks(entries)}
            </BaseMenu.Popup>
          </BaseMenu.Positioner>
        </BaseMenu.Portal>
      </BaseMenu.Root>
    </span>
  )
}
