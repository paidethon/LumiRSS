/** Dialog primitive — Base UI 行为底座（原 0009 Gate 1 自研实现迁移）。
 *
 * 模态对话框。行为全部由 Base UI Dialog（modal）提供：role="dialog" +
 * aria-modal、Escape 关闭、焦点 trap、关闭还焦、body 滚动锁、遮罩/
 * 外点关闭、Title 自动 aria-labelledby（含 hideTitle 时的 sr-only 兜底，
 * 修复旧实现 hideTitle 后 aria-labelledby 悬空的缺陷）。
 * Lumi 只负责视觉：--lumi-* token、遮罩色、面板圆角/阴影/边框、
 * 移动端全屏（<768 撑满 viewport）、footer 布局。 */

import { type ReactNode, useRef } from 'react'
import { Dialog as BaseDialog } from '@base-ui/react/dialog'
import { cx } from './cx'

export interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  /** 底部操作区（按钮等）；由调用方组装 */
  footer?: ReactNode
  /** 面板宽度类（默认 max-w-md；大面板如设置中心传自定义宽度） */
  panelClassName?: string
  /** 隐藏内置标题行（大面板自带头部时用；aria 仍需要 title 提供名字） */
  hideTitle?: boolean
  /** 移动端全屏（<768：面板撑满 viewport，无遮罩圆角；设置中心用） */
  fullscreenOnMobile?: boolean
}

/** 初始焦点目标：面板内第一个可聚焦元素（无则面板自身）。
 * 保持旧实现的焦点语义（首字符即可输入，如 AddSourceDialog 的地址框）。 */
const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

export function Dialog({ open, onClose, title, children, footer, panelClassName, hideTitle, fullscreenOnMobile }: DialogProps) {
  const popupRef = useRef<HTMLDivElement>(null)

  return (
    <BaseDialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <BaseDialog.Portal>
        {/* 遮罩（移动端全屏时透明）；iOS 26+ Safari 退为 absolute 盖住 body
         * （官方前置：body { position: relative }，见 index.css） */}
        <BaseDialog.Backdrop
          className={cx(
            'fixed inset-0 z-[var(--lumi-z-dialog)] bg-[var(--lumi-text-primary)]/30',
            'supports-[-webkit-touch-callout:none]:absolute',
            fullscreenOnMobile && 'bg-transparent md:bg-[var(--lumi-text-primary)]/30',
          )}
        />
        {/* Viewport = 旧实现的 fixed 容器：居中 + 视口内不溢出 */}
        <BaseDialog.Viewport
          className={cx(
            'fixed inset-0 z-[var(--lumi-z-dialog)] flex items-center justify-center p-4',
            fullscreenOnMobile && 'items-stretch justify-stretch p-0 md:items-center md:justify-center md:p-4',
          )}
        >
          <BaseDialog.Popup
            ref={popupRef}
            /* Base UI 以「面板外内容 inert」实现模态隔离（比 aria-modal 更强）；
             * 仍显式挂 aria-modal 保持 WAI-ARIA 模态对话框契约（项目 a11y 门禁） */
            aria-modal="true"
            initialFocus={() => {
              const panel = popupRef.current
              return panel?.querySelector<HTMLElement>(FOCUSABLE) ?? panel
            }}
            className={cx(
              'relative w-full p-5',
              'rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)]',
              'shadow-[var(--lumi-shadow-dialog)]',
              panelClassName ?? 'max-w-md',
              fullscreenOnMobile &&
                'max-md:h-dvh max-md:w-screen max-md:rounded-none max-md:border-0 max-md:shadow-none',
            )}
          >
            <BaseDialog.Title
              className={
                hideTitle
                  ? 'sr-only'
                  : 'mb-3 text-base font-semibold text-[var(--lumi-text-primary)]'
              }
            >
              {title}
            </BaseDialog.Title>
            <div className="text-sm text-[var(--lumi-text-primary)]">{children}</div>
            {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
          </BaseDialog.Popup>
        </BaseDialog.Viewport>
      </BaseDialog.Portal>
    </BaseDialog.Root>
  )
}
