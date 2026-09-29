/** NEW-242 来源时间轴 — 发表 / 接收 / 更新 / 个人保存四类时间，
 * 每项说明时间来自哪里；个人备注逐类可写（覆盖式）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  getSourceTimeline,
  listTimelineAnnotations,
  putTimelineAnnotation,
} from '../../api/new241'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

const KIND_LABELS: Record<string, string> = {
  published: '发表',
  received: '接收',
  updated: '更新',
  saved: '个人保存',
}

export function SourceTimelinePanel({ entryRef }: { entryRef: string }) {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState('published')
  const [note, setNote] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const timeline = useQuery({
    queryKey: ['new242-source-timeline', entryRef],
    queryFn: ({ signal }) => getSourceTimeline(entryRef, signal),
  })
  const annotations = useQuery({
    queryKey: ['new242-timeline-annotations', entryRef],
    queryFn: ({ signal }) => listTimelineAnnotations(entryRef, signal),
  })

  const putMutation = useMutation({
    mutationFn: () => putTimelineAnnotation(entryRef, kind, note),
    onSuccess: async () => {
      setNotice('备注已保存。')
      setNote('')
      await queryClient.invalidateQueries({ queryKey: ['new242-timeline-annotations', entryRef] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '备注保存失败'),
  })

  return (
    <section
      aria-label="来源时间轴（NEW-242）"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">来源时间轴</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-242</span>
      </div>

      {timeline.isPending && <Skeleton className="h-16 w-full" />}
      {timeline.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">
          时间轴加载失败。{timeline.error instanceof Error ? timeline.error.message : ''}
        </div>
      )}
      {timeline.data && (
        <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          {timeline.data.items.map((item) => (
            <li key={item.kind} className="flex flex-col gap-0.5">
              <span className="text-[var(--lumi-text-primary)]">
                {KIND_LABELS[item.kind] ?? item.kind}：
                {item.available && item.time !== null ? item.time : '不可用'}
              </span>
              <span className="text-[var(--lumi-text-tertiary)]">来源：{item.source}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-1 border-t border-[var(--lumi-border)] pt-2">
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-[var(--lumi-text-secondary)]">
            备注类型
            <select
              aria-label="备注时间类型"
              value={kind}
              onChange={(event) => setKind(event.target.value)}
              className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
            >
              {Object.entries(KIND_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <textarea
          aria-label="时间备注内容"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="例如：这个更新时间来自 feed 的 atom:updated 字段…"
          rows={2}
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          disabled={note.trim() === '' || putMutation.isPending}
          onClick={() => putMutation.mutate()}
        >
          保存备注
        </Button>
      </div>

      {annotations.data && annotations.data.items.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          {annotations.data.items.map((item) => (
            <li key={`${item.kind}-${item.createdAt}`}>
              {KIND_LABELS[item.kind] ?? item.kind}：{item.note}
            </li>
          ))}
        </ul>
      )}

      {timeline.data && !timeline.data.projectionKnown && (
        <EmptyState title="文章投影缺失" description="本库中没有这篇文章的记录，时间轴只显示不可用项。" />
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}
    </section>
  )
}
