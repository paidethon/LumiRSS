/** NEW-261..270 共享面板骨架 — 统一 section 外壳 / 通知行 / 索引徽标。
 * 语义 token（--lumi-*）only；控件全带可访问名。 */

import type { ReactNode } from 'react'

export function ToolSection({
  label,
  itemId,
  hint,
  children,
}: {
  label: string
  itemId: string
  hint?: string
  children: ReactNode
}) {
  return (
    <section
      aria-label={`${label}（${itemId}）`}
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">{label}</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">
          {itemId}
          {hint ? ` · ${hint}` : ''}
        </span>
      </div>
      {children}
    </section>
  )
}

export function NoticeLine({ tone, children }: { tone: 'info' | 'error' | 'success'; children: ReactNode }) {
  const color =
    tone === 'error'
      ? 'text-[var(--lumi-danger)]'
      : tone === 'success'
        ? 'text-[var(--lumi-success)]'
        : 'text-[var(--lumi-text-secondary)]'
  return (
    <p role="status" className={`text-xs leading-relaxed ${color}`}>
      {children}
    </p>
  )
}

export function IndexBadges({ indexes }: { indexes: number[] }) {
  if (indexes.length === 0) return null
  return (
    <span className="flex flex-wrap gap-1">
      {indexes.map((index) => (
        <span
          key={index}
          className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-hover)] px-1.5 py-0.5 text-xs text-[var(--lumi-text-secondary)]"
        >
          第 {index + 1} 段
        </span>
      ))}
    </span>
  )
}
