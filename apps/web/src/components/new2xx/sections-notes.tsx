/** NEW-228 阅读中断便签 section —— 下次从哪继续 + 在想什么，读完归档。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import {
  archiveNote,
  getActiveNote,
  listActiveNotes,
  upsertNote,
  type InterruptionNote,
} from './api'
import { Button } from '../ui/Button'
import { Chip, ErrorNote, ItemPicker, SectionShell, useTodayItems } from './parts'

export function NotesSection() {
  const qc = useQueryClient()
  const { items } = useTodayItems()
  const [ref, setRef] = useState('')
  const [thought, setThought] = useState('')
  const [hint, setHint] = useState('')
  const [error, setError] = useState<unknown>(null)

  const noteQuery = useQuery({
    queryKey: ['new2xx', 'note', ref],
    queryFn: ({ signal }) => getActiveNote(ref, signal),
    enabled: ref !== '',
  })
  const allQuery = useQuery({
    queryKey: ['new2xx', 'notes-all'],
    queryFn: ({ signal }) => listActiveNotes(signal),
  })

  // 返回文章时把已有便签回填到表单（「返回文章时显示这条便签」）。
  useEffect(() => {
    const existing: InterruptionNote | null = noteQuery.data?.note ?? null
    setThought(existing?.thought ?? '')
    setHint(existing?.resumeHint ?? '')
  }, [noteQuery.data])

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['new2xx', 'note'] })
    void qc.invalidateQueries({ queryKey: ['new2xx', 'notes-all'] })
  }

  const saveMutation = useMutation({
    mutationFn: () => upsertNote(ref, thought, hint.trim() || undefined),
    onSuccess: invalidate,
    onError: setError,
  })
  const archiveMutation = useMutation({
    mutationFn: () => archiveNote(ref),
    onSuccess: () => {
      setThought('')
      setHint('')
      invalidate()
    },
    onError: setError,
  })

  const activeNote = noteQuery.data?.note ?? null
  const others = (allQuery.data?.items ?? []).filter((note) => note.itemRef !== ref)

  return (
    <SectionShell
      title="阅读中断便签"
      hint="离开前记下「下次从哪里继续、正在想什么」；返回文章时这里会显示；读完点归档。"
    >
      <ErrorNote error={error} />
      <ItemPicker items={items} value={ref} onChange={setRef} label="文章" />
      {ref ? (
        <div className="flex flex-col gap-1.5 text-xs">
          {activeNote ? (
            <p className="flex items-center gap-2 text-[var(--lumi-text-secondary)]">
              <Chip tone="accent">有未完成便签</Chip>
              记于 {activeNote.updatedAt?.slice(0, 16).replace('T', ' ')}
            </p>
          ) : null}
          <label className="flex flex-col gap-0.5 text-[var(--lumi-text-secondary)]">
            正在想什么
            <textarea
              value={thought}
              onChange={(event) => setThought(event.target.value)}
              rows={3}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-1 text-xs"
            />
          </label>
          <label className="flex flex-col gap-0.5 text-[var(--lumi-text-secondary)]">
            下次从哪里继续
            <input
              value={hint}
              onChange={(event) => setHint(event.target.value)}
              placeholder="（可选）如：第 4 节末尾"
              className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-xs"
            />
          </label>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={!thought.trim() || saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              保存便签
            </Button>
            {activeNote ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={archiveMutation.isPending}
                onClick={() => archiveMutation.mutate()}
              >
                读完，归档
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {others.length > 0 ? (
        <div className="flex flex-col gap-1 text-xs">
          <p className="font-medium text-[var(--lumi-text-primary)]">读到一半的</p>
          {others.map((note) => (
            <p key={note.id} className="truncate text-[var(--lumi-text-secondary)]">
              {note.title ?? note.itemRef}：{note.thought}
            </p>
          ))}
        </div>
      ) : null}
    </SectionShell>
  )
}
