/** DetailDrawer primitive — R3 共享契约 §2/§4（Wave0 foundation）。
 *
 * 唯一详情抽屉：桌面（≥1024）右侧 400–440px 抽屉（Sheet side="right"，
 * 宽度走 --lumi-width-detail-drawer token = 416px）；非 desktop 档
 * （<1024，compact/tablet 触摸优先，同 use-is-mobile P03 语义）自动
 * 渲染为 ActionSheet 全宽底部面板。焦点 trap、Escape、遮罩关闭、滚动
 * 锁、返回链登记两条路径都由 Sheet → Base UI Drawer 提供。
 *
 * 契约：抽屉内禁止再嵌套抽屉/对话框浮层跳出不同尺寸弹窗（浮层规则
 * §2——内部二级视图由消费方在面板内自行切换）。右侧路径的宽度覆盖用
 * important 修饰符：Sheet 对 side=right 自带 max-w-md，panelClassName
 * 是拼接而非替换（cx 无 merge），token 宽度必须稳定胜出。 */

import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { useIsMobile } from '../../lib/use-is-mobile'
import { ActionSheet } from './ActionSheet'
import { cx } from './cx'
import { IconButton } from './IconButton'
import { Sheet } from './Sheet'

export interface DetailDrawerProps {
  open: boolean
  onClose: () => void
  /** 面板标题（同时是 accessible name） */
  title: string
  children: ReactNode
  /** 底部操作区（按钮等），恒定可见不随正文滚动 */
  footer?: ReactNode
  /** 面板附加类（两种形态共用） */
  panelClassName?: string
  /** 面板 id（外部 aria-controls 联动用） */
  id?: string
}

export function DetailDrawer({
  open,
  onClose,
  title,
  children,
  footer,
  panelClassName,
  id,
}: DetailDrawerProps) {
  const isMobile = useIsMobile()

  if (isMobile) {
    return (
      <ActionSheet
        open={open}
        onClose={onClose}
        title={title}
        footer={footer}
        id={id}
        panelClassName={panelClassName}
      >
        {children}
      </ActionSheet>
    )
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      label={title}
      side="right"
      id={id}
      panelClassName={cx(
        // important：压过 Sheet right 形态自带的 max-w-md（448 > 440 契约上限）
        'flex max-w-[var(--lumi-width-detail-drawer)]! flex-col',
        panelClassName,
      )}
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--lumi-separator)] pr-1.5 pl-4">
        {/* 非 heading：accessible name 由 Sheet 的 sr-only Title 承载 */}
        <span className="min-w-0 truncate py-2.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
          {title}
        </span>
        <IconButton
          icon={<X aria-hidden="true" className="size-4" />}
          label="关闭"
          onClick={onClose}
          className="-mr-1"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4 text-sm text-[var(--lumi-text-primary)] [scrollbar-gutter:stable]">
        {children}
      </div>
      {footer !== undefined && (
        <div className="shrink-0 border-t border-[var(--lumi-separator)] px-4 py-3">{footer}</div>
      )}
    </Sheet>
  )
}
