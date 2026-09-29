/** NEW-221..230 决策面板共享部件（feature 本地；Base UI 只经 ui/ 原语）。 */

import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { getTodayQueue } from '../../api/client'
import type { QueueItemView } from '../../api/types'
import { EmptyState } from '../ui/EmptyState'
import { cx } from '../ui/cx'

/** 今日队列成员（材料选择器数据源）；removed 行不出库门（服务端契约）。 */
export function useTodayItems() {
  const query = useQuery({
    queryKey: ['queue', 'today'],
    queryFn: ({ signal }) => getTodayQueue(signal),
  })
  const items = (query.data?.items ?? []).filter(
    (item: QueueItemView) => item.status !== 'removed',
  )
  return { items, isLoading: query.isLoading, error: query.error }
}

export function SectionShell({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children: ReactNode
}) {
  return (
    <section className="flex min-h-0 flex-1 flex-col gap-2" aria-label={title}>
      <header>
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">{title}</h3>
        {hint ? (
          <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">{hint}</p>
        ) : null}
      </header>
      {children}
    </section>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  const message = error instanceof Error ? error.message : String(error)
  return (
    <p role="alert" className="text-xs text-[var(--lumi-danger)]">
      {message}
    </p>
  )
}

/** 队列成员选择器（label 提示语义；value=ItemRef）。 */
export function ItemPicker({
  items,
  value,
  onChange,
  label,
  emptyLabel = '今天队列还没有条目',
}: {
  items: QueueItemView[]
  value: string
  onChange: (itemRef: string) => void
  label: string
  emptyLabel?: string
}) {
  if (items.length === 0) {
    return <p className="text-xs text-[var(--lumi-text-tertiary)]">{emptyLabel}</p>
  }
  return (
    <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
      <span className="shrink-0">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-7 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface)] px-1.5 py-0.5 text-xs"
      >
        <option value="">选择…</option>
        {items.map((item) => (
          <option key={item.id} value={item.itemRef}>
            {item.title ?? item.itemRef}
          </option>
        ))}
      </select>
    </label>
  )
}

/** 标签样式的小状态 chip（语义 token；不新增平行色板）。 */
export function Chip({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'accent' | 'warn'
  children: ReactNode
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center rounded-[var(--lumi-radius-full)] px-1.5 py-0.5 text-xs leading-tight',
        tone === 'accent' && 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]',
        tone === 'warn' && 'bg-[var(--lumi-surface-hover)] text-[var(--lumi-warning)]',
        tone === 'neutral' && 'bg-[var(--lumi-surface-hover)] text-[var(--lumi-text-secondary)]',
      )}
    >
      {children}
    </span>
  )
}

export function SectionEmpty({ message }: { message: string }) {
  return <EmptyState title={message} className="py-6" />
}
