/** NEW-291..300 邮件资料工具组共享小件：两级情境展开子区（折叠 =
 * 不挂载子面板 = 零查询，MASTER §6）与稳定的表单反馈行。与 new271
 * panel.tsx 同构（组件内容不同，不共享文件以免跨组耦合）。 */

import { useState, type ReactNode } from 'react'
import { cx } from '../ui/cx'

/** 情境展开子区：折叠态只渲染开关（aria-expanded），展开后才挂载
 * children——子面板里的查询只在真实展开时发起。 */
export function SubSection({
  id,
  label,
  children,
  defaultOpen = false,
}: {
  id: string
  label: string
  children: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section data-new291-subsection={id} className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]">
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
      {open && <div className="flex flex-col gap-3 border-t border-[var(--lumi-border)] p-3">{children}</div>}
    </section>
  )
}

export function StatusLine({ tone, children }: { tone: 'info' | 'error' | 'ok'; children: ReactNode }) {
  return (
    <p
      role={tone === 'error' ? 'alert' : undefined}
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

export const buttonClass =
  'self-start rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent)] px-3 py-1.5 text-sm font-medium text-[var(--lumi-accent-contrast)] hover:opacity-90 disabled:opacity-50'

export const secondaryButtonClass =
  'self-start rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-1.5 text-sm font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)] disabled:opacity-50'

export function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
