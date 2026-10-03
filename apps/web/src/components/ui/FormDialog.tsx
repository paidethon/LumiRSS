/** FormDialog primitive — R3 共享契约 §2（Wave0 foundation）。
 *
 * 表单对话框：基于 ui/Dialog.tsx（Base UI Dialog：Escape / 焦点 trap /
 * 遮罩关闭 / body 滚动锁全继承）。结构契约：
 * - 头部：标题行 + 关闭钮 sticky 在滚动容器顶（长表单滚动时恒可见）。
 *   标题用非 heading 元素——accessible name 由 Dialog 的 sr-only Title
 *   承载（hideTitle 形态，MobileNavigationDrawer 的 span 标题同款），
 *   面板内只有一个 heading，不重复；
 * - 正文：children 在 Dialog 的滚动区内滚动；description 置顶；
 * - 底部操作区：sticky 在滚动容器底（长表单滚动时操作区恒可达），
 *   整体包在原生 form 元素里——回车提交走原生 form submit；
 * - 宽度：--lumi-width-form-dialog token（28rem）。
 *
 * busy：提交按钮 loading + aria-busy + disabled（Button FIX-115 契约），
 * 由消费方在 onSubmit 异步期间置 true。 */

import { X } from 'lucide-react'
import type { FormEvent, ReactNode } from 'react'
import { Button } from './Button'
import { cx } from './cx'
import { Dialog } from './Dialog'
import { IconButton } from './IconButton'

export interface FormDialogProps {
  open: boolean
  onClose: () => void
  /** 表单标题（同时是 accessible name） */
  title: string
  /** 置顶说明（一句话） */
  description?: ReactNode
  /** 表单字段 */
  children: ReactNode
  /** 提交回调（原生 form submit；busy 期间不触发） */
  onSubmit: () => void
  /** 提交按钮文案 */
  submitLabel: string
  /** 取消按钮文案（默认 取消） */
  cancelLabel?: string
  /** 提交中：提交按钮 loading + 禁用 */
  busy?: boolean
  /** 面板附加类（宽度默认 --lumi-width-form-dialog token） */
  panelClassName?: string
}

export function FormDialog({
  open,
  onClose,
  title,
  description,
  children,
  onSubmit,
  submitLabel,
  cancelLabel = '取消',
  busy = false,
  panelClassName,
}: FormDialogProps) {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!busy) onSubmit()
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      hideTitle
      panelClassName={cx('max-w-[var(--lumi-width-form-dialog)]', panelClassName)}
    >
      <form onSubmit={handleSubmit}>
        {/* sticky 头部：标题（非 heading，sr-only Title 承载语义）+ 关闭钮。
            -mx-5/px-5 出血到面板边（Dialog 面板 p-5），bg 遮住滚动内容。 */}
        <div
          className={cx(
            'sticky top-0 z-[1] -mx-5 mb-3 flex items-center justify-between gap-2',
            'bg-[var(--lumi-surface-elevated)] px-5 pb-2 pt-0.5',
          )}
        >
          <div className="min-w-0 truncate text-base font-semibold leading-tight text-[var(--lumi-text-primary)]">
            {title}
          </div>
          <IconButton
            icon={<X aria-hidden="true" className="size-4" />}
            label="关闭"
            onClick={onClose}
            className="-mr-1 shrink-0"
          />
        </div>
        {description !== undefined && (
          <p className="mb-3 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            {description}
          </p>
        )}
        <div className="flex flex-col gap-4">{children}</div>
        {/* sticky 底部：正文滚动时操作区钉在滚动容器底（Dialog 的 children 区即滚动区） */}
        <div
          className={cx(
            'sticky bottom-0 -mx-5 mt-5 flex items-center justify-end gap-2',
            'border-t border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-5 pt-3',
          )}
        >
          <Button type="button" variant="secondary" onClick={onClose}>
            {cancelLabel}
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            {submitLabel}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
