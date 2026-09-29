/** ExclusionSuggestionsPanel — NEW-365 搜索排除词建议审批。
 *
 * 从用户标记为「不相关」的结果提取候选词（纯计数）；「确认排除」是
 * 唯一写入路径，确认词由父级并进该查询的 exclude 参数。撤销即删除。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban } from 'lucide-react'
import {
  approveExclusionWord,
  deleteExclusionWord,
  fetchExclusionCandidates,
  fetchExclusionWords,
} from '../../api/new361'
import { Button } from '../ui/Button'

export function ExclusionSuggestionsPanel({
  query,
  markedRefs,
}: {
  query: string
  /** 本页被用户标记「不相关」的 entryRef（空 = 提取不可用，如实说明）。 */
  markedRefs: string[]
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const enabled = open && query.trim() !== '' && markedRefs.length > 0
  const candidates = useQuery({
    queryKey: ['new365', 'candidates', query, markedRefs],
    queryFn: () => fetchExclusionCandidates(query, markedRefs),
    enabled,
  })
  const approved = useQuery({
    queryKey: ['new365', 'words', query],
    queryFn: () => fetchExclusionWords(query),
    enabled: open && query.trim() !== '',
  })
  const approve = useMutation({
    mutationFn: (word: string) => approveExclusionWord(query, word),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['new365', 'words', query] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => deleteExclusionWord(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['new365', 'words', query] })
    },
  })

  return (
    <section
      data-testid="n365-exclusion"
      aria-label="排除词建议审批"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <button
        type="button"
        aria-expanded={open}
        data-testid="n365-toggle"
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-7 items-center gap-1.5 text-left text-xs font-medium text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-accent-text)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <Ban aria-hidden className="size-3.5" />
        排除词建议（{markedRefs.length} 条标记）
      </button>
      {open && markedRefs.length === 0 && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          先把不相关的结果标记出来，才会有候选词（候选只从标记结果提取）。
        </p>
      )}
      {enabled && candidates.isPending && (
        <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">
          提取中…
        </p>
      )}
      {candidates.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          候选提取失败：{candidates.error instanceof Error ? candidates.error.message : '请稍后重试。'}
        </p>
      )}
      {candidates.data && (
        <div role="group" aria-label="候选排除词" className="flex flex-wrap gap-1.5">
          {candidates.data.candidates.map((candidate) => (
            <button
              key={candidate.word}
              type="button"
              data-testid="n365-candidate"
              disabled={approve.isPending}
              onClick={() => approve.mutate(candidate.word)}
              title={`出现在 ${candidate.markedHits} 条标记结果中；点击确认排除`}
              className="min-h-7 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              {candidate.word}
              <span className="ml-1 tabular-nums opacity-70">×{candidate.markedHits}</span>
            </button>
          ))}
          {candidates.data.candidates.length === 0 && (
            <span className="text-xs text-[var(--lumi-text-tertiary)]">标记结果里没有可用候选词。</span>
          )}
        </div>
      )}
      {approved.data !== undefined && approved.data.items.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium text-[var(--lumi-text-secondary)]">
            已确认（并进本查询的排除条件）：
          </p>
          <div role="group" aria-label="已确认排除词" className="flex flex-wrap gap-1.5">
            {approved.data.items.map((item) => (
              <span
                key={item.id}
                data-testid="n365-approved"
                className="flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] px-2.5 py-1 text-xs text-[var(--lumi-accent-text)]"
              >
                {item.word}
                <button
                  type="button"
                  aria-label={`撤销排除词 ${item.word}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(item.id)}
                  className="rounded-full px-1 hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        </div>
      )}
      <p className="text-xs text-[var(--lumi-text-tertiary)]">
        候选绝不自动生效；只有确认后才加入该查询，撤销即失效。
      </p>
      {approve.isError && (
        <Button size="sm" variant="secondary" onClick={() => approve.reset()}>
          确认失败，点击重置
        </Button>
      )}
    </section>
  )
}
