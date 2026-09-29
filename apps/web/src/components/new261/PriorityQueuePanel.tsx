/** NEW-266 分段翻译优先队列 — 章节先行/选段先行：把段落索引登记成队列，
 * 显式执行时只翻「队列 ∩ 提交块集合」；缓存语义沿用生成路径 —— 已有
 * 结果/不翻译/修订段零 provider 调用（不重复收费）。执行后队列原样保留。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  clearPriorityQueue,
  getPriorityQueue,
  putPriorityQueue,
  removePriorityQueueItem,
  runPriorityQueue,
  type QueueRunResult,
} from '../../api/new261'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { NoticeLine } from './parts'

export function PriorityQueuePanel({
  entryRef,
  blocks,
}: {
  entryRef: string
  blocks: Array<{ index: number; text: string }> | null
}) {
  const queryClient = useQueryClient()
  const queueQuery = useQuery({
    queryKey: ['new266-priority-queue', entryRef],
    queryFn: ({ signal }) => getPriorityQueue(entryRef, signal),
  })
  const [picked, setPicked] = useState<number[]>([])
  const [result, setResult] = useState<QueueRunResult | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['new266-priority-queue', entryRef] })
    void queryClient.invalidateQueries({ queryKey: ['translation-segments', entryRef] })
  }

  const putMutation = useMutation({
    mutationFn: () => putPriorityQueue(entryRef, picked),
    onSuccess: (data) => {
      setPicked([])
      setNotice(`已按顺序登记 ${data.queue.length} 段（重复索引保持原位）。`)
      void queryClient.invalidateQueries({ queryKey: ['new266-priority-queue', entryRef] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })
  const runMutation = useMutation({
    mutationFn: () => runPriorityQueue(entryRef, blocks ?? []),
    onSuccess: (runResult) => {
      setResult(runResult)
      setNotice(null)
      invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '执行失败'),
  })
  const removeMutation = useMutation({
    mutationFn: (index: number) => removePriorityQueueItem(entryRef, index),
    onSuccess: () => invalidate(),
    onError: (error) => setNotice(error instanceof Error ? error.message : '移出失败'),
  })
  const clearMutation = useMutation({
    mutationFn: () => clearPriorityQueue(entryRef),
    onSuccess: (data) => {
      setNotice(`已清空队列（移除 ${data.removed} 条）。`)
      void queryClient.invalidateQueries({ queryKey: ['new266-priority-queue', entryRef] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '清空失败'),
  })

  const queue = queueQuery.data?.queue ?? []
  const queuedIndexes = new Set(queue.map((entry) => entry.index))

  return (
    <div className="flex flex-col gap-2">
      {blocks !== null && blocks.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {blocks.map((block) => {
            const active = picked.includes(block.index)
            return (
              <button
                key={block.index}
                type="button"
                aria-pressed={active}
                aria-label={`选择第 ${block.index + 1} 段${queuedIndexes.has(block.index) ? '（已在队列）' : ''}`}
                onClick={() =>
                  setPicked((prev) =>
                    prev.includes(block.index) ? prev.filter((index) => index !== block.index) : [...prev, block.index],
                  )
                }
                className={`rounded-[var(--lumi-radius-full)] px-2 py-1 text-xs ${
                  active
                    ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                    : 'bg-[var(--lumi-surface-hover)] text-[var(--lumi-text-secondary)]'
                }`}
              >
                {block.index + 1}
                {queuedIndexes.has(block.index) ? '·' : ''}
              </button>
            )
          })}
        </div>
      ) : (
        <EmptyState title="还没有正文块" description="切到双语/仅译文并等正文分段后，再挑优先段。" />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={picked.length === 0 || putMutation.isPending}
          onClick={() => putMutation.mutate()}
        >
          按此顺序加入队列（{picked.length} 段）
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={queue.length === 0 || blocks === null || blocks.length === 0 || runMutation.isPending}
          onClick={() => runMutation.mutate()}
        >
          执行队列
        </Button>
        {queue.length > 0 && (
          <Button size="sm" variant="ghost" disabled={clearMutation.isPending} onClick={() => clearMutation.mutate()}>
            清空
          </Button>
        )}
      </div>

      {queue.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          {queue.map((entry, order) => (
            <li key={entry.index} className="flex items-center gap-2">
              <span>
                {order + 1}. 第 {entry.index + 1} 段（登记于 {entry.addedAt}）
              </span>
              <Button size="sm" variant="ghost" disabled={removeMutation.isPending} onClick={() => removeMutation.mutate(entry.index)}>
                移出
              </Button>
            </li>
          ))}
        </ul>
      )}

      {result !== null && (
        <div className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          <p>
            发送 {result.queuedCount} 段；成功 {result.queuedStates.filter((state) => state.status === 'success').length} 段
            （其中缓存命中 {result.queuedStates.filter((state) => state.status === 'success' && state.cached).length} 段零调用）。
          </p>
          {result.skippedMissingText.length > 0 && (
            <p className="text-[var(--lumi-text-tertiary)]">
              队列中 {result.skippedMissingText.length} 段在当前正文里找不到文本，未发送（如实上报，不臆造）。
            </p>
          )}
        </div>
      )}
      {notice !== null && <NoticeLine tone={notice.includes('失败') ? 'error' : 'success'}>{notice}</NoticeLine>}
    </div>
  )
}
