/** SearchParsePreview — N142「帮我转条件」预览（SearchPage）。
 *
 * 展示 parse-query 的结果为可编辑 chips：
 * - 每个已转换条件一个 chip，可移除（移除 = 不应用该条件，并把被
 *   消费的原文还给剩余关键词，绝不静默丢词）；
 * - unrecognized 逐词列出（服务端契约：未识别部分保留为关键词）；
 * - 应用只经用户确认（onApply），确认前不执行任何搜索。
 *
 * 编辑口径：移除即编辑（想把「今天」改成其他范围 → 移除后用日期
 * 面板重设）；不做行内改写，避免与既有的条件面板出现两套真相。
 */

import { useState } from 'react'
import { Sparkles, X } from 'lucide-react'
import type { SearchParseResult } from '../api/types'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

/** chips 的可编辑草稿（filters + 剩余关键词）。 */
export interface ParseDraft {
  filters: Record<string, string>
  remainingText: string
}

const KIND_LABELS: Record<string, string> = {
  date: '日期',
  source: '来源',
  phrase: '短语',
  exclude: '排除',
}

interface ChipView {
  key: string
  kind: string
  label: string
  /** 移除时还给剩余关键词的原文（可能为空 = 无法还原）。 */
  restoreText: string
  filterKeys: string[]
}

function buildChips(result: SearchParseResult): ChipView[] {
  const filters = result.filters ?? {}
  const recognized = result.recognized ?? []
  const chips: ChipView[] = []
  const recognizedOf = (kind: string) => recognized.find((r) => r.kind === kind)?.text ?? ''

  if (filters.from || filters.to) {
    const label =
      filters.from && filters.to
        ? `${filters.from} ~ ${filters.to}`
        : `${filters.from ?? '…'} ~ ${filters.to ?? '…'}`
    chips.push({
      key: 'date',
      kind: 'date',
      label,
      restoreText: recognizedOf('date'),
      filterKeys: ['from', 'to'],
    })
  }
  if (filters.feedRef) {
    chips.push({
      key: 'feedRef',
      kind: 'source',
      label: filters.feedRef,
      restoreText: recognizedOf('source'),
      filterKeys: ['feedRef'],
    })
  }
  if (filters.phrase) {
    chips.push({
      key: 'phrase',
      kind: 'phrase',
      label: `“${filters.phrase}”`,
      restoreText: recognizedOf('phrase'),
      filterKeys: ['phrase'],
    })
  }
  if (filters.exclude) {
    chips.push({
      key: 'exclude',
      kind: 'exclude',
      label: filters.exclude,
      restoreText: (recognized.filter((r) => r.kind === 'exclude').map((r) => r.text) ?? []).join(' ') || filters.exclude,
      filterKeys: ['exclude'],
    })
  }
  return chips
}

export function SearchParsePreview({
  result,
  pending,
  error,
  onApply,
  onClose,
  sourceLabelOf,
}: {
  result: SearchParseResult | null
  pending: boolean
  error: string | null
  onApply: (draft: ParseDraft) => void
  onClose: () => void
  /** feedUrl → 订阅标题（展示用；未命中回退 URL）。 */
  sourceLabelOf?: (feedUrl: string) => string | null
}) {
  const [draft, setDraft] = useState<ParseDraft | null>(null)
  // result 变化（重新解析）时重置草稿。
  const [seenResult, setSeenResult] = useState<SearchParseResult | null>(null)
  if (result !== null && result !== seenResult) {
    setSeenResult(result)
    setDraft({
      filters: { ...(result.filters ?? {}) },
      remainingText: result.remainingText ?? '',
    })
  }

  if (pending) {
    return (
      <div
        data-testid="parse-preview"
        role="status"
        className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3 text-xs text-[var(--lumi-text-secondary)]"
      >
        正在解析条件…
      </div>
    )
  }
  if (error !== null) {
    return (
      <div
        data-testid="parse-preview"
        role="alert"
        className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3 text-xs text-[var(--lumi-danger)]"
      >
        {error}
      </div>
    )
  }
  if (result === null || draft === null) return null

  const chips = buildChips({ ...result, filters: draft.filters })
  const unrecognized = result.unrecognized ?? []

  const removeChip = (chip: ChipView) => {
    setDraft((prev) => {
      if (prev === null) return prev
      const filters = { ...prev.filters }
      for (const key of chip.filterKeys) delete filters[key]
      const restore = chip.restoreText.trim()
      const remaining = restore
        ? `${prev.remainingText} ${restore}`.trim()
        : prev.remainingText
      return { filters, remainingText: remaining }
    })
  }

  return (
    <div
      data-testid="parse-preview"
      className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      role="group"
      aria-label="帮我转条件预览"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <Sparkles aria-hidden className="size-3.5" />
        已识别的条件（可移除后再应用）
      </p>
      {chips.length === 0 ? (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          没有识别出可转换的条件；全部文本将作为关键词搜索。
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((chip) => (
            <span
              key={chip.key}
              className="flex items-center gap-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] pl-2.5 pr-1 text-xs font-medium text-[var(--lumi-accent-text)]"
            >
              <span data-testid={`parse-chip-${chip.key}`}>
                {KIND_LABELS[chip.kind] ?? chip.kind}:{' '}
                {chip.key === 'feedRef' && sourceLabelOf
                  ? (sourceLabelOf(chip.label) ?? chip.label)
                  : chip.label}
              </span>
              <button
                type="button"
                aria-label={`移除条件「${chip.label}」`}
                onClick={() => removeChip(chip)}
                className="relative flex size-6 items-center justify-center rounded-full transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                <X aria-hidden className="size-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <p className="text-xs text-[var(--lumi-text-secondary)]">
        关键词：
        <span data-testid="parse-remaining" className={cx(draft.remainingText === '' && 'text-[var(--lumi-text-tertiary)]')}>
          {draft.remainingText === '' ? '（无——仅按条件过滤需要至少一个关键词）' : draft.remainingText}
        </span>
      </p>
      {unrecognized.length > 0 && (
        <p className="text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
          未转成条件、将保留为关键词：{unrecognized.join('、')}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          size="sm"
          data-testid="parse-apply"
          onClick={() => onApply(draft)}
        >
          应用这些条件
        </Button>
        <Button variant="ghost" size="sm" onClick={onClose}>
          取消
        </Button>
      </div>
    </div>
  )
}
