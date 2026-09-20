/** BacklogPanel — F024 积压整理助手（EntryList 工具区）。
 *
 * 条件表单 → 预览（真实 count + 样本）→ 确认执行 → 结果（成功 N /
 * 失败列表 → 可重试失败项）。starred / read-later 服务端强制排除，
 * 面板照常显示 effectiveExclusions 提示。
 */

import { useState } from 'react'
import { Archive, Loader2 } from 'lucide-react'
import { ApiError } from '../api/client'
import type { BacklogCondition, BacklogPreviewView, BacklogSampleItemView } from '../api/client'
import { useBacklogMutations } from '../api/queries'
import { Button } from './ui/Button'

const DAYS_OPTIONS = [7, 30, 90, 365] as const

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
