/** F014 阅读预算面板 —— 会话内临时清单（不写入稍后读、不持久化）。
 *
 * 预算选择 5/15/30/60 分钟 → 按当前筛选的未读候选装填；清单可移除/
 * 调序（上移/下移）；「开始阅读」进入顺序模式（当前成员读完点「下一篇」；
 * 明确标注「估读时间≠实际」）；退出/完成清空本次清单。 */

import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, CalendarClock, Play, Trash2, X } from 'lucide-react'
import {
  buildReadingBudget,
  type BudgetCandidate,
  type BudgetItem,
} from '../lib/reading-budget'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { cx } from './ui/cx'

const BUDGET_OPTIONS = [5, 15, 30, 60] as const

export function ReadingBudgetPanel({
  candidates,
  onOpenEntry,
  onClose,
}: {
  candidates: BudgetCandidate[]
  /** 「下一篇」时打开对应文章（顺序阅读模式）。 */
  onOpenEntry?: (entryRef: string) => void
  onClose: () => void
}) {
  const [budget, setBudget] = useState<number | null>(null)
  const [items, setItems] = useState<BudgetItem[] | null>(null)
  const [reading, setReading] = useState(false)
  const [cursor, setCursor] = useState(0)

  const result = useMemo(
    () => (budget === null ? null : buildReadingBudget(candidates, budget)),
    [candidates, budget],
  )

  function generate(minutes: number) {
    setBudget(minutes)
    setReading(false)
    setCursor(0)
    const r = buildReadingBudget(candidates, minutes)
    setItems(r.items)
  }

  function removeItem(entryRef: string) {
    setItems((prev) => (prev ?? []).filter((item) => item.entryRef !== entryRef))
    setCursor(0)
  }

  function move(entryRef: string, direction: -1 | 1) {
    setItems((prev) => {
      const list = [...(prev ?? [])]
      const index = list.findIndex((item) => item.entryRef === entryRef)
      const target = index + direction
      if (index === -1 || target < 0 || target >= list.length) return prev
      const tmp = list[index]!
      list[index] = list[target]!
      list[target] = tmp
      return list
    })
  }

  function closeAndClear() {
    setItems(null)
    setBudget(null)
    setReading(false)
    setCursor(0)
    onClose()
  }

  const totalMinutes = (items ?? []).reduce((sum, item) => sum + item.minutes, 0)

  return (
    <section
      aria-label="阅读预算"
      data-testid="reading-budget-panel"
      className="mx-4 mb-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <CalendarClock aria-hidden className="size-4 text-[var(--lumi-accent-text)]" />
        <h3 className="text-sm font-semibold text-[var(--lumi-text-primary)]">阅读预算</h3>
        <span className="flex-1" />
        <button
          type="button"
          aria-label="关闭阅读预算"
          onClick={closeAndClear}
          className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>

      {/* 预算选择 */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="预算选择">
        {BUDGET_OPTIONS.map((minutes) => (
          <Button
            key={minutes}
            size="sm"
            variant={budget === minutes ? 'primary' : 'secondary'}
            onClick={() => generate(minutes)}
          >
            {minutes} 分钟
          </Button>
        ))}
      </div>

      {items !== null && result !== null && (
        <>
          <p className="mt-2 text-xs text-[var(--lumi-text-secondary)]" role="status">
            共 {items.length} 篇 · 估读合计约 {totalMinutes} 分钟
            {result.underBudget && '（当前筛选下估算不足预算，已全收）'}
            {' · '}
            <span className="text-[var(--lumi-text-tertiary)]">估读时间≠实际，临时清单不写入稍后读</span>
          </p>
          {items.length === 0 ? (
            <div className="mt-1">
              <EmptyState
                icon={<CalendarClock aria-hidden className="size-6" />}
                title="当前筛选下没有可装填的未读文章"
                description="切换到「未读」或调整筛选后重试。"
              />
            </div>
          ) : reading ? (
            /* 顺序阅读模式 */
            <div className="mt-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] p-3">
              <p className="text-xs text-[var(--lumi-text-tertiary)]">
                顺序阅读 {Math.min(cursor + 1, items.length)} / {items.length} · 估读时间≠实际
              </p>
              <p className="mt-1 truncate text-sm font-medium text-[var(--lumi-text-primary)]">
                {items[cursor]?.title ?? '清单已读完'}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {cursor < items.length && (
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => {
                      const item = items[cursor]
                      if (item && onOpenEntry !== undefined) onOpenEntry(item.entryRef)
                    }}
                  >
                    打开当前篇
                  </Button>
                )}
                {cursor < items.length - 1 && (
                  <Button size="sm" variant="secondary" onClick={() => setCursor((c) => c + 1)}>
                    下一篇
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={closeAndClear}>
                  完成并清空清单
                </Button>
              </div>
            </div>
          ) : (
            <>
              <ul className="mt-2 max-h-48 divide-y divide-[var(--lumi-separator)] overflow-y-auto rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]">
                {items.map((item, index) => (
                  <li key={item.entryRef} className="flex items-center gap-1.5 px-2.5 py-1.5">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-[var(--lumi-text-primary)]">{item.title}</span>
                      <span className="block text-xs text-[var(--lumi-text-tertiary)]">约 {item.minutes} 分钟</span>
                    </span>
                    <button
                      type="button"
                      aria-label={`上移「${item.title}」`}
                      disabled={index === 0}
                      onClick={() => move(item.entryRef, -1)}
                      className="flex min-h-11 min-w-11 items-center justify-center rounded text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)] disabled:opacity-30"
                    >
                      <ArrowUp aria-hidden className="size-3.5" />
                    </button>
                    <button
                      type="button"
                      aria-label={`下移「${item.title}」`}
                      disabled={index === items.length - 1}
                      onClick={() => move(item.entryRef, 1)}
                      className="flex min-h-11 min-w-11 items-center justify-center rounded text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)] disabled:opacity-30"
                    >
                      <ArrowDown aria-hidden className="size-3.5" />
                    </button>
                    <button
                      type="button"
                      aria-label={`移除「${item.title}」`}
                      onClick={() => removeItem(item.entryRef)}
                      className="flex min-h-11 min-w-11 items-center justify-center rounded text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
                    >
                      <Trash2 aria-hidden className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
              <div className="mt-2 flex items-center gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  disabled={items.length === 0}
                  onClick={() => setReading(true)}
                >
                  <Play aria-hidden className="size-3.5" />
                  开始阅读
                </Button>
              </div>
            </>
          )}
        </>
      )}
      {items !== null && items.length > 0 && !reading && (
        <p className={cx('mt-1 text-[10px] text-[var(--lumi-text-tertiary)]')} aria-hidden>
          清单仅在本次会话有效
        </p>
      )}
    </section>
  )
}
