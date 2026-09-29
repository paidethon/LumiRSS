/** New219InboxOpsPanel — NEW-219/220 内容整理工作台（InboxPage 挂载）。
 *
 * 两个分区：批量归档（条件预览 → 勾选 → 一次归档 → 收据 → 撤销未被
 * 后续修改的部分）/ 处理记录（每次整理的 from → to + 原因，按日追踪）。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as api from './api'
import { ApiError } from './api'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

type Section = 'archive' | 'journal'

const SECTIONS: { key: Section; label: string }[] = [
  { key: 'archive', label: '批量归档' },
  { key: 'journal', label: '处理记录' },
]

function errText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return String(error)
}

// ---- NEW-219 批量归档 -------------------------------------------------------

function ArchiveSection() {
  const qc = useQueryClient()
  const [days, setDays] = useState('30')
  const [preview, setPreview] = useState<api.ArchivePreview | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [receipt, setReceipt] = useState<api.ArchiveReceipt | null>(null)

  const previewMutation = useMutation({
    mutationFn: () => api.archivePreview(Number(days)),
    onSuccess: (data) => {
      setPreview(data)
      setPicked([])
      setReceipt(null)
    },
  })
  const applyMutation = useMutation({
    mutationFn: () => api.archiveApply(picked),
    onSuccess: (data) => {
      setReceipt(data)
      setPreview(null)
      // 归档改变阅读状态：刷新收件箱列表。
      void qc.invalidateQueries({ queryKey: ['inbox'] })
    },
  })
  const undoMutation = useMutation({
    mutationFn: (batchId: string) => api.archiveUndo(batchId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['inbox'] }),
  })

  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="new219-archive">
      <div className="flex items-end gap-1">
        <label className="flex flex-col">
          归档发布早于（天）
          <input
            aria-label="归档条件：发布早于天数"
            type="number"
            min={1}
            className="w-24 rounded border border-[var(--lumi-border)] px-2 py-1"
            value={days}
            onChange={(event) => setDays(event.target.value)}
          />
        </label>
        <Button
          size="sm"
          disabled={days === '' || previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          生成清单
        </Button>
      </div>
      {previewMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(previewMutation.error)}</p>}
      {preview !== null && (
        <div data-testid="new219-preview">
          <p>
            待归档 {preview.count} 篇（加星恒排除：{preview.effectiveExclusions.join('、')}）
          </p>
          {preview.sample.length === 0 ? (
            <EmptyState title="没有符合条件的文章" />
          ) : (
            <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
              {preview.sample.map((item) => (
                <li key={item.ref}>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={picked.includes(item.ref)}
                      onChange={(event) =>
                        setPicked((prev) =>
                          event.target.checked ? [...prev, item.ref] : prev.filter((r) => r !== item.ref),
                        )
                      }
                    />
                    <span className="truncate">
                      {item.title}（{item.feedTitle}）
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          <Button
            variant="primary"
            size="sm"
            disabled={picked.length === 0 || applyMutation.isPending}
            onClick={() => applyMutation.mutate()}
          >
            归档所选（{picked.length}）
          </Button>
        </div>
      )}
      {applyMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(applyMutation.error)}</p>}
      {receipt !== null && (
        <div className="rounded border border-[var(--lumi-border)] p-2" data-testid="new219-receipt">
          <p>
            本批收据：归档 {receipt.archived.length} 篇
            {receipt.failed.length > 0 ? `，失败 ${receipt.failed.length} 篇` : ''}。
          </p>
          <Button
            size="sm"
            disabled={undoMutation.isPending}
            onClick={() => undoMutation.mutate(receipt.batchId)}
          >
            撤销本批（未被后续修改的部分）
          </Button>
        </div>
      )}
      {undoMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(undoMutation.error)}</p>}
      {undoMutation.isSuccess && (
        <p role="status" data-testid="new219-undo-result">
          已恢复 {undoMutation.data.restored.length} 篇；跳过 {undoMutation.data.skipped.length} 篇（已被后续修改）。
        </p>
      )}
    </div>
  )
}

// ---- NEW-220 处理记录 -------------------------------------------------------

function JournalSection() {
  const qc = useQueryClient()
  const trail = useQuery({ queryKey: ['new220-journal'], queryFn: api.listTriageJournal })
  const [from, setFrom] = useState('收件箱')
  const [to, setTo] = useState('')
  const [reason, setReason] = useState('')
  const [refsText, setRefsText] = useState('')

  const createMutation = useMutation({
    mutationFn: () =>
      api.createTriageEntry({
        fromLocation: from,
        toLocation: to,
        refs: refsText
          .split(/\s+/)
          .map((r) => r.trim())
          .filter((r) => r !== ''),
        reason,
      }),
    onSuccess: () => {
      setTo('')
      setReason('')
      setRefsText('')
      void qc.invalidateQueries({ queryKey: ['new220-journal'] })
    },
  })

  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="new220-journal">
      <div className="flex flex-col gap-1">
        <div className="flex gap-1">
          <input
            aria-label="从哪里"
            className="flex-1 rounded border border-[var(--lumi-border)] px-2 py-1"
            value={from}
            onChange={(event) => setFrom(event.target.value)}
            placeholder="从（如 收件箱）"
          />
          <input
            aria-label="到哪里"
            className="flex-1 rounded border border-[var(--lumi-border)] px-2 py-1"
            value={to}
            onChange={(event) => setTo(event.target.value)}
            placeholder="到（如 工作区:调研）"
          />
        </div>
        <input
          aria-label="涉及引用（空格分隔）"
          className="rounded border border-[var(--lumi-border)] px-2 py-1"
          value={refsText}
          onChange={(event) => setRefsText(event.target.value)}
          placeholder="引用（rss:… / library:…，空格分隔）"
        />
        <input
          aria-label="原因"
          className="rounded border border-[var(--lumi-border)] px-2 py-1"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="为什么整理（可选）"
        />
        <Button
          size="sm"
          variant="primary"
          disabled={from.trim() === '' || to.trim() === '' || refsText.trim() === '' || createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          记录本次整理
        </Button>
        {createMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(createMutation.error)}</p>}
      </div>
      {trail.isLoading ? (
        <Skeleton className="h-24" />
      ) : (trail.data?.count ?? 0) === 0 ? (
        <EmptyState title="还没有整理记录" description="每次整理都会保存从哪里移到哪里与原因。" />
      ) : (
        <div className="flex flex-col gap-2" data-testid="new220-trail">
          {(trail.data?.days ?? []).map((day) => (
            <div key={day.date}>
              <p className="font-medium">{day.date}</p>
              <ul className="list-disc pl-5">
                {day.entries.map((entry) => (
                  <li key={entry.id}>
                    {entry.fromLocation} → {entry.toLocation}（{entry.refs.length} 条
                    {entry.reason ? `；原因：${entry.reason}` : ''}）
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function New219InboxOpsPanel({ onClose }: { onClose: () => void }) {
  const [section, setSection] = useState<Section>('archive')
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3" data-testid="new219-panel">
      <div role="tablist" aria-label="内容整理分区" className="flex flex-wrap gap-1">
        {SECTIONS.map((item) => (
          <button
            key={item.key}
            role="tab"
            aria-selected={section === item.key}
            className={
              section === item.key
                ? 'rounded bg-[var(--lumi-surface-selected)] px-2 py-1 text-sm font-medium'
                : 'rounded px-2 py-1 text-sm text-[var(--lumi-text-secondary)]'
            }
            onClick={() => setSection(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {section === 'archive' && <ArchiveSection />}
        {section === 'journal' && <JournalSection />}
      </div>
      <div className="flex justify-end">
        <Button size="sm" onClick={onClose}>
          关闭
        </Button>
      </div>
    </div>
  )
}
