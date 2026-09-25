/** BacklogPanel — F024 积压整理助手（EntryList 工具区）。
 *
 * 条件表单 → 预览（真实 count + 样本）→ 确认执行 → 结果（成功 N /
 * 失败列表 → 可重试失败项）。starred / read-later 服务端强制排除，
 * 面板照常显示 effectiveExclusions 提示。
 */

import { useState } from 'react'
import { Archive, History, Loader2, Layers } from 'lucide-react'
import { ApiError } from '../api/client'
import type { BacklogCondition, BacklogPreviewView, BacklogSampleItemView } from '../api/client'
import type { BacklogBatchApplyResponse, BacklogBatchPreviewResponse } from '../api/types'
import { useBacklogMutations } from '../api/queries'
import {
  useBacklogBatchLogs,
  useBacklogBatchMutations,
  useBacklogBatches,
  useUndoBacklogBatchMutation,
} from '../api/queries'
import { Button } from './ui/Button'

const DAYS_OPTIONS = [7, 30, 90, 365] as const

/** N049 分批处理区（source / age 分组；每批两段式确认 + 按批撤销）。 */
function BatchMode({ olderThanDays }: { olderThanDays: number }) {
  const [groupBy, setGroupBy] = useState<'source' | 'age'>('source')
  const batchesQuery = useBacklogBatches(groupBy, olderThanDays)
  const { previewBatch, applyBatch } = useBacklogBatchMutations()
  const logsQuery = useBacklogBatchLogs()
  const undoMutation = useUndoBacklogBatchMutation()
  const [previewed, setPreviewed] = useState<BacklogBatchPreviewResponse | null>(null)
  const [previewKey, setPreviewKey] = useState<string | null>(null)
  const [result, setResult] = useState<BacklogBatchApplyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  function runPreview(key: string) {
    setError(null)
    setResult(null)
    setPreviewKey(key)
    previewBatch.mutate(
      { groupBy, key, olderThanDays },
      {
        onSuccess: setPreviewed,
        onError: () => setError('批次预览失败，请稍后重试。'),
      },
    )
  }

  function runApply(key: string, token: string) {
    setError(null)
    applyBatch.mutate(
      { groupBy, key, olderThanDays, confirmPreviewToken: token },
      {
        onSuccess: (data) => {
          setResult(data)
          setPreviewed(null)
          setPreviewKey(null)
        },
        onError: (err) =>
          setError(
            err instanceof ApiError && err.status === 409
              ? '预览令牌已过期（30 秒），请重新预览。'
              : '执行失败，请稍后重试。',
          ),
      },
    )
  }

  return (
    <div className="mt-2 border-t border-[var(--lumi-separator)] pt-2" data-lumi-backlog-batches="">
      <div className="flex flex-wrap items-center gap-2">
        <p className="flex items-center gap-1 font-medium text-[var(--lumi-text-secondary)]">
          <Layers aria-hidden className="size-3.5" />
          分批处理（每批单独确认，可整批撤销）
        </p>
        <label className="flex items-center gap-1 text-[var(--lumi-text-secondary)]">
          分组
          <select
            aria-label="分批分组方式"
            value={groupBy}
            onChange={(e) => {
              setGroupBy(e.target.value as 'source' | 'age')
              setPreviewed(null)
              setPreviewKey(null)
            }}
            className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
          >
            <option value="source">按来源</option>
            <option value="age">按账龄</option>
          </select>
        </label>
      </div>
      {error ? (
        <p role="alert" className="mt-1 text-[var(--lumi-danger)]">
          {error}
        </p>
      ) : null}
      {batchesQuery.isPending ? (
        <p className="mt-1 flex items-center gap-1.5 text-[var(--lumi-text-tertiary)]">
          <Loader2 aria-hidden className="size-3 animate-spin" /> 加载中…
        </p>
      ) : batchesQuery.isError ? (
        <p role="alert" className="mt-1 text-[var(--lumi-danger)]">
          批次加载失败，请稍后重试。
        </p>
      ) : (batchesQuery.data?.batches?.length ?? 0) === 0 ? (
        <p className="mt-1 text-[var(--lumi-text-tertiary)]">当前条件下没有可分批的积压。</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {(batchesQuery.data?.batches ?? []).map((batch) => (
            <li key={batch.key} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
                  {groupBy === 'age' ? batch.key : batch.key.replace(/^https?:\/\//, '')}
                </span>
                <span className="text-[var(--lumi-text-tertiary)]">{batch.count} 条</span>
                {previewKey === batch.key && previewed !== null ? (
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => runApply(batch.key, previewed.confirmPreviewToken)}
                    disabled={applyBatch.isPending || previewed.count === 0}
                  >
                    确认本批（{previewed.count}）
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => runPreview(batch.key)}
                    disabled={previewBatch.isPending}
                  >
                    预览本批
                  </Button>
                )}
              </div>
              {previewKey === batch.key && previewed !== null && (
                <ul className="mt-1 max-h-24 overflow-y-auto">
                  {previewed.sample.map((item: BacklogSampleItemView) => (
                    <li key={item.ref} className="truncate text-[var(--lumi-text-secondary)]">
                      {item.title}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {result !== null && (
        <p role="status" className="mt-1 text-[var(--lumi-text-primary)]" data-lumi-backlog-batch-result="">
          本批已标记 {result.applied} 条为已读{result.failed.length > 0 ? `（${result.failed.length} 条失败）` : ''}；可整批撤销。
        </p>
      )}

      {/* 撤销台账（cap 5；最近的批次可撤销） */}
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <History aria-hidden className="size-3.5 text-[var(--lumi-text-tertiary)]" />
        <span className="text-[10px] text-[var(--lumi-text-tertiary)]">最近批次（最多保留 5 个，可撤销）</span>
      </div>
      <ul className="mt-1 space-y-0.5">
        {(logsQuery.data?.items ?? []).map((log) => (
          <li key={log.id} className="flex items-center gap-1.5 text-[var(--lumi-text-secondary)]">
            <span className="min-w-0 flex-1 truncate">
              {log.batchKey.replace(/^https?:\/\//, '')} · {log.appliedCount} 条 · {log.createdAt.slice(5, 16).replace('T', ' ')}
            </span>
            {log.undone ? (
              <span className="text-[10px] text-[var(--lumi-text-tertiary)]">已撤销</span>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => undoMutation.mutate(log.id)}
                disabled={undoMutation.isPending}
              >
                撤销本批
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function BacklogPanel({ onClose }: { onClose: () => void }) {
  const { preview, apply } = useBacklogMutations()
  const [olderThanDays, setOlderThanDays] = useState<number>(30)
  const [condition] = useState<BacklogCondition>(() => ({ olderThanDays: 30 }))
  const [previewData, setPreviewData] = useState<BacklogPreviewView | null>(null)
  const [result, setResult] = useState<{ applied: number; failed: BacklogSampleItemView[] } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const activeCondition: BacklogCondition = { ...condition, olderThanDays }

  function runPreview() {
    setError(null)
    setResult(null)
    preview.mutate(activeCondition, {
      onSuccess: setPreviewData,
      onError: () => setError('预览失败，请稍后重试。'),
    })
  }

  function runApply(token: string) {
    setError(null)
    apply.mutate(
      { condition: activeCondition, token },
      {
        onSuccess: (data) => {
          setResult({ applied: data.applied, failed: data.failed })
          setPreviewData(null)
        },
        onError: (err) =>
          setError(
            err instanceof ApiError && err.status === 409
              ? '预览令牌已过期（30 秒），请重新预览。'
              : '执行失败，请稍后重试。',
          ),
      },
    )
  }

  function retryFailed() {
    if (!result || result.failed.length === 0) return
    setError(null)
    apply.mutate(
      { condition: activeCondition, token: previewData?.confirmPreviewToken ?? '' },
      {
        onSuccess: (data) => setResult((prev) => ({ applied: (prev?.applied ?? 0) + data.applied, failed: data.failed })),
        onError: () => setError('重试失败，请重新预览。'),
      },
    )
  }

  return (
    <div
      className="mx-4 mb-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2 text-xs"
      data-lumi-backlog-panel=""
    >
      <p className="flex items-center gap-1 font-medium text-[var(--lumi-text-secondary)]">
        <Archive aria-hidden className="size-3.5" />
        积压整理（批量标为已读；加星与稍后读永远排除）
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1 text-[var(--lumi-text-secondary)]">
          早于
          <select
            aria-label="积压天数"
            value={olderThanDays}
            onChange={(e) => {
              setOlderThanDays(Number(e.target.value))
              setPreviewData(null)
            }}
            className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
          >
            {DAYS_OPTIONS.map((days) => (
              <option key={days} value={days}>
                {days} 天前
              </option>
            ))}
          </select>
        </label>
        <Button size="sm" variant="secondary" onClick={runPreview} disabled={preview.isPending}>
          {preview.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : '预览'}
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          关闭
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-1 text-[var(--lumi-danger)]">
          {error}
        </p>
      ) : null}
      {/* N049：分批处理（独立于整批预览/执行；每批两段式 + 可撤销） */}
      <BatchMode olderThanDays={olderThanDays} />
      {previewData ? (
        <div className="mt-2" data-lumi-backlog-preview="">
          <p className="text-[var(--lumi-text-primary)]">
            共 <strong>{previewData.count}</strong> 条未读积压（排除：
            {previewData.effectiveExclusions.join('、')}）
          </p>
          <ul className="mt-1 max-h-32 overflow-y-auto">
            {previewData.sample.map((item) => (
              <li key={item.ref} className="truncate text-[var(--lumi-text-secondary)]">
                {item.title}
              </li>
            ))}
          </ul>
          <Button
            size="sm"
            variant="primary"
            className="mt-1"
            onClick={() => runApply(previewData.confirmPreviewToken)}
            disabled={apply.isPending || previewData.count === 0}
          >
            确认全部标为已读（{previewData.count}）
          </Button>
        </div>
      ) : null}
      {result ? (
        <div className="mt-2" data-lumi-backlog-result="">
          <p className="text-[var(--lumi-text-primary)]">
            已标记 {result.applied} 条为已读
            {result.failed.length > 0 ? `，${result.failed.length} 条失败` : '。'}
          </p>
          {result.failed.length > 0 ? (
            <>
              <ul className="mt-1 max-h-24 overflow-y-auto">
                {result.failed.map((item) => (
                  <li key={item.ref} className="truncate text-[var(--lumi-danger)]">
                    {item.title}
                  </li>
                ))}
              </ul>
              <Button size="sm" variant="secondary" className="mt-1" onClick={retryFailed} disabled={apply.isPending}>
                重试失败项
              </Button>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export default BacklogPanel
