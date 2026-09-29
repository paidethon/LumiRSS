/** HitFeedbackControls — NEW-370 搜索结果评注 + 显式排序方案。
 *
 * - 行内控件：对某个命中标记「对此问题有用 / 无关」并写原因（可重标
 *   覆盖）；反馈只入库，绝不改变默认搜索排序；
 * - RankingSchemeToggle：「有用优先」排序方案默认关闭——只有本人
 *   显式启用后，重排预览才生效；停用即回到默认（诚实空表）。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownUp, ThumbsDown, ThumbsUp } from 'lucide-react'
import {
  fetchHitFeedback,
  fetchRankingScheme,
  fetchReranked,
  recordHitFeedback,
  setRankingScheme,
} from '../../api/new361'
import { Button } from '../ui/Button'

export function HitFeedbackControls({
  query,
  entryRef,
}: {
  query: string
  entryRef: string
}) {
  const queryClient = useQueryClient()
  const [reasonOpen, setReasonOpen] = useState(false)
  const [reason, setReason] = useState('')
  const feedback = useMutation({
    mutationFn: (verdict: 'useful' | 'irrelevant') =>
      recordHitFeedback({ query, entryRef, verdict, reason: reason.trim() || null }),
    onSuccess: () => {
      setReasonOpen(false)
      setReason('')
      void queryClient.invalidateQueries({ queryKey: ['new370', 'feedback', query] })
    },
  })

  return (
    <span
      data-testid="n370-feedback"
      role="group"
      aria-label="对此命中评注"
      className="inline-flex flex-wrap items-center gap-1"
    >
      <button
        type="button"
        data-testid="n370-useful"
        disabled={feedback.isPending}
        aria-label="对此问题有用"
        onClick={() => feedback.mutate('useful')}
        className="inline-flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2 py-0.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <ThumbsUp aria-hidden className="size-3" />
        有用
      </button>
      <button
        type="button"
        data-testid="n370-irrelevant"
        disabled={feedback.isPending}
        aria-label="与此问题无关"
        onClick={() => setReasonOpen((value) => !value)}
        className="inline-flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2 py-0.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <ThumbsDown aria-hidden className="size-3" />
        无关
      </button>
      {reasonOpen && (
        <span className="inline-flex items-center gap-1">
          <label className="sr-only" htmlFor={`n370-reason-${entryRef}`}>
            无关原因
          </label>
          <input
            id={`n370-reason-${entryRef}`}
            data-testid="n370-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="原因（可选）"
            className="h-7 w-40 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={feedback.isPending}
            onClick={() => feedback.mutate('irrelevant')}
          >
            提交
          </Button>
        </span>
      )}
      {feedback.isSuccess && (
        <span role="status" data-testid="n370-saved" className="text-xs text-[var(--lumi-text-tertiary)]">
          已记录（{feedback.data.already ? '覆盖原标记' : '新标记'}；仅你启用的排序方案会用到）。
        </span>
      )}
      {feedback.isError && (
        <span role="alert" className="text-xs text-[var(--lumi-danger)]">
          评注失败：{feedback.error instanceof Error ? feedback.error.message : '请稍后重试。'}
        </span>
      )}
    </span>
  )
}

export function FeedbackSummary({ query }: { query: string }) {
  const feedback = useQuery({
    queryKey: ['new370', 'feedback', query],
    queryFn: () => fetchHitFeedback(query),
    enabled: query.trim() !== '',
  })
  if (feedback.data === undefined || feedback.data.items.length === 0) return null
  return (
    <p data-testid="n370-summary" className="text-xs text-[var(--lumi-text-tertiary)]">
      本查询已评注 {feedback.data.items.length} 条（有用 {feedback.data.counts.useful} · 无关{' '}
      {feedback.data.counts.irrelevant}）。
    </p>
  )
}

export function RankingSchemeToggle({ query }: { query: string }) {
  const queryClient = useQueryClient()
  const scheme = useQuery({
    queryKey: ['new370', 'scheme'],
    queryFn: () => fetchRankingScheme(),
  })
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => setRankingScheme(enabled),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['new370', 'scheme'] })
      void queryClient.invalidateQueries({ queryKey: ['new370', 'reranked', query] })
    },
  })
  const reranked = useQuery({
    queryKey: ['new370', 'reranked', query],
    queryFn: () => fetchReranked(query),
    enabled: query.trim() !== '' && (scheme.data?.enabled ?? false),
  })

  return (
    <section
      data-testid="n370-scheme"
      aria-label="排序方案"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <ArrowDownUp aria-hidden className="size-3.5" />
        排序方案：有用优先（{scheme.data?.enabled ? '已启用' : '默认关闭'}）
      </p>
      <div className="flex gap-1.5">
        <Button
          size="sm"
          variant={scheme.data?.enabled ? 'secondary' : 'primary'}
          data-testid="n370-enable"
          disabled={toggle.isPending || (scheme.data?.enabled ?? false)}
          onClick={() => toggle.mutate(true)}
        >
          显式启用
        </Button>
        <Button
          size="sm"
          variant="ghost"
          data-testid="n370-disable"
          disabled={toggle.isPending || !(scheme.data?.enabled ?? false)}
          onClick={() => toggle.mutate(false)}
        >
          停用
        </Button>
      </div>
      <p className="text-xs text-[var(--lumi-text-tertiary)]">
        {scheme.data?.note ?? '默认关闭：评注绝不自动改变默认搜索排序。'}
      </p>
      {scheme.data?.enabled === true && reranked.data !== undefined && (
        <p data-testid="n370-reranked" className="text-xs text-[var(--lumi-text-secondary)]">
          重排预览：{reranked.data.items.length} 条
          {reranked.data.items.length > 0 &&
            `，置顶 ${reranked.data.items.filter((item) => item.boosted).length} 条你标过「有用」的结果`}
          。
        </p>
      )}
      {toggle.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          方案切换失败：{toggle.error instanceof Error ? toggle.error.message : '请稍后重试。'}
        </p>
      )}
    </section>
  )
}
