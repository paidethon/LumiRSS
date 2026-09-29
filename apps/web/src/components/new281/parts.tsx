/** NEW-281..290 简报工具组共用小件：情境展开子区（折叠 = 不挂载子面板
 * = 零查询，MASTER §6）、带标签输入与统一反馈行。 */

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
    <section data-new281-subsection={id} className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]">
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
      role={tone === 'error' ? 'alert' : 'status'}
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

/** 带标签输入（label 显式关联，可访问性基线；id 前缀 new281-*）。 */
export function TextField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  const id = `new281-field-${label}`
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
      {label}
      <input
        id={id}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      />
    </label>
  )
}

export function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
}) {
  const id = `new281-select-${label}`
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
      {label}
      <select id={id} value={value} onChange={(event) => onChange(event.target.value)} className={inputClass}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

/** 统一的错误提取：ApiError 优先，普通 Error 兜底。 */
export function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
