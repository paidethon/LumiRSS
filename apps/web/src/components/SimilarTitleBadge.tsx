/** SimilarTitleBadge — N148 相似标题区别提示（搜索结果行内 chip）。
 *
 * 同一结果页内出现近同名标题（规范化 bigram Jaccard ≥ 0.8，客户端
 * 判定）时，给相关行加「相似标题」chip + 对比 popover（来源 / 时间 /
 * 摘录并排展示）。只帮助区分，绝不合并、绝不隐藏任何结果行。
 */

import { CircleDashed } from 'lucide-react'
import type { SearchItem } from '../api/types'
import { Popover } from './ui/Popover'
import { dateTimeFormatter } from '../lib/date-format'

function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return dateTimeFormatter.format(date)
}

/** 对比卡：一行相似结果的 来源/时间/摘录。 */
function CompareCard({ item }: { item: SearchItem }) {
  return (
    <div
      data-testid="similar-title-card"
      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5"
    >
      <p className="line-clamp-2 text-xs font-medium text-[var(--lumi-text-primary)]">
        {item.title}
      </p>
      <p className="mt-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
        <span>来源：{item.feedTitle}</span>
        <span className="mx-1.5">·</span>
        <span>{formatTime(item.publishedAt)}</span>
      </p>
      {item.snippet !== '' && (
        <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-[var(--lumi-text-secondary)]">
          {item.snippet}
        </p>
      )}
    </div>
  )
}

export function SimilarTitleBadge({
  item,
  similarItems,
}: {
  item: SearchItem
  /** 同页与本行标题相似（但不相同 ref）的其它结果。 */
  similarItems: SearchItem[]
}) {
  if (similarItems.length === 0) return null
  const group = [item, ...similarItems]
  return (
    <Popover
      width={300}
      trigger={({ triggerProps }) => (
        <button
          type="button"
          data-testid="similar-title-chip"
          {...triggerProps}
          aria-label={`相似标题（${similarItems.length}）：查看对比`}
          className={cxChip()}
        >
          <CircleDashed aria-hidden className="size-3" />
          相似标题{similarItems.length > 1 ? `（${similarItems.length}）` : ''}
        </button>
      )}
    >
      {() => (
        <div className="flex flex-col gap-1.5">
          <p className="text-[11px] font-medium text-[var(--lumi-text-secondary)]">
            以下是标题相似的不同条目（不会合并）：
          </p>
          {group.map((entry) => (
            <CompareCard key={entry.entryRef} item={entry} />
          ))}
        </div>
      )}
    </Popover>
  )
}

function cxChip(): string {
  return [
    'inline-flex shrink-0 items-center gap-1 rounded-[var(--lumi-radius-full)]',
    'border border-dashed border-[var(--lumi-border)] px-1.5 text-[11px]',
    'text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)]',
    'hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
  ].join(' ')
}
