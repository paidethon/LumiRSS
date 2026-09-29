/** NEW-222 队列依赖关系 section —— 先读项提示（met/unmet + basis）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { addQueuePrereq, deleteQueuePrereq, getItemPrereqs } from './api'
import { Button } from '../ui/Button'
import { Chip, ErrorNote, ItemPicker, SectionShell, useTodayItems } from './parts'

const BASIS_LABEL: Record<string, string> = {
  read: '已读',
  'queue-done': '今日队列已完成',
  'slot-done': '时段已完成',
  unread: '未读',
  unknown: '无状态',
}

export function PrereqSection() {
  const qc = useQueryClient()
  const { items } = useTodayItems()
  const [target, setTarget] = useState('')
  const [prereq, setPrereq] = useState('')
  const [error, setError] = useState<unknown>(null)

  const viewQuery = useQuery({
    queryKey: ['new2xx', 'prereqs', target],
    queryFn: ({ signal }) => getItemPrereqs(target, signal),
    enabled: target !== '',
  })

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new2xx', 'prereqs'] })

  const addMutation = useMutation({
    mutationFn: () => addQueuePrereq(target, prereq),
    onSuccess: () => {
      setPrereq('')
      invalidate()
    },
    onError: setError,
  })
  const deleteMutation = useMutation({
    mutationFn: (prereqId: string) => deleteQueuePrereq(prereqId),
    onSuccess: invalidate,
    onError: setError,
  })

  const view = viewQuery.data

  return (
    <SectionShell
      title="队列依赖关系"
      hint="为材料设置先读项；未满足的前置只是提示，绝不阻止你跳读。"
    >
      <ErrorNote error={error} />
      <ItemPicker items={items} value={target} onChange={setTarget} label="材料" />
      {target ? (
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <ItemPicker items={items} value={prereq} onChange={setPrereq} label="先读项" />
          </div>
          <Button
            size="sm"
            disabled={!prereq || addMutation.isPending}
            onClick={() => addMutation.mutate()}
          >
            设置先读
          </Button>
        </div>
      ) : null}

      {view ? (
        <div className="flex flex-col gap-1.5 text-xs">
          {view.prereqs.length === 0 ? (
            <p className="text-[var(--lumi-text-tertiary)]">这条材料还没有先读项。</p>
          ) : (
            view.prereqs.map((entry) => (
              <div
                key={entry.id}
                className="flex items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-separator)] px-2 py-1.5"
              >
                <Chip tone={entry.met ? 'neutral' : 'warn'}>
                  {entry.met ? '已满足' : '未满足'}
                </Chip>
                <span className="text-[var(--lumi-text-primary)]">
                  {entry.title ?? entry.prereqRef}
                </span>
                <Chip>{BASIS_LABEL[entry.basis] ?? entry.basis}</Chip>
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  onClick={() => deleteMutation.mutate(entry.id)}
                >
                  移除
                </Button>
              </div>
            ))
          )}
          {view.unmetCount > 0 ? (
            <p className="text-[var(--lumi-text-tertiary)]">
              {view.unmetCount} 条前置未满足——仅供你安排顺序，不影响直接打开。
            </p>
          ) : null}
        </div>
      ) : null}
    </SectionShell>
  )
}
