/** SimilarTitleCandidatesPanel — NEW-362 相似标题候选审阅。
 *
 * 候选带可解释相似度（score/共有二元组/片段样例）；「加入重复组 /
 * 标为转载」都是显式确认动作（BFF 唯一写 item_relations 的路径）。
 * 已在组中的候选如实标注，绝不自动归组。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CopyPlus } from 'lucide-react'
import {
  confirmSimilarTitle,
  fetchSimilarTitleCandidates,
} from '../../api/new361'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'

export function SimilarTitleCandidatesPanel({ entryRef }: { entryRef: string }) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const candidates = useQuery({
    queryKey: ['new362', 'similar-titles', entryRef],
    queryFn: () => fetchSimilarTitleCandidates(entryRef),
    enabled: open && entryRef !== '',
  })
  const confirm = useMutation({
    mutationFn: (input: { bRef: string; relation: 'duplicate' | 'reprint' }) =>
      confirmSimilarTitle(entryRef, input.bRef, input.relation),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['new362', 'similar-titles', entryRef] })
    },
  })

  return (
    <section
      data-testid="n362-similar-titles"
      aria-label="相似标题候选审阅"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <button
        type="button"
        aria-expanded={open}
        data-testid="n362-toggle"
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-7 items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-accent-text)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <CopyPlus aria-hidden className="size-3.5" />
        相似标题候选审阅
      </button>
      {open && (
        <>
          {candidates.isPending && (
            <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">
              扫描中…
            </p>
          )}
          {candidates.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              候选扫描失败：{candidates.error instanceof Error ? candidates.error.message : '请稍后重试。'}
            </p>
          )}
          {candidates.data && candidates.data.candidates.length === 0 && (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              本账户索引内没有相似标题候选。
            </p>
          )}
          {candidates.data?.candidates.map((candidate) => (
            <article
              key={candidate.entryRef}
              data-testid="n362-candidate"
              className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs"
            >
              <p className="font-medium text-[var(--lumi-text-primary)]">{candidate.title}</p>
              <p className="text-[var(--lumi-text-tertiary)]">
                相似度 {candidate.score}%：共有 {candidate.sharedBigrams} 组字符片段（
                {candidate.sharedSample}）
                {candidate.sameSource ? ' · 同一来源' : ''}
              </p>
              {candidate.inGroup !== null ? (
                <p className="text-[var(--lumi-text-secondary)]" data-testid="n362-in-group">
                  已在{candidate.inGroup === 'duplicate' ? '重复' : '转载'}关系中，不重复操作。
                </p>
              ) : (
                <div className="flex gap-1.5">
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={confirm.isPending}
                    onClick={() => confirm.mutate({ bRef: candidate.entryRef, relation: 'duplicate' })}
                  >
                    确认加入重复组
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={confirm.isPending}
                    onClick={() => confirm.mutate({ bRef: candidate.entryRef, relation: 'reprint' })}
                  >
                    确认为转载
                  </Button>
                </div>
              )}
              {confirm.isError && (
                <p role="alert" className={cx('text-[var(--lumi-danger)]')}>
                  确认失败：{confirm.error instanceof Error ? confirm.error.message : '请稍后重试。'}
                </p>
              )}
            </article>
          ))}
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            候选只列出、绝不自动入组；确认是唯一写入路径。
          </p>
        </>
      )}
    </section>
  )
}
