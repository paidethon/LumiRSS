/** NEW-255 事件时间线编辑器 — 事件发生时间 vs 报道时间。
 *
 * eventAt 按用户掌握的精度原文登记；排序视图按可解析日期呈现，解析
 * 不了的行诚实标注「时间未解析」，绝不估位。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { createTimelineEvent, listTimelineEvents, type TimelineEvent } from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ErrorLine, NoticeLine, TextField } from './parts'

function compareEvents(left: TimelineEvent, right: TimelineEvent): number {
  const a = left.eventDateParsed ?? '9999-12-31'
  const b = right.eventDateParsed ?? '9999-12-31'
  return a.localeCompare(b)
}

export function TimelinePanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const [eventAt, setEventAt] = useState('')
  const [reportedAt, setReportedAt] = useState('')
  const [itemRef, setItemRef] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const events = useQuery({
    queryKey: ['new255-timeline', projectId],
    queryFn: ({ signal }) => listTimelineEvents(projectId, signal),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      createTimelineEvent(projectId, {
        title,
        eventAt,
        reportedAt: reportedAt || undefined,
        itemRef: itemRef || undefined,
      }),
    onSuccess: async () => {
      setTitle('')
      setEventAt('')
      setReportedAt('')
      setItemRef('')
      setNotice('事件已登记（时间保留原文精度）。')
      await queryClient.invalidateQueries({ queryKey: ['new255-timeline', projectId] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })

  const sorted = useMemo(() => [...(events.data?.items ?? [])].sort(compareEvents), [events.data])
  return (
    <div data-new255-timeline="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <TextField label="事件标题" value={title} onChange={setTitle} />
        <TextField
          label="事件发生时间（原文精度，如 1997-03-15 或「约 2003 年春」）"
          value={eventAt}
          onChange={setEventAt}
        />
        <TextField label="报道时间（可选，媒体什么时候说的）" value={reportedAt} onChange={setReportedAt} />
        <TextField label="出处 ItemRef（可选）" value={itemRef} onChange={setItemRef} placeholder="rss:… / library:…" />
        <div>
          <Button size="sm" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
            登记事件
          </Button>
        </div>
      </div>
      <NoticeLine notice={notice} />
      <ErrorLine error={events.error} />
      {events.data !== undefined && events.data.unparseableCount > 0 && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          {events.data.unparseableCount} 条时间未解析（排在末尾，不估位）。
        </p>
      )}
      {events.data !== undefined && sorted.length === 0 && (
        <EmptyState title="时间线为空" description="从自己的材料里登记事件时间与出处。" />
      )}
      <ol className="flex flex-col gap-2">
        {sorted.map((event) => (
          <li
            key={event.id}
            data-new255-event={event.id}
            className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-[var(--lumi-text-primary)]">{event.title}</span>
              {event.reportedDaysAfter !== null && (
                <span
                  className="text-xs text-[var(--lumi-text-tertiary)]"
                  data-new255-gap={event.reportedDaysAfter}
                >
                  报道晚 {event.reportedDaysAfter} 天
                </span>
              )}
            </div>
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              发生：{event.eventAt}
              {event.eventDateParsed === null && '（时间未解析）'}
              {event.reportedAt !== null && ` · 报道：${event.reportedAt}`}
            </p>
          </li>
        ))}
      </ol>
    </div>
  )
}
