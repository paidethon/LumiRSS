/** NEW-263 译文质量反馈 — 对具体段标记漏译/误译/格式问题：创建时刻快照
 * 原文/机器/人工三段文本并关联原文；进入本人待复核队列（跨条目），
 * 复核或删除才出队。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { TranslationSegmentState } from '../../api/types'
import {
  createSegmentFeedback,
  listEntryFeedback,
  listFeedbackQueue,
  resolveFeedback,
  deleteFeedback,
  type FeedbackIssueKind,
} from '../../api/new261'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { NoticeLine } from './parts'

const FEEDBACK_KIND_LABELS: Record<FeedbackIssueKind, string> = {
  omission: '漏译',
  mistranslation: '误译',
  format: '格式问题',
}

const NOTE_MAX = 500

export function QualityFeedbackPanel({ entryRef, segments }: { entryRef: string; segments: TranslationSegmentState[] }) {
  const queryClient = useQueryClient()
  const feedbackQuery = useQuery({
    queryKey: ['new263-entry-feedback', entryRef],
    queryFn: ({ signal }) => listEntryFeedback(entryRef, signal),
  })
  const queueQuery = useQuery({
    queryKey: ['new263-feedback-queue'],
    queryFn: ({ signal }) => listFeedbackQueue(signal),
  })
  const [blockIndex, setBlockIndex] = useState<number>(segments[0]?.index ?? 0)
  const [issueKind, setIssueKind] = useState<FeedbackIssueKind>('omission')
  const [note, setNote] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['new263-entry-feedback', entryRef] })
    void queryClient.invalidateQueries({ queryKey: ['new263-feedback-queue'] })
  }

  const createMutation = useMutation({
    mutationFn: () => createSegmentFeedback(entryRef, blockIndex, issueKind, note.trim()),
    onSuccess: (item) => {
      setNotice(`已标记第 ${item.blockIndex + 1} 段为「${FEEDBACK_KIND_LABELS[item.issueKind]}」，进入你的待复核队列。`)
      setNote('')
      invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '标记失败'),
  })
  const resolveMutation = useMutation({
    mutationFn: (id: string) => resolveFeedback(id),
    onSuccess: () => {
      setNotice('已复核完成，移出队列。')
      invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '复核失败'),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteFeedback(id),
    onSuccess: () => {
      setNotice('已删除该反馈。')
      invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '删除失败'),
  })

  const feedback = feedbackQuery.data?.feedback ?? []
  const queue = queueQuery.data?.queue ?? []

  return (
    <div className="flex flex-col gap-2">
      {segments.length === 0 ? (
        <EmptyState title="还没有分段" description="先切到双语/仅译文完成一次翻译，再对具体段落标记质量问题。" />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-[var(--lumi-text-secondary)]">
            段落
            <select
              value={blockIndex}
              onChange={(event) => setBlockIndex(Number(event.target.value))}
              aria-label="标记问题的段落"
              className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
            >
              {segments.map((segment) => (
                <option key={segment.index} value={segment.index}>
                  第 {segment.index + 1} 段
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-[var(--lumi-text-secondary)]">
            问题类型
            <select
              value={issueKind}
              onChange={(event) => setIssueKind(event.target.value as FeedbackIssueKind)}
              aria-label="问题类型"
              className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
            >
              <option value="omission">漏译</option>
              <option value="mistranslation">误译</option>
              <option value="format">格式问题</option>
            </select>
          </label>
          <input
            type="text"
            value={note}
            maxLength={NOTE_MAX}
            onChange={(event) => setNote(event.target.value)}
            placeholder="补充说明（可空）"
            aria-label="问题补充说明"
            className="min-w-40 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            标记问题
          </Button>
        </div>
      )}

      {feedback.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          {feedback.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-surface-hover)] p-1.5">
              <span className="font-medium text-[var(--lumi-text-primary)]">
                第 {item.blockIndex + 1} 段 · {FEEDBACK_KIND_LABELS[item.issueKind]}
              </span>
              <span className="min-w-0 flex-1 truncate">{item.note || '（无说明）'}</span>
              <span>{item.status === 'open' ? '待复核' : '已复核'}</span>
              {item.status === 'open' && (
                <Button size="sm" variant="ghost" disabled={resolveMutation.isPending} onClick={() => resolveMutation.mutate(item.id)}>
                  复核完成
                </Button>
              )}
              <Button size="sm" variant="ghost" disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate(item.id)}>
                删除
              </Button>
            </li>
          ))}
        </ul>
      )}

      {queue.length > 0 && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">本人待复核队列共 {queue.length} 条（跨条目）。</p>
      )}
      {notice !== null && <NoticeLine tone={notice.includes('失败') ? 'error' : 'success'}>{notice}</NoticeLine>}
    </div>
  )
}
