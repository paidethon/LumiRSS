/** NEW-237 引用卡片组装 — 从自己的几段引文组一张带来源索引的文字卡。
 * 导出前必须可预览（markdown 全文 + 来源索引）；批注可选是否包含；
 * 预览如实上报无法引用的 id（unknownIds）。 */

import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { exportQuoteCard, previewQuoteCard, type QuoteCardPreview } from '../../api/new231'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'

export function QuoteCardComposer({ selectedIds }: { selectedIds: Set<string> }) {
  const [includeNotes, setIncludeNotes] = useState(true)
  const [title, setTitle] = useState('')
  const [preview, setPreview] = useState<QuoteCardPreview | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const ids = [...selectedIds]

  const previewMutation = useMutation({
    mutationFn: () => previewQuoteCard(ids, includeNotes, title.trim() || undefined),
    onSuccess: (result) => {
      setPreview(result)
      setNotice(
        result.unknownIds.length > 0
          ? `有 ${result.unknownIds.length} 条无法引用（已跳过）。`
          : null,
      )
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '预览失败'),
  })
  const exportMutation = useMutation({
    mutationFn: () => exportQuoteCard(ids, includeNotes, title.trim() || undefined),
    onSuccess: async (markdown) => {
      const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'lumi-quote-card.md'
      anchor.click()
      URL.revokeObjectURL(url)
      setNotice('已导出引用卡片。')
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '导出失败'),
  })

  return (
    <section aria-label="引用卡片组装（NEW-237）" className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">引用卡片</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-237 · 从选中批注组装</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="卡片标题（可空）"
          aria-label="卡片标题"
          className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm"
        />
        <label className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
          <input
            type="checkbox"
            checked={includeNotes}
            onChange={(event) => setIncludeNotes(event.target.checked)}
            aria-label="包含我的批注"
            className="size-3.5"
          />
          包含批注
        </label>
        <Button size="sm" variant="secondary" disabled={ids.length === 0 || previewMutation.isPending} onClick={() => previewMutation.mutate()}>
          预览卡片（{ids.length} 条）
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={ids.length === 0 || exportMutation.isPending}
          onClick={() => exportMutation.mutate()}
        >
          导出
        </Button>
      </div>

      {ids.length === 0 && (
        <EmptyState title="先选择批注" description="在批注列表勾选若干条，再在这里组装成带来源索引的文字卡。" />
      )}

      {preview !== null && (
        <div className="flex flex-col gap-1" aria-label="卡片预览">
          <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] p-2 text-xs">
            {preview.markdown}
          </pre>
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            来源索引 {preview.sources.length} 项 · 引文 {preview.quoteCount} 条
          </p>
        </div>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{notice}</p>
      )}
    </section>
  )
}
