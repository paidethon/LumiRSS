/** ActionSheet primitive — R3 共享契约 §2（Wave0 foundation）。
 *
 * 移动底部面板：基于 ui/Sheet.tsx 定稿（side="bottom"）。行为（role=
 * dialog + aria-modal、Escape / 遮罩 / ✕ 关闭、焦点 trap 与还原、body
 * 滚动锁、下滑手势关闭、返回链登记）全部由 Sheet → Base UI Drawer
 * 提供；ActionSheet 只补「可见标题行 + 关闭钮 + 正文滚动 + footer +
 * safe-area-inset-bottom」，进入动效沿用 Sheet 的 motion-slow（200ms，
 * 契约 180–220ms 区间中值）。
 *
 * 命名暴露 BaseDrawer.Title 是 sr-only 的事实：Sheet 以 label 提供
 * accessible name，这里的可见标题是面板内非 heading 文本（不参与
 * aria-labelledby，面板内只有一个 heading），两者文案一致。 */

import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { cx } from './cx'
import { IconButton } from './IconButton'
import { Sheet } from './Sheet'

export interface ActionSheetProps {
  open: boolean
  onClose: () => void
  /** 面板标题（同时是 accessible name） */
  title: string
  children: ReactNode
  /** 底部操作区（按钮等），恒定可见不随正文滚动 */
  footer?: ReactNode
  /** 面板附加类（调用方定制高度等） */
  panelClassName?: string
  /** 面板 id（外部 aria-controls 联动用） */
  id?: string
}

export function ActionSheet({
  open,
  onClose,
  title,
  children,
  footer,
  panelClassName,
  id,
}: ActionSheetProps) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      label={title}
      side="bottom"
      id={id}
      panelClassName={cx('flex flex-col', panelClassName)}
    >
      <div
        className="flex shrink-0 items-center justify-between gap-2 pr-1.5 pl-4"
        style={{ paddingTop: 'max(0.75rem, var(--safe-top))' }}
      >
        {/* 非 heading：accessible name 由 Sheet 的 sr-only Title 承载，
            面板内不重复 heading（MobileNavigationDrawer span 标题同款） */}
        <span className="min-w-0 truncate text-sm font-semibold text-[var(--lumi-text-primary)]">
          {title}
        </span>
        <IconButton icon={<X aria-hidden="true" className="size-4" />} label="关闭" onClick={onClose} touch />
      </div>
      <div
        className="min-h-0 flex-1 overflow-y-auto px-4 pt-1 text-sm text-[var(--lumi-text-primary)]"
        style={{ paddingBottom: footer === undefined ? 'max(0.75rem, var(--safe-bottom))' : undefined }}
      >
        {children}
      </div>
      {footer !== undefined && (
        <div
          className="shrink-0 border-t border-[var(--lumi-separator)] px-4 pt-3"
          style={{ paddingBottom: 'max(0.75rem, var(--safe-bottom))' }}
        >
          {footer}
        </div>
      )}
    </Sheet>
  )
}
