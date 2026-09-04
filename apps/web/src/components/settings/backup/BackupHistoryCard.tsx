/** BackupHistoryCard — 0018 G8：备份 job 历史。
 *
 * 展示时间 / 类型 / 状态 / 目标 / 大小 / 文件名 / 组件 / 失败安全原因；
 * 成功的完整备份可发起「从此备份恢复」（打开 RestoreWizard）。
 * loading / empty / error 三态齐全；列表限最近 20 条（后端已有界）。
 */

import { useState } from 'react'
import { useBackups } from '../../../api/queries'
import type { BackupJob } from '../../../api/types'
import { Button } from '../../ui/Button'
import { EmptyState } from '../../ui/EmptyState'
import { Skeleton } from '../../ui/Skeleton'
import { cx } from '../../ui/cx'
import { AlertCircle, History, RotateCcw } from 'lucide-react'
import { RestoreWizard } from './RestoreWizard'
import {
  JOB_STATUS_LABELS,
  JOB_TYPE_LABELS,
  formatBytes,
  formatJobTime,
  jobStageText,
} from './backup-format'

const STATUS_TONE: Record<BackupJob['status'], string> = {
  queued: 'text-[var(--lumi-text-secondary)]',
  running: 'text-[var(--lumi-accent-text)]',
  succeeded: 'text-[var(--lumi-accent-text)]',
  failed: 'text-[var(--lumi-danger)]',
  interrupted: 'text-[var(--lumi-danger)]',
}

function JobRow({ job, onRestore }: { job: BackupJob; onRestore: (job: BackupJob) => void }) {
  const restorable = job.type === 'full' && job.status === 'succeeded'
  return (
    <li className="flex flex-col gap-1.5 px-3 py-2.5" aria-label={`备份任务 ${JOB_TYPE_LABELS[job.type]} ${JOB_STATUS_LABELS[job.status]}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={cx('text-sm font-medium', STATUS_TONE[job.status])}>
          {jobStageText(job)}
        </span>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">
          {JOB_TYPE_LABELS[job.type]}
          {job.summary?.target ? ` · ${job.summary.target === 'webdav' ? 'WebDAV' : '本机'}` : ''}
        </span>
        <span className="ml-auto text-xs text-[var(--lumi-text-tertiary)]">
          {formatJobTime(job.createdAt)}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--lumi-text-secondary)]">
        {job.summary?.filename && (
          <span className="max-w-full truncate font-mono text-[var(--lumi-text-tertiary)]">
            {job.summary.filename}
          </span>
        )}
        {job.summary?.sizeBytes !== undefined && <span>{formatBytes(job.summary.sizeBytes)}</span>}
        {job.summary?.components && (
          <span className="text-[var(--lumi-text-tertiary)]">
            {job.summary.components.join(' + ')}
          </span>
        )}
      </div>
      {job.safeError && (
        <p className="text-xs leading-relaxed text-[var(--lumi-danger)]">{job.safeError}</p>
      )}
      {restorable && (
        <div>
          <Button size="sm" variant="secondary" onClick={() => onRestore(job)}>
            <RotateCcw aria-hidden className="size-3.5" />
            从此备份恢复
          </Button>
        </div>
      )}
    </li>
  )
}

export function BackupHistoryCard() {
  const jobs = useBackups()
  const [wizardOpen, setWizardOpen] = useState(false)

  if (jobs.isError) {
    return (
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <h3 className="flex items-center gap-2 text-sm font-medium text-[var(--lumi-text-primary)]">
          <History aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
          备份历史
        </h3>
        <p role="alert" className="mt-2 flex items-start gap-1.5 text-sm text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
          无法获取备份历史：{jobs.error instanceof Error ? jobs.error.message : '请稍后重试。'}
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <h3 className="flex items-center gap-2 text-sm font-medium text-[var(--lumi-text-primary)]">
        <History aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
        备份历史
      </h3>

      {jobs.data === undefined ? (
        <div className="mt-3 flex flex-col gap-2" aria-label="正在加载备份历史">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : jobs.data.length === 0 ? (
        <EmptyState
          icon={<History aria-hidden className="size-5" />}
          title="暂无备份"
          description="创建第一个完整备份后，历史会显示在这里。"
        />
      ) : (
        <ul className="mt-2 divide-y divide-[var(--lumi-separator)]">
          {jobs.data.slice(0, 20).map((job) => (
            <JobRow
              key={job.id}
              job={job}
              onRestore={() => setWizardOpen(true)}
            />
          ))}
        </ul>
      )}

      <RestoreWizard open={wizardOpen} onClose={() => setWizardOpen(false)} />
    </div>
  )
}
