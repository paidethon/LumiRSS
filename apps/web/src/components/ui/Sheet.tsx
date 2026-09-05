/** Sheet primitive — 0009 Gate 1；0011 Gate 2 升级为完整 modal。
 *
 * 移动端侧滑抽屉（Drawer）：底部小屏导航/表单用。Escape 关闭、
 * 遮罩点击关闭、关闭还焦、进入时焦点入面板。宽度由 panelClassName
 * 控制（默认 80vw / max 320px）。桌面 Drawer 场景复用同一组件。
 *
 * 0011 Gate 2（用户批准的 modal 升级，Spec AC7）：
 * - role="dialog" + aria-modal + 焦点 trap（Tab 在面板内循环）；
 * - 初始焦点：第一个可聚焦元素（无则面板自身）；
 * - 打开时锁定背景滚动（body overflow hidden，关闭恢复）；
 * - 遮罩点击关闭修复：pointerdown 目标不在面板内即关闭
 *  （原实现 `target === currentTarget` 因遮罩 div 覆盖而永不触发）。
 *
 * 0016：新增 side="right"（0016 AI 对话面板；移动端全宽 = 全屏对话）。 */

import { type ReactNode, useId, useRef } from 'react'
import { cx } from './cx'
import { useModalA11y } from '../../lib/use-modal-a11y'

export interface SheetProps {
  open: boolean
  onClose: () => void
  /** 抽屉标题（aria-labelledby） */
  label: string
  children: ReactNode
  /** 滑出方向：left = 侧边导航抽屉；bottom = 底部 sheet；
   *  right = 右侧面板（0016 AI 对话） */
  side?: 'left' | 'bottom' | 'right'
  /** 面板附加类（宽度/safe-area/背景表面由调用方定制） */
  panelClassName?: string
  /** 面板 id（供外部 aria-controls 联动，如顶栏菜单按钮） */
  id?: string
}

export function Sheet({ open, onClose, label, children, side = 'left', panelClassName, id }: SheetProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const labelId = useId()
  // 0020 Gate 3：模态键盘/焦点/滚动行为复用共享 hook（与 Dialog/
  // MobileSettingsScreen 同源）。遮罩点击关闭仍由下方 onPointerDown 处理。
  useModalA11y(panelRef, open, onClose)

  if (!open) return null

  return (
    <div
      className={cx(
        'fixed inset-0 z-[var(--lumi-z-dialog)]',
        side === 'left' && 'flex',
        side === 'right' && 'flex justify-end',
        side === 'bottom' && 'flex items-end',
      )}
      onPointerDown={(e) => {
        // 遮罩点击关闭：目标不在面板内（遮罩 div / 容器空白）即关闭
        if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
          onClose()
        }
      }}
    >
      <div
        className="absolute inset-0 bg-[var(--lumi-text-primary)]/30"
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        id={id}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
        tabIndex={-1}
        className={cx(
          'relative bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-dialog)]',
          'duration-[var(--lumi-motion-slow)]',
          side === 'left' &&
            'h-full w-4/5 max-w-80 border-r border-[var(--lumi-border)]',
          side === 'right' &&
            'h-full w-full max-w-md border-l border-[var(--lumi-border)]',
          side === 'bottom' &&
            'max-h-[85dvh] w-full rounded-t-[var(--lumi-radius-xl)] border-t border-[var(--lumi-border)]',
          panelClassName,
        )}
      >
        <h2 id={labelId} className="sr-only">
          {label}
        </h2>
        {children}
      </div>
    </div>
  )
}
