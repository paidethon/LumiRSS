/** MatchExplain — F074「为什么匹配」徽标 + popover（SearchPage 结果行）。
 *
 * - 徽标渲染自服务端 matchedFields（中文标签映射）；
 * - popover：各字段命中的词 + 索引新鲜度（"索引于 N 分钟前"）+
 *   单腿降级提示（库腿不可用时如实说明）；
 * - 无分数 → 绝不显示任何百分比（负向契约）。 */

import { useState } from 'react'
import { Info } from 'lucide-react'
import { explainMatch, indexFreshnessLabel, MATCH_FIELD_LABELS, type MatchField } from '../lib/search-explain'

export function MatchExplainBadges({
  item,
  terms,
  lastSyncedAt,
  libraryError,
}: {
  item: { title: string; feedTitle: string; author?: string | null; snippet: string; matchedFields: string[] }
  terms: string[]
  lastSyncedAt: string | null | undefined
  /** 库腿降级提示（SearchResponse.libraryError；非空 = 单腿）。 */
  libraryError?: string | null
}) {
  const [open, setOpen] = useState(false)
  const explanations = explainMatch(item, terms)
  if (explanations.length === 0) return null
  const freshness = indexFreshnessLabel(lastSyncedAt)

  return (
    <span className="flex flex-wrap items-center gap-1" data-lumi-match-explain="">
      {explanations.map((e) => (
        <span
          key={e.field}
          className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]"
        >
          {MATCH_FIELD_LABELS[e.field as MatchField] ?? e.field}
        </span>
      ))}
      <button
        type="button"
        aria-label="为什么匹配"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex size-5 items-center justify-center rounded-full text-[var(--lumi-text-tertiary)] transition-colors hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <Info aria-hidden className="size-3" />
      </button>
      {open && (
        <span
          role="dialog"
          aria-label="命中解释"
          className="absolute z-20 max-w-72 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-2.5 shadow-[var(--lumi-shadow-popover)]"
        >
          <span className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
            {explanations.map((e) => (
              <span key={e.field}>
                <span className="font-medium">{e.label}</span>
                ：命中 {e.terms.join('、')}
              </span>
            ))}
            {libraryError !== null && libraryError !== undefined && (
              <span className="text-[var(--lumi-text-tertiary)]">库搜索暂不可用，结果仅来自 RSS 腿。</span>
            )}
            {freshness !== null && (
              <span className="text-[var(--lumi-text-tertiary)]">{freshness}</span>
            )}
            {/* 负向契约：后端无相关性分数，UI 不显示任何百分比 */}
          </span>
        </span>
      )}
    </span>
  )
}

export function matchBadgeLabel(field: string): string {
  return MATCH_FIELD_LABELS[field as MatchField] ?? field
}