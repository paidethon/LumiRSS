/** NEW-221 分时段阅读队列 section —— 命名时段 / 打开接续 / 显式顺延。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  addQueueSlotItem,
  carryOverQueueSlot,
  createQueueSlot,
  getQueueSlot,
  listQueueSlots,
  openQueueSlot,
  setQueueSlotItemDone,
  type QueueSlotOpen,
} from './api'
import { Button } from '../ui/Button'
import { Chip, ErrorNote, ItemPicker, SectionEmpty, SectionShell, useTodayItems } from './parts'

export function SlotSection() {
  const qc = useQueryClient()
  const { items } = useTodayItems()
  const [name, setName] = useState('')
  const [assignRef, setAssignRef] = useState('')
  const [assignSlot, setAssignSlot] = useState('')
  const [openSlotId, setOpenSlotId] = useState<string | null>(null)
  // 接续视图来自「打开接续」响应（GET detail 不含 resume，诚实分源）
  const [openResume, setOpenResume] = useState<QueueSlotOpen['resume'] | null>(null)
  const [carryTarget, setCarryTarget] = useState<Record<string, string>>({})
  const [error, setError] = useState<unknown>(null)

  const slotsQuery = useQuery({
    queryKey: ['new2xx', 'slots'],
    queryFn: ({ signal }) => listQueueSlots(signal),
  })
  const detailQuery = useQuery({
    queryKey: ['new2xx', 'slot', openSlotId],
    queryFn: ({ signal }) => getQueueSlot(openSlotId ?? '', signal),
    enabled: openSlotId !== null,
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['new2xx', 'slots'] })
    void qc.invalidateQueries({ queryKey: ['new2xx', 'slot'] })
  }

  const createMutation = useMutation({
    mutationFn: () => createQueueSlot(name),
    onSuccess: () => {
      setName('')
      invalidate()
    },
    onError: setError,
  })
  const openMutation = useMutation({
    mutationFn: (slotId: string) => openQueueSlot(slotId),
    onSuccess: (view) => {
      setOpenSlotId(view.id)
      setOpenResume(view.resume)
      invalidate()
    },
    onError: setError,
  })
  const addMutation = useMutation({
    mutationFn: () => addQueueSlotItem(assignSlot, assignRef),
    onSuccess: () => {
      setAssignRef('')
      invalidate()
    },
    onError: setError,
  })
  const doneMutation = useMutation({
    mutationFn: ({ itemId, done }: { itemId: string; done: boolean }) =>
      setQueueSlotItemDone(itemId, done),
    onSuccess: invalidate,
    onError: setError,
  })
  const carryMutation = useMutation({
    mutationFn: ({ slotId, target }: { slotId: string; target: string }) =>
      carryOverQueueSlot(slotId, target),
    onSuccess: invalidate,
    onError: setError,
  })

  const slots = slotsQuery.data?.slots ?? []
  const detail = detailQuery.data

  return (
    <SectionShell
      title="分时段阅读队列"
      hint="把文章分到通勤、午休、晚间等时段；打开时段即可接续。未完成的顺延由你决定（绝不自动）。"
    >
      <ErrorNote error={error} />
      <div className="flex items-center gap-2">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="新时段名（如：通勤）"
          aria-label="新时段名"
          className="min-h-7 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-xs"
        />
        <Button size="sm" disabled={!name.trim() || createMutation.isPending} onClick={() => createMutation.mutate()}>
          创建时段
        </Button>
      </div>

      {slots.length === 0 ? (
        <SectionEmpty message="还没有时段：先创建一个（通勤/午休/晚间…）。" />
      ) : (
        <ul className="flex flex-col gap-1.5">
          {slots.map((slot) => (
            <li
              key={slot.id}
              className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-separator)] px-2.5 py-1.5 text-xs"
            >
              <span className="font-medium text-[var(--lumi-text-primary)]">{slot.name}</span>
              <Chip tone={slot.pendingCount > 0 ? 'accent' : 'neutral'}>
                待读 {slot.pendingCount}
              </Chip>
              {slot.doneCount > 0 ? <Chip>完成 {slot.doneCount}</Chip> : null}
              <div className="ml-auto flex items-center gap-1">
                <Button size="sm" variant="ghost" onClick={() => openMutation.mutate(slot.id)}>
                  打开接续
                </Button>
                {slot.pendingCount > 0 && slots.length > 1 ? (
                  <select
                    aria-label={`顺延 ${slot.name} 到`}
                    value={carryTarget[slot.id] ?? ''}
                    onChange={(event) => {
                      const target = event.target.value
                      setCarryTarget((prev) => ({ ...prev, [slot.id]: target }))
                      if (target) {
                        carryMutation.mutate({ slotId: slot.id, target })
                      }
                    }}
                    className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-1 text-xs"
                  >
                    <option value="">顺延到…</option>
                    {slots
                      .filter((other) => other.id !== slot.id)
                      .map((other) => (
                        <option key={other.id} value={other.id}>
                          {other.name}
                        </option>
                      ))}
                  </select>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}

      {detail ? (
        <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-separator)] p-2 text-xs">
          <p className="font-medium text-[var(--lumi-text-primary)]">
            接续：{detail.name}
            {openResume?.nextTitle ? (
              <span className="ml-2 font-normal text-[var(--lumi-text-secondary)]">
                下一篇：{openResume.nextTitle}
              </span>
            ) : (
              <span className="ml-2 font-normal text-[var(--lumi-text-tertiary)]">没有待读</span>
            )}
          </p>
          <ul className="mt-1 flex flex-col gap-1">
            {detail.items.map((item) => (
              <li key={item.id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={item.status === 'done'}
                  aria-label={`完成 ${item.title ?? item.itemRef}`}
                  onChange={(event) =>
                    doneMutation.mutate({ itemId: item.id, done: event.target.checked })
                  }
                />
                <span
                  className={item.status === 'done' ? 'text-[var(--lumi-text-tertiary)] line-through' : ''}
                >
                  {item.title ?? item.itemRef}
                </span>
                {item.status === 'carried' ? <Chip tone="warn">已顺延</Chip> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <ItemPicker
            items={items}
            value={assignRef}
            onChange={setAssignRef}
            label="分配文章"
          />
        </div>
        <select
          aria-label="目标时段"
          value={assignSlot}
          onChange={(event) => setAssignSlot(event.target.value)}
          className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-1 text-xs"
        >
          <option value="">目标时段…</option>
          {slots.map((slot) => (
            <option key={slot.id} value={slot.id}>
              {slot.name}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          disabled={!assignRef || !assignSlot || addMutation.isPending}
          onClick={() => addMutation.mutate()}
        >
          加入时段
        </Button>
      </div>
    </SectionShell>
  )
}
