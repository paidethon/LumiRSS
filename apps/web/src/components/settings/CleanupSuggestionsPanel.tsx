/** CleanupSuggestionsPanel — N017：设置 → 订阅与来源 的清理建议。
 *
 * GET /sources/cleanup-suggestions：长期未读 × 仍高产的自有数据投影
 * （lastReadAt 来自本服务器的已读记录投影，诚实标注口径）；建议仅是
 * 文字（demote / mute），GET 绝无副作用。用户逐项勾选后一次性
 * 应用：mute = 时间线隐藏（可随时撤销）；demote = 移入指定分类。
 * 没有自动退订，没有全选默认。
 */

import { useState } from 'react'
import { AlertCircle, CheckCircle2 } from 'lucide-react'
import {
  useApplyCleanupSuggestionsMutation,
  useCleanupSuggestions,
} from '../../api/queries'
import type { CleanupSuggestion } from '../../api/client'
import { formatTimestamp } from '../../lib/date-format'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

const SUGGESTION_LABELS: Record<CleanupSuggestion['suggestion'], string> = {
  demote: '建议降级（移入低优先级分类）',
  mute: '建议静音（从时间线隐藏）',
}

function errorText(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message
  return fallback
}

export function CleanupSuggestionsPanel() {
  const suggestions = useCleanupSuggestions()
  const apply = useApplyCleanupSuggestionsMutation()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [action, setAction] = useState<'mute' | 'demote_category'>('mute')
  const [categoryLabel, setCategoryLabel] = useState('低优先级')

  const items = suggestions.data?.items ?? []
  const toggle = (feedUrl: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(feedUrl)) next.delete(feedUrl)
      else next.add(feedUrl)
      return next
    })
  }

  const runApply = () => {
    apply.mutate(
      {
        feedUrls: Array.from(selected),
        action,
        targetCategoryLabel: action === 'demote_category' ? categoryLabel.trim() : undefined,
      },
      {
        onSuccess: () => setSelected(new Set()),
      },
    )
  }

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5" data-cleanup-panel="">
      <p className="text-sm font-medium text-[var(--lumi-text-primary)]">清理建议</p>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        找出「长期未读但仍高产」的来源，供你手动静音或降级。数据只来自你自己的阅读记录
        （本服务器的已读记录 + 最近 28 天产量）；建议不会自动执行，也绝不自动退订。
      </p>

      {suggestions.isPending && (
        <div className="mt-3 flex flex-col gap-2" aria-label="清理建议加载中">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      )}
      {suggestions.isError && (
        <p role="alert" className="mt-2 flex items-center gap-1.5 text-xs text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="size-3.5 shrink-0" />
          {errorText(suggestions.error, '建议加载失败。')}
        </p>
      )}

      {items.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1.5" data-cleanup-items="">
          {items.map((item) => (
            <li
              key={item.feedUrl}
              className="flex items-start gap-2.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2"
            >
              <input
                type="checkbox"
                id={`cleanup-${item.feedUrl}`}
                checked={selected.has(item.feedUrl)}
                onChange={() => toggle(item.feedUrl)}
                className="mt-0.5 size-4 shrink-0"
                aria-label={`选择 ${item.title}`}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-[var(--lumi-text-primary)]">{item.title}</p>
                <p className="mt-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                  {item.weeklyYield} 条/周 ·{' '}
                  {item.lastReadAt != null
                    ? `最近已读 ${formatTimestamp(item.lastReadAt)}`
                    : '本服务器暂无已读记录'}
                </p>
                <p className="mt-0.5 text-[11px] text-[var(--lumi-text-secondary)]">
                  {SUGGESTION_LABELS[item.suggestion]}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}

      {suggestions.isSuccess && items.length === 0 && (
        <p role="status" className="mt-3 text-xs text-[var(--lumi-text-tertiary)]" data-cleanup-empty="">
          暂时没有需要清理的来源。
        </p>
      )}

      {selected.size > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2" data-cleanup-apply="">
          <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
            动作
            <select
              aria-label="应用动作"
              value={action}
              onChange={(e) => setAction(e.target.value as 'mute' | 'demote_category')}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
            >
              <option value="mute">静音（时间线隐藏，可撤销）</option>
              <option value="demote_category">降级（移入分类）</option>
            </select>
          </label>
          {action === 'demote_category' && (
            <input
              aria-label="目标分类名称"
              value={categoryLabel}
              onChange={(e) => setCategoryLabel(e.target.value)}
              className="w-32 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
              placeholder="低优先级"
            />
          )}
          <Button size="sm" variant="primary" onClick={runApply} disabled={apply.isPending}>
            应用（{selected.size} 项）
          </Button>
        </div>
      )}

      {apply.isSuccess && (
        <p role="status" className={cx('mt-2 flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]')} data-cleanup-applied="">
          <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-accent-text)]" />
          已应用 {apply.data.applied} 项（仅限你勾选的来源）。
        </p>
      )}
      {apply.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          {errorText(apply.error, '应用失败，请稍后重试。')}
        </p>
      )}
    </div>
  )
}
