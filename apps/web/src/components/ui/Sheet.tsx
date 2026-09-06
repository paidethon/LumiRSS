/** Sheet primitive — Base UI Drawer 行为底座（原 0009/0011 自研实现迁移）。
 *
 * 移动端侧滑抽屉：left = 侧边导航抽屉（MobileNavigationDrawer）、
 * right = 右侧面板（ArticleConversation AI 对话）、bottom = 底部 sheet
 * （ReaderAaPanel 阅读样式）。行为由 Base UI Drawer（stable since 1.3，
 * 继承 Dialog 语义）提供：role=dialog + aria-modal、Escape、遮罩/外点
 * 关闭、焦点 trap 与还原、body 滚动锁、swipe-to-dismiss（方向随 side
 * 映射）。视觉保持 Lumi：--lumi-* token 面板、三方向定位、滑入动效
 * 用 motion-slow token + data-starting-style/data-ending-style 实现
 * （旧实现定义了 motion token 但从未真正动画，此处补齐且尊重
 * prefers-reduced-motion / data-motion-reduce）。 */

import { type ReactNode, useRef } from 'react'
import { Drawer as BaseDrawer } from '@base-ui/react/drawer'
import { cx } from './cx'

export interface SheetProps {
  open: boolean
  onClose: () => void
  /** 抽屉标题（aria-labelledby） */
  label: string
  children: ReactNode
  /** 滑出方向：left = 侧边导航抽屉；bottom = 底部 sheet；
   *  right = 右侧面板（AI 对话） */
  side?: 'left' | 'bottom' | 'right'
  /** 面板附加类（宽度/safe-area/背景表面由调用方定制） */
  panelClassName?: string
  /** 面板 id（供外部 aria-controls 联动，如顶栏菜单按钮） */
  id?: string
}

const SWIPE_DIRECTION = {
  left: 'left',
  right: 'right',
  bottom: 'down',
} as const

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

export function Sheet({ open, onClose, label, children, side = 'left', panelClassName, id }: SheetProps) {
  const popupRef = useRef<HTMLDivElement>(null)

  return (
    <BaseDrawer.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      swipeDirection={SWIPE_DIRECTION[side]}
    >
      <BaseDrawer.Portal>
        <BaseDrawer.Backdrop
          className={cx(
            'fixed inset-0 z-[var(--lumi-z-dialog)] bg-[var(--lumi-text-primary)]/30',
            'supports-[-webkit-touch-callout:none]:absolute',
          )}
        />
        <BaseDrawer.Viewport
          className={cx(
            'fixed inset-0 z-[var(--lumi-z-dialog)] flex',
            side === 'right' && 'justify-end',
            side === 'bottom' && 'items-end',
          )}
        >
          <BaseDrawer.Popup
            ref={popupRef}
            id={id}
            aria-modal="true"
            initialFocus={() => {
              const panel = popupRef.current
              return panel?.querySelector<HTMLElement>(FOCUSABLE) ?? panel
            }}
            className={cx(
              'relative bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-dialog)]',
              'transition-transform duration-[var(--lumi-motion-slow)] ease-[var(--lumi-ease)]',
              side === 'left' &&
                cx(
                  'h-full w-4/5 max-w-80 border-r border-[var(--lumi-border)]',
                  'data-starting-style:-translate-x-full data-ending-style:-translate-x-full',
                ),
              side === 'right' &&
                cx(
                  'h-full w-full max-w-md border-l border-[var(--lumi-border)]',
                  'data-starting-style:translate-x-full data-ending-style:translate-x-full',
                ),
              side === 'bottom' &&
                cx(
                  'max-h-[85dvh] w-full rounded-t-[var(--lumi-radius-xl)] border-t border-[var(--lumi-border)]',
                  'data-starting-style:translate-y-full data-ending-style:translate-y-full',
                ),
              panelClassName,
            )}
          >
            <BaseDrawer.Title className="sr-only">{label}</BaseDrawer.Title>
            {children}
          </BaseDrawer.Popup>
        </BaseDrawer.Viewport>
      </BaseDrawer.Portal>
    </BaseDrawer.Root>
  )
}
