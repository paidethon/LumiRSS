/** NEW-224 阅读预约清单 section —— 一次性预约（应用内）/ 改期 / 取消。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  cancelReminder,
  completeReminder,
  createReminder,
  listReminders,
  rescheduleReminder,
  type ReadingReminder,
} from './api'
import { Button } from '../ui/Button'
import { Chip, ErrorNote, ItemPicker, SectionEmpty, SectionShell, useTodayItems } from './parts'

function toLocalInputValue(deltaMinutes: number): string {
  const moment = new Date(Date.now() + deltaMinutes * 60_000)
  moment.setSeconds(0, 0)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}T${pad(moment.getHours())}:${pad(moment.getMinutes())}`
}

export function ReminderSection() {
  const qc = useQueryClient()
  const { items } = useTodayItems()
  const [ref, setRef] = useState('')
  const [when, setWhen] = useState(toLocalInputValue(60))
  const [note, setNote] = useState('')
  const [error, setError] = useState<unknown>(null)

  const listQuery = useQuery({
    queryKey: ['new2xx', 'reminders'],
    queryFn: ({ signal }) => listReminders(signal),
  })

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new2xx', 'reminders'] })

  const createMutation = useMutation({
    mutationFn: () =>
      createReminder(ref, new Date(when).toISOString(), note.trim() || undefined),
    onSuccess: () => {
      setNote('')
      invalidate()
    },
    onError: setError,
  })
  const rescheduleMutation = useMutation({
    mutationFn: (id: string) =>
      rescheduleReminder(id, new Date(toLocalInputValue(30)).toISOString()),
    onSuccess: invalidate,
    onError: setError,
  })
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelReminder(id),
    onSuccess: invalidate,
    onError: setError,
  })
  const completeMutation = useMutation({
    mutationFn: (id: string) => completeReminder(id),
    onSuccess: invalidate,
    onError: setError,
  })

  const rows = listQuery.data?.items ?? []
  const active = rows.filter((row: ReadingReminder) => row.status === 'active')

  return (
    <SectionShell
      title="阅读预约清单"
      hint="一次性预约，到时只在应用内提示（没有推送/邮件）；可改期或取消。"
    >
      <ErrorNote error={error} />
      <ItemPicker items={items} value={ref} onChange={setRef} label="文章" />
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <label className="flex flex-col gap-0.5 text-[var(--lumi-text-secondary)]">
          时间
          <input
            type="datetime-local"
            value={when}
            onChange={(event) => setWhen(event.target.value)}
            className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-xs"
          />
        </label>
        <label className="flex flex-1 flex-col gap-0.5 text-[var(--lumi-text-secondary)]">
          备注
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="（可选）"
            className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-xs"
          />
        </label>
        <Button size="sm" disabled={!ref || !when || createMutation.isPending} onClick={() => createMutation.mutate()}>
          预约
        </Button>
      </div>

      {active.length === 0 ? (
        <SectionEmpty message="没有进行中的预约。" />
      ) : (
        <ul className="flex flex-col gap-1.5">
          {active.map((row) => (
            <li
              key={row.id}
              className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-separator)] px-2 py-1.5 text-xs"
            >
              {row.due ? <Chip tone="warn">到时了</Chip> : <Chip>{row.remindAt}</Chip>}
              <span className="text-[var(--lumi-text-primary)]">
                {row.title ?? row.itemRef}
              </span>
              {row.note ? (
                <span className="text-[var(--lumi-text-tertiary)]">{row.note}</span>
              ) : null}
              <div className="ml-auto flex items-center gap-1">
                <Button size="sm" variant="ghost" onClick={() => rescheduleMutation.mutate(row.id)}>
                  +30 分钟
                </Button>
                <Button size="sm" variant="ghost" onClick={() => completeMutation.mutate(row.id)}>
                  已读
                </Button>
                <Button size="sm" variant="ghost" onClick={() => cancelMutation.mutate(row.id)}>
                  取消
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </SectionShell>
  )
}
