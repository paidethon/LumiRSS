/** NEW-223 队列工作量预览 section —— 本人速度校正 + 估算 + 压缩范围建议。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  estimateWorkload,
  getReadingSpeed,
  setReadingSpeed,
  suggestCompressions,
  type CompressionOption,
  type EstimateView,
} from './api'
import { Button } from '../ui/Button'
import { Chip, ErrorNote, SectionEmpty, SectionShell, useTodayItems } from './parts'

export function WorkloadSection() {
  const qc = useQueryClient()
  const { items } = useTodayItems()
  const [speedInput, setSpeedInput] = useState('')
  const [estimate, setEstimate] = useState<EstimateView | null>(null)
  const [options, setOptions] = useState<CompressionOption[]>([])
  const [compressionNote, setCompressionNote] = useState('')
  const [error, setError] = useState<unknown>(null)

  const speedQuery = useQuery({
    queryKey: ['new2xx', 'speed'],
    queryFn: ({ signal }) => getReadingSpeed(signal),
  })

  const saveSpeed = useMutation({
    mutationFn: () => setReadingSpeed(Number(speedInput)),
    onSuccess: () => {
      setSpeedInput('')
      void qc.invalidateQueries({ queryKey: ['new2xx', 'speed'] })
    },
    onError: setError,
  })

  const runEstimate = useMutation({
    mutationFn: () => estimateWorkload(items.map((item) => item.itemRef)),
    onSuccess: (view) => {
      setEstimate(view)
      setError(null)
    },
    onError: setError,
  })
  const runCompressions = useMutation({
    mutationFn: () => suggestCompressions(items.map((item) => item.itemRef)),
    onSuccess: (view) => {
      setOptions(view.options)
      setCompressionNote(view.note)
    },
    onError: setError,
  })

  const speed = speedQuery.data

  return (
    <SectionShell
      title="队列工作量预览"
      hint="按你的阅读速度估算队列时长——估算是数量级参考，不是精确耗时。"
    >
      <ErrorNote error={error} />
      <div className="flex items-center gap-2 text-xs">
        {speed ? (
          <span className="text-[var(--lumi-text-secondary)]">
            当前速度：{speed.charsPerMinute} 字符/分钟
            {speed.customized ? '（已校正）' : '（缺省粗估，建议校正）'}
          </span>
        ) : null}
        <input
          value={speedInput}
          onChange={(event) => setSpeedInput(event.target.value.replace(/\D/g, ''))}
          placeholder="校正为…"
          aria-label="校正阅读速度（字符每分钟）"
          className="min-h-7 w-24 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-xs"
        />
        <Button
          size="sm"
          disabled={!speedInput || saveSpeed.isPending}
          onClick={() => saveSpeed.mutate()}
        >
          保存速度
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <Button size="sm" disabled={items.length === 0 || runEstimate.isPending} onClick={() => runEstimate.mutate()}>
          估算今日队列
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={items.length === 0 || runCompressions.isPending}
          onClick={() => runCompressions.mutate()}
        >
          压缩范围建议
        </Button>
      </div>

      {items.length === 0 ? <SectionEmpty message="今天队列还没有条目可估算。" /> : null}

      {estimate ? (
        <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-separator)] p-2 text-xs">
          <p className="font-medium text-[var(--lumi-text-primary)]">
            合计约 {estimate.totalKnownMinutes} 分钟
            <Chip>按 {estimate.charsPerMinute} 字符/分钟</Chip>
            {estimate.unknownCount > 0 ? (
              <Chip tone="warn">{estimate.unknownCount} 篇无法估（无文本）</Chip>
            ) : null}
          </p>
          <p className="mt-1 text-[var(--lumi-text-tertiary)]">
            {estimate.basis}；{estimate.note}
          </p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {estimate.items.map((item) => (
              <li key={item.itemRef} className="flex items-center justify-between gap-2">
                <span className="truncate text-[var(--lumi-text-secondary)]">
                  {item.title ?? item.itemRef}
                </span>
                <span className="shrink-0 text-[var(--lumi-text-tertiary)]">
                  {item.minutes === null ? '未知' : `约 ${item.minutes} 分钟`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {options.length > 0 ? (
        <div className="flex flex-col gap-1 text-xs">
          <p className="text-[var(--lumi-text-tertiary)]">{compressionNote}</p>
          {options.map((option) => (
            <div
              key={option.key}
              className="flex items-center justify-between gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-separator)] px-2 py-1.5"
            >
              <span className="text-[var(--lumi-text-primary)]">{option.label}</span>
              <span className="text-[var(--lumi-text-secondary)]">
                {option.refs.length} 篇 · 约 {option.estimatedMinutes} 分钟
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </SectionShell>
  )
}
