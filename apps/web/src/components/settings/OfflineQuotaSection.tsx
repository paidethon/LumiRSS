/** OfflineQuotaSection — N183：离线资料设备配额（device-local）。
 *
 * 枚举本设备 Cache Storage → 用量显示 → 清理预览（大 → 小、旧 → 新）
 * → 应用（只删缓存条目）。说明文案与实现都保证：服务器上的收藏 /
 * 人工笔记 / 阅读状态不受影响；应用阶段不发起任何删除 API 调用
 * （配额保存在本设备 localStorage，默认 200 MB）。
 */

import { useState } from 'react'

import {
  OFFLINE_QUOTA_DEFAULT_MB,
  OFFLINE_QUOTA_MAX_MB,
  OFFLINE_QUOTA_MIN_MB,
  applyCleanup,
  enumerateCacheEntries,
  planCleanup,
  readQuotaMb,
  writeQuotaMb,
  type CacheUsage,
  type CleanupPreviewItem,
} from '../../lib/offline-quota'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function OfflineQuotaSection() {
  const [quotaMb, setQuotaMb] = useState<number>(() => readQuotaMb())
  const [usage, setUsage] = useState<CacheUsage | null>(null)
  const [candidates, setCandidates] = useState<CleanupPreviewItem[] | null>(null)
  const [reclaimable, setReclaimable] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)

  const refreshUsage = async () => {
    setError(null)
    setBusy(true)
    try {
      const next = await enumerateCacheEntries()
      setUsage(next)
      const plan = planCleanup(next, quotaMb * 1024 * 1024)
      setCandidates(plan.overQuota ? plan.candidates : [])
      setReclaimable(plan.reclaimableBytes)
    } catch {
      setError('无法读取本设备的离线缓存。')
    } finally {
      setBusy(false)
    }
  }

  const scanUsage = () => {
    setResult(null)
    void refreshUsage()
  }

  const applyQuota = () => {
    writeQuotaMb(quotaMb)
    if (usage) {
      const plan = planCleanup(usage, quotaMb * 1024 * 1024)
      setCandidates(plan.overQuota ? plan.candidates : [])
      setReclaimable(plan.reclaimableBytes)
    }
  }

  const doCleanup = async () => {
    if (candidates === null || candidates.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const deleted = await applyCleanup(candidates)
      setResult(`已清理 ${deleted} 条离线缓存条目（仅本设备缓存；服务器上的收藏与笔记不受影响）。`)
      await refreshUsage()
    } catch {
      setError('清理失败：部分缓存条目无法删除。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="py-3" data-offline-quota="">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium text-[var(--lumi-text-primary)]">离线资料设备配额</div>
        <label className="flex items-center gap-1.5 text-xs">
          <span className="text-[var(--lumi-text-secondary)]">配额上限（MB，{OFFLINE_QUOTA_MIN_MB}–{OFFLINE_QUOTA_MAX_MB}）</span>
          <input
            type="number"
            min={OFFLINE_QUOTA_MIN_MB}
            max={OFFLINE_QUOTA_MAX_MB}
            value={quotaMb}
            aria-label="离线缓存配额（MB）"
            onChange={(event) => {
              const parsed = Number.parseInt(event.target.value, 10)
              if (!Number.isNaN(parsed)) setQuotaMb(parsed)
            }}
            className="min-h-8 w-20 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
          />
          <Button variant="secondary" size="sm" data-quota-save="" disabled={busy} onClick={applyQuota}>
            保存
          </Button>
        </label>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
        管理本设备的离线缓存（Cache Storage），默认 {OFFLINE_QUOTA_DEFAULT_MB} MB。清理只删除本设备缓存条目，
        绝不触碰服务器上的收藏、人工笔记与阅读状态（不调用任何删除接口）。
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" data-quota-scan="" disabled={busy} onClick={scanUsage}>
          {busy ? '统计中…' : usage === null ? '统计本设备离线缓存' : '重新统计'}
        </Button>
        {candidates !== null && candidates.length > 0 && (
          <Button variant="danger" size="sm" data-quota-clean="" disabled={busy} onClick={() => void doCleanup()}>
            清理 {candidates.length} 条（预计释放 {fmtBytes(reclaimable)}）
          </Button>
        )}
      </div>

      {usage === null && !busy && !error && (
        <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">尚未统计。点击「统计本设备离线缓存」查看用量。</p>
      )}
      {busy && usage === null && (
        <div className="mt-2" aria-label="正在统计离线缓存">
          <Skeleton className="h-9 w-full" />
        </div>
      )}
      {usage !== null && (
        <div className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5 text-xs" data-quota-usage="">
          {!usage.available ? (
            <p className="text-[var(--lumi-text-secondary)]">本设备不支持离线缓存统计（Cache Storage 不可用）。</p>
          ) : (
            <>
              <p className="text-[var(--lumi-text-secondary)]">
                已用 {fmtBytes(usage.knownBytes)} / 配额 {quotaMb} MB · {usage.entryCount} 条（{usage.cacheCount} 个缓存）
                {usage.unknownSizeCount > 0 && `；另有 ${usage.unknownSizeCount} 条大小未知（不冒充 0）`}
              </p>
              {candidates !== null && candidates.length === 0 && (
                <p className="mt-0.5 text-[var(--lumi-text-tertiary)]" data-quota-ok="">
                  未超出配额，无需清理。
                </p>
              )}
              {candidates !== null && candidates.length > 0 && (
                <ul className="mt-1 flex flex-col gap-0.5" data-quota-candidates="">
                  {candidates.slice(0, 8).map((candidate) => (
                    <li key={`${candidate.cacheName}:${candidate.url}`} className="truncate text-[var(--lumi-text-secondary)]">
                      {candidate.url}（{candidate.sizeBytes === null ? '大小未知' : fmtBytes(candidate.sizeBytes)}）
                    </li>
                  ))}
                  {candidates.length > 8 && (
                    <li className="text-[var(--lumi-text-tertiary)]">…等共 {candidates.length} 条</li>
                  )}
                </ul>
              )}
            </>
          )}
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">{error}</p>}
      {result && <p role="status" className="mt-2 text-xs text-[var(--lumi-text-secondary)]" data-quota-result="">{result}</p>}
    </div>
  )
}
