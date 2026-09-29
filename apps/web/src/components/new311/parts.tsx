/** NEW-311..320 剪藏与书签资料组共享小件：情境展开子区（折叠 = 不挂载
 * 子面板 = 零查询，MASTER §6）、状态行与表单类（与 new271/panel.tsx
 * 同一套视觉口径，只复用既有 --lumi-* 语义令牌）。 */

import { useState, type ReactNode } from 'react'
import { cx } from '../ui/cx'

/** 情境展开子区：折叠态只渲染开关（aria-expanded）；children 可以是
 * 函数 ``(open) => ReactNode``——查询类内容用它把请求门在真实展开后
 * （折叠 = 不挂载 = 零查询，MASTER §6）。 */
export function SubSection({
  id,
  label,
  children,
  defaultOpen = false,
}: {
  id: string
  label: string
  children: ReactNode | ((open: boolean) => ReactNode)
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section data-new311-subsection={id} className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]">
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

/** 统一的错误提取：ApiError 优先，普通 Error 兜底。 */
export function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
