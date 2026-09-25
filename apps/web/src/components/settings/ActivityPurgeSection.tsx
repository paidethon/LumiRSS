/** ActivityPurgeSection — N189 清除活动记录（数据控制 → 隐私）。
 *
 * 流程：选日期 → 预览（服务端各活动桶的计数，只读）→ 确认清除。
 * 诚实边界：只清服务端活动记录（登录事件 / AI 任务日志 / 搜索快照）；
 * 已读/收藏/笔记等业务状态不受影响；阅读路径与语音书签是设备本地
 * 的——服务端没有可清的数据，如实说明而非冒充已清除。 */

import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import {
  ApiError,
  applyActivityPurge,
  previewActivityPurge,
  type ActivityPurgePreviewResult,
  type ActivityPurgeResult,
} from '../../api/client'
import { Button } from '../ui/Button'

const BUCKET_LABELS: Record<string, string> = {
  loginEvents: '登录事件',
  aiTaskLogs: 'AI 任务日志',
  searchSnapshots: '搜索快照',
}

export function ActivityPurgeSection() {
  const [before, setBefore] = useState('')
  const [preview, setPreview] = useState<ActivityPurgePreviewResult | null>(null)
  const [result, setResult] = useState<ActivityPurgeResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const hasCounts =
    preview !== null && Object.values(preview.counts).some((count) => count > 0)

  async function runPreview() {
    setError(null)
    setPreview(null)
    setResult(null)
    if (!before) return
    setBusy(true)
    try {
      setPreview(await previewActivityPurge(before))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '预览失败，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }

  async function runPurge() {
    if (!before) return
    setBusy(true)
    setError(null)
    try {
      setResult(await applyActivityPurge(before))
      setPreview(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '清除失败，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="py-2" data-lumi-activity-purge="">
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        清除指定日期之前的服务端活动记录：登录事件、AI 任务日志、搜索快照。
        已读/收藏/笔记等业务状态不受影响；阅读路径与语音书签保存在设备本地，
        服务端没有可清的数据。
      </p>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <div>
          <label
            htmlFor="activity-purge-before"
            className="mb-1 block text-xs font-medium text-[var(--lumi-text-primary)]"
          >
            清除此日期之前
          </label>
          <input
            id="activity-purge-before"
            type="date"
            value={before}
            onChange={(event) => setBefore(event.target.value)}
            className="min-h-10 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          />
        </div>
        <Button variant="secondary" size="sm" disabled={!before || busy} onClick={runPreview}>
          {busy ? '处理中…' : '预览'}
        </Button>
        {hasCounts && (
          <Button variant="danger" size="sm" disabled={busy} onClick={runPurge} data-testid="lumi-activity-purge-confirm">
            <Trash2 aria-hidden className="size-4" />
            确认清除
          </Button>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          {error}
        </p>
      )}
      {preview && (
        <ul className="mt-2 flex flex-col gap-1 text-xs" data-testid="lumi-activity-purge-preview">
          {Object.entries(preview.counts).map(([bucket, count]) => (
            <li key={bucket} className="flex justify-between gap-2">
              <span className="text-[var(--lumi-text-secondary)]">{BUCKET_LABELS[bucket] ?? bucket}</span>
              <span className="text-[var(--lumi-text-primary)]">{count} 条</span>
            </li>
          ))}
        </ul>
      )}
      {result && (
        <div className="mt-2 flex flex-col gap-1" data-testid="lumi-activity-purge-result">
          <p className="text-xs text-[var(--lumi-accent-text)]">已清除 {before} 之前的活动记录：</p>
          <ul className="flex flex-col gap-1 text-xs">
            {Object.entries(result.deleted).map(([bucket, count]) => (
              <li key={bucket} className="flex justify-between gap-2">
                <span className="text-[var(--lumi-text-secondary)]">{BUCKET_LABELS[bucket] ?? bucket}</span>
                <span className="text-[var(--lumi-text-primary)]">删除 {count} 条</span>
              </li>
            ))}
          </ul>
          <ul className="mt-1 flex flex-col gap-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
            {result.retained.map((note) => (
              <li key={note}>· {note}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
