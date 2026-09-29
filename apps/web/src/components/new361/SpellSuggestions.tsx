/** SpellSuggestions — NEW-368 相近拼写搜索提示（零命中时）。
 *
 * 只在父级判定零命中时拉取；候选是可选择的 chip——点击 = 用户显式
 * 替换输入，绝不自动替换原查询（负向契约）。
 */

import { useQuery } from '@tanstack/react-query'
import { SpellCheck } from 'lucide-react'
import { fetchSpellSuggestions } from '../../api/new361'

export function SpellSuggestions({
  query,
  zeroHits,
  onPick,
}: {
  query: string
  /** 父级根据结果集判定（true = 本次搜索零命中）。 */
  zeroHits: boolean
  onPick: (suggestion: string) => void
}) {
  const enabled = zeroHits && query.trim() !== ''
  const spell = useQuery({
    queryKey: ['new368', 'spell', query],
    queryFn: () => fetchSpellSuggestions(query),
    enabled,
    staleTime: 30_000,
  })
  if (!enabled || spell.data === undefined || spell.data.candidates.length === 0) {
    return null
  }
  const suggestions = Array.from(
    new Set(spell.data.candidates.map((candidate) => candidate.suggestion)),
  ).slice(0, 6)

  return (
    <div
      data-testid="n368-spell"
      role="group"
      aria-label="相近拼写候选"
      className="flex flex-wrap items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]"
    >
      <SpellCheck aria-hidden className="size-3.5" />
      <span>没有命中。你是不是想搜（点击选择，不会自动替换）：</span>
      {suggestions.map((suggestion) => (
        <button
          key={suggestion}
          type="button"
          data-testid="n368-spell-option"
          onClick={() => onPick(suggestion)}
          className="min-h-7 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          {suggestion}
        </button>
      ))}
    </div>
  )
}
