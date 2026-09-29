/** NEW-226 队列容量上限 section —— 设置容量 / 待确认区裁决（替换/暂不加入）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  dismissCandidate,
  getQueueCapacity,
  listCapacityPending,
  offerQueueItem,
  replaceWithCandidate,
  setQueueCapacity,
} from './api'
import { getTodayQueue } from '../../api/client'
import { Button } from '../ui/Button'
import { Chip, ErrorNote, ItemPicker, SectionShell, useTodayItems } from './parts'

export function CapacitySection() {
  const qc = useQueryClient()
  const { items } = useTodayItems()
  const [capacityInput, setCapacityInput] = useState('')
  const [pickRef, setPickRef] = useState('')
  const [victimId, setVictimId] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [status, setStatus] = useState<string | null>(null)

  const settingsQuery = useQuery({
    queryKey: ['new2xx', 'capacity'],
    queryFn: ({ signal }) => getQueueCapacity(signal),
  })
  const pendingQuery = useQuery({
    queryKey: ['new2xx', 'capacity-pending'],
    queryFn: ({ signal }) => listCapacityPending(signal),
  })
  const queueQuery = useQuery({
    queryKey: ['queue', 'today'],
    queryFn: ({ signal }) => getTodayQueue(signal),
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['new2xx', 'capacity'] })
    void qc.invalidateQueries({ queryKey: ['new2xx', 'capacity-pending'] })
    void qc.invalidateQueries({ queryKey: ['queue', 'today'] })
  }

  const saveMutation = useMutation({
    mutationFn: () => setQueueCapacity(Number(capacityInput), true),
    onSuccess: () => {
      setCapacityInput('')
      invalidate()
    },
    onError: setError,
  })
  const offerMutation = useMutation({
    mutationFn: () => offerQueueItem(pickRef),
    onSuccess: (result) => {
      setPickRef('')
      setStatus(
        result.outcome === 'overflow'
          ? '队列已满：候选已进待确认区，等你裁决。'
          : `已加入队列（${result.outcome}）。`,
      )
      invalidate()
    },
    onError: setError,
  })
  const replaceMutation = useMutation({
    mutationFn: ({ candidateId }: { candidateId: string }) =>
      replaceWithCandidate(candidateId, victimId),
    onSuccess: () => {
      setVictimId('')
      invalidate()
    },
    onError: setError,
  })
  const dismissMutation = useMutation({
    mutationFn: (candidateId: string) => dismissCandidate(candidateId),
    onSuccess: invalidate,
    onError: setError,
  })

  const settings = settingsQuery.data
  const pending = pendingQuery.data
  const queueItems = (queueQuery.data?.items ?? []).filter(
    (item) => item.status === 'pending',
  )

  return (
    <SectionShell
      title="队列容量上限"
      hint="给今日队列设容量；满员时新候选进待确认区——替换谁、还是暂不加入，由你决定。"
    >
      <ErrorNote error={error} />
      {status ? (
        <p role="status" className="text-xs text-[var(--lumi-success)]">
          {status}
        </p>
      ) : null}
      <div className="flex items-center gap-2 text-xs">
        <span className="text-[var(--lumi-text-secondary)]">
          {settings
            ? settings.capacity !== null
              ? `当前容量：${settings.capacity}${settings.enabled ? '' : '（未启用）'} · 队列现有 ${pending?.queueCount ?? 0} 条`
              : settings.note
            : null}
        </span>
        <input
          value={capacityInput}
          onChange={(event) => setCapacityInput(event.target.value.replace(/\D/g, ''))}
          placeholder="容量…"
          aria-label="队列容量（条）"
          className="min-h-7 w-20 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-xs"
        />
        <Button
          size="sm"
          disabled={!capacityInput || saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          保存容量
        </Button>
      </div>

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <ItemPicker items={items} value={pickRef} onChange={setPickRef} label="尝试加入" />
        </div>
        <Button size="sm" disabled={!pickRef || offerMutation.isPending} onClick={() => offerMutation.mutate()}>
          加入（守门）
        </Button>
      </div>

      {pending && pending.items.length > 0 ? (
        <div className="flex flex-col gap-1.5 text-xs">
          <p className="font-medium text-[var(--lumi-text-primary)]">待确认区</p>
          {pending.items.map((candidate) => (
            <div
              key={candidate.id}
              className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-separator)] px-2 py-1.5"
            >
              <Chip tone="warn">待裁决</Chip>
              <span className="text-[var(--lumi-text-primary)]">
                {candidate.title ?? candidate.itemRef}
              </span>
              <select
                aria-label={`替换 ${candidate.title ?? candidate.itemRef} 时移除谁`}
                value={victimId}
                onChange={(event) => setVictimId(event.target.value)}
                className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-1 text-xs"
              >
                <option value="">替换时移除…</option>
                {queueItems.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title ?? item.itemRef}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="ghost"
                disabled={!victimId || replaceMutation.isPending}
                onClick={() => replaceMutation.mutate({ candidateId: candidate.id })}
              >
                替换
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => dismissMutation.mutate(candidate.id)}
              >
                暂不加入
              </Button>
            </div>
          ))}
        </div>
      ) : null}
    </SectionShell>
  )
}
