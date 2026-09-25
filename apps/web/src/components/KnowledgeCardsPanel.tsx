/** KnowledgeCardsPanel — F070 文章工具「提取知识卡片」（折叠面板）。
 *
 * 预览候选卡（证据核验由服务端完成）→ 勾选 + 可编辑解释 → 保存；
 * 取消（不调用保存端点）= 零写入；保存逐条显示 created/skipped。 */

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Layers } from 'lucide-react'
import { previewKnowledgeCards, saveKnowledgeCards } from '../api/client'
import type { EntryDetail } from '../api/types'
import { Button } from './ui/Button'

interface Draft {
  concept: string
  explanation: string
  sourceQuote: string
  verified: boolean
  selected: boolean
}

export function KnowledgeCardsPanel({ detail }: { detail: EntryDetail }) {
  const [open, setOpen] = useState(false)
  const [drafts, setDrafts] = useState<Draft[] | null>(null)
  const [savedResults, setSavedResults] = useState<{ concept: string; status: string }[] | null>(null)
  const queryClient = useQueryClient()

  const preview = useMutation({
    mutationFn: () => previewKnowledgeCards(detail.entryRef, 10),
    onSuccess: (result) =>
      setDrafts(
        result.cards.map((c) => ({
          concept: c.concept,
          explanation: c.explanation,
          sourceQuote: c.sourceQuote,
          verified: c.verified,
          selected: true,
        })),
      ),
  })
  const save = useMutation({
    mutationFn: () =>
      saveKnowledgeCards(
        detail.entryRef,
        (drafts ?? [])
          .filter((d) => d.selected)
          .map((d) => ({ concept: d.concept, explanation: d.explanation, sourceQuote: d.sourceQuote })),
      ),
    onSuccess: (result) => {
      setSavedResults(result.results.map((r) => ({ concept: r.concept, status: r.status })))
      // N080：只统计实际创建（status='created'）的卡片，skipped/error 不计。
      const createdCount = result.results.filter((r) => r.status === 'created').length
      if (createdCount > 0) {
        void import('../lib/session-recap').then(({ recordRecapEvent }) => {
          for (let i = 0; i < createdCount; i += 1) recordRecapEvent('card', detail.entryRef)
        })
      }
      void queryClient.invalidateQueries({ queryKey: ['knowledge-cards'] })
    },
  })

  const selectedCount = (drafts ?? []).filter((d) => d.selected).length
  const cancel = () => {
    // 取消 = 零写入：丢弃草稿，不发任何保存请求
    setDrafts(null)
    setSavedResults(null)
    setOpen(false)
  }

  return (
    <section
      data-lumi-knowledge-panel=""
      className="mt-4 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2"
    >
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="inline-flex items-center gap-1 text-xs font-medium text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          <Layers aria-hidden className="size-3.5" />
          知识卡片
        </button>
        {open && drafts === null && (
          <Button
            size="sm"
            variant="primary"
            disabled={preview.isPending}
            onClick={() => preview.mutate()}
          >
            {preview.isPending ? '提取中…' : '提取候选卡片'}
          </Button>
        )}
      </div>
      {open && (
        <div className="mt-2 flex flex-col gap-2">
          {preview.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {preview.error instanceof Error ? preview.error.message : '提取失败，请稍后重试。'}
            </p>
          )}
          {(drafts ?? []).map((draft, i) => (
            <div key={draft.concept} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  aria-label={`选择卡片 ${draft.concept}`}
                  checked={draft.selected}
                  onChange={() =>
                    setDrafts((prev) =>
                      (prev ?? []).map((d, j) => (j === i ? { ...d, selected: !d.selected } : d)),
                    )
                  }
                />
                <span className="font-medium text-[var(--lumi-text-primary)]">{draft.concept}</span>
                {!draft.verified && (
                  <span className="text-[11px] text-[var(--lumi-danger)]">证据未通过核验</span>
                )}
              </label>
              <textarea
                aria-label={`编辑卡片解释 ${draft.concept}`}
                value={draft.explanation}
                rows={2}
                maxLength={1000}
                onChange={(e) =>
                  setDrafts((prev) =>
                    (prev ?? []).map((d, j) => (j === i ? { ...d, explanation: e.target.value } : d)),
                  )
                }
                className="mt-1 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
              />
              {draft.sourceQuote !== '' && (
                <p className="mt-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">引文：“{draft.sourceQuote}”</p>
              )}
            </div>
          ))}
          {drafts !== null && (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="primary"
                disabled={save.isPending || selectedCount === 0}
                onClick={() => save.mutate()}
              >
                {save.isPending ? '保存中…' : `保存所选（${selectedCount}）`}
              </Button>
              <Button size="sm" variant="ghost" onClick={cancel}>
                取消
              </Button>
            </div>
          )}
          {savedResults !== null && (
            <p role="status" className="text-xs text-[var(--lumi-text-secondary)]" aria-live="polite">
              {savedResults.map((r) => `${r.concept}：${r.status === 'created' ? '已保存' : r.status === 'skipped' ? '已存在，跳过' : '失败'}`).join('；')}
            </p>
          )}
          {save.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">保存失败，请稍后重试。</p>
          )}
        </div>
      )}
    </section>
  )
}
