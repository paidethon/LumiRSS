/** BackupOverview — 0018 G8：备份概览 + 立即创建完整备份 + 活动 job 状态。
 *
 * 数据全部来自真实 API（operations/status + backups job 列表）：
 * - readiness（SQLite 健康）；
 * - 最近成功 / 最近失败；
 * - 活动 job（queued/running）按 stage 如实展示，不伪造百分比；
 * - 单并发：有活动 job 时禁用创建（后端 backup_busy 双保险）；
 * - 页面刷新后 job 状态从服务端恢复（TanStack Query refetch）。
 */

import { useCreateBackupMutation, useBackups, useOperationsStatus } from '../../../api/queries'
import type { BackupJob } from '../../../api/types'
import { Button } from '../../ui/Button'
import { Skeleton } from '../../ui/Skeleton'
import { cx } from '../../ui/cx'
import { AlertCircle, CheckCircle2, DatabaseBackup, HardDriveUpload, Loader2 } from 'lucide-react'
import {
  componentLabel,
  formatBytes,
  formatJobTime,
  jobStageText,
} from './backup-format'

function isActiveJob(job: BackupJob | undefined): boolean {
  return job !== undefined && (job.status === 'queued' || job.status === 'running')
}

function ActiveJobCard({ job }: { job: BackupJob }) {
  return (
    <div
      role="status"
      aria-label="备份正在进行"
      className="flex items-start gap-2.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)] bg-[var(--lumi-accent-soft)] px-3.5 py-2.5"
    >
      <Loader2 aria-hidden className="mt-0.5 size-4 shrink-0 animate-spin text-[var(--lumi-accent)]" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
          {job.type === 'safety' ? '恢复前安全备份' : '完整备份'}进行中
        </p>
        <p className="mt-0.5 text-xs text-[var(--lumi-text-secondary)]">
          {jobStageText(job)}（创建于 {formatJobTime(job.createdAt)}）
        </p>
      </div>
    </div>
  )
}

export function BackupOverview() {
  const status = useOperationsStatus()
  const jobs = useBackups()
  const create = useCreateBackupMutation()

  const activeJob = jobs.data?.find((job) => isActiveJob(job))
  const busy = activeJob !== undefined || create.isPending
  const lastSucceeded = jobs.data?.find((job) => job.type === 'full' && job.status === 'succeeded')
  const lastFailed = jobs.data?.find(
    (job) => (job.status === 'failed' || job.status === 'interrupted'),
  )

  if (jobs.isError) {
    return (
      <p role="alert" className="flex items-start gap-1.5 text-sm text-[var(--lumi-danger)]">
        <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
        无法获取备份状态：{jobs.error instanceof Error ? jobs.error.message : '请稍后重试。'}
      </p>
    )
  }

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex items-center gap-2">
        <DatabaseBackup aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">备份概览</h3>
      </div>

      {jobs.data === undefined ? (
        <div className="mt-3 flex flex-col gap-2" aria-label="正在加载备份概览">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ) : (
        <dl className="mt-3 divide-y divide-[var(--lumi-separator)] text-sm">
          <div className="flex items-center justify-between gap-3 py-2">
            <dt className="text-[var(--lumi-text-secondary)]">系统就绪</dt>
            <dd className="flex items-center gap-1.5 text-[var(--lumi-text-primary)]">
              {status.data?.sqlite.status === 'healthy' ? (
                <>
                  <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-accent)]" />
                  正常
                </>
              ) : (
                <>
                  <AlertCircle aria-hidden className="size-3.5 text-[var(--lumi-danger)]" />
                  {status.data === undefined ? '检查中…' : '本地数据不可用，暂无法备份'}
                </>
              )}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-3 py-2">
            <dt className="text-[var(--lumi-text-secondary)]">最近成功备份</dt>
            <dd className="text-right text-[var(--lumi-text-primary)]">
              {lastSucceeded
                ? `${formatJobTime(lastSucceeded.finishedAt ?? lastSucceeded.createdAt)} · ${formatBytes(lastSucceeded.summary?.sizeBytes)}`
                : '尚无备份'}
            </dd>
          </div>
          {lastFailed && (
            <div className="flex items-start justify-between gap-3 py-2">
              <dt className="shrink-0 text-[var(--lumi-text-secondary)]">最近一次失败</dt>
              <dd className="min-w-0 text-right text-[var(--lumi-text-primary)]">
                {formatJobTime(lastFailed.createdAt)}
                {lastFailed.safeError && (
                  <span className="mt-0.5 block text-xs leading-relaxed text-[var(--lumi-danger)]">
                    {lastFailed.safeError}
                  </span>
                )}
              </dd>
            </div>
          )}
          <div className="flex items-start justify-between gap-3 py-2">
            <dt className="shrink-0 text-[var(--lumi-text-secondary)]">备份内容</dt>
            <dd className="min-w-0 text-right text-xs leading-relaxed text-[var(--lumi-text-primary)]">
              Lumi 数据库（设置 / AI 缓存 / 对话）+ FreshRSS 数据（订阅 / 文章状态）。
              <span className="mt-0.5 block text-[var(--lumi-text-tertiary)]">
                秘密（WebDAV 密码 / RSSHub 凭据 / API Key）不进入备份；恢复后需重新配置。
              </span>
            </dd>
          </div>
        </dl>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={busy}
          onClick={() => create.mutate('local')}
        >
          {create.isPending && create.variables === 'local' ? (
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
          ) : (
            <HardDriveUpload aria-hidden className="size-3.5" />
          )}
          创建完整备份（本机）
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={() => create.mutate('webdav')}
        >
          {create.isPending && create.variables === 'webdav' ? (
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
          ) : (
            <HardDriveUpload aria-hidden className="size-3.5" />
          )}
          备份并上传 WebDAV
        </Button>
      </div>
      {create.isError && (
        <p role="alert" className={cx('mt-2 text-xs leading-relaxed text-[var(--lumi-danger)]')}>
          创建失败：{create.error instanceof Error ? create.error.message : '请稍后重试。'}
        </p>
      )}
      {activeJob && <div className="mt-3"><ActiveJobCard job={activeJob} /></div>}
      {lastSucceeded?.summary?.components && !activeJob && (
        <p className="mt-2 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
          最近备份包含：{lastSucceeded.summary.components.map(componentLabel).join('、')}。
        </p>
      )}
    </div>
  )
}
