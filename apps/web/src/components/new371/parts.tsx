/** NEW-371..380 运行治理组共享小件：情境展开子区（折叠 = 不挂载子
 * 面板 = 零查询）、状态行、输入类。视觉口径与 new341/parts.tsx 一致，
 * 只复用既有 --lumi-* 语义令牌；data-* 前缀为本组 n371。 */

import { useState, type ReactNode } from 'react'
import { cx } from '../ui/cx'

/** 情境展开子区：折叠态只渲染开关（aria-expanded）；children 可以是
 * 函数 ``(open) => ReactNode`` —— 查询类内容用它把请求门在真实展开后
 * （折叠 = 不挂载 = 零查询）。 */
export function SubSection({
  id,
  label,
  children,
}: {
  id: string
  label: string
  children: ReactNode | ((open: boolean) => ReactNode)
}) {
  const [open, setOpen] = useState(false)
  return (
    <section data-n371-subsection={id} className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between rounded-[var(--lumi-radius-lg)] px-3 py-2 text-left text-sm font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
      >
        {label}
        <span aria-hidden="true" className="text-[var(--lumi-text-tertiary)]">
          {open ? '−' : '+'}
        </span>
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t border-[var(--lumi-border)] p-3">
          {typeof children === 'function' ? children(open) : children}
        </div>
      )}
    </section>
  )
}

export function StatusLine({
  tone,
  children,
  testId,
}: {
  tone: 'info' | 'error' | 'ok'
  children: ReactNode
  testId?: string
}) {
  return (
    <p
      role={tone === 'error' ? 'alert' : undefined}
      data-n371-status={testId}
      className={cx(
        'text-sm leading-relaxed',
        tone === 'error' && 'text-[var(--lumi-danger)]',
        tone === 'ok' && 'text-[var(--lumi-success)]',
        tone === 'info' && 'text-[var(--lumi-text-secondary)]',
      )}
    >
      {children}
    </p>
  )
}

export function NoteText({ children }: { children: ReactNode }) {
  return <p className="text-sm leading-relaxed text-[var(--lumi-text-tertiary)]">{children}</p>
}

export const inputClass =
  'w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]'

export const labelClass =
  'text-xs font-medium text-[var(--lumi-text-secondary)]'

export const actionButtonClass =
  'self-start rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-1.5 text-sm font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)] disabled:opacity-50'

export function Field({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
    </label>
  )
}

export function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
