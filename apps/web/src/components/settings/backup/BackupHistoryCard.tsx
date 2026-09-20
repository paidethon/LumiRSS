/** BackupHistoryCard — 0018 G8：备份 job 历史。
 *
 * 展示时间 / 类型 / 状态 / 目标 / 大小 / 文件名 / 组件 / 失败安全原因；
 * 成功的完整备份可发起「从此备份恢复」（打开 RestoreWizard）。
 * loading / empty / error 三态齐全；列表限最近 20 条（后端已有界）。
 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useBackups } from '../../../api/queries'
import type { BackupJob } from '../../../api/types'
import { compareBackups, type BackupCompareResult } from '../../../api/client'
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

function JobRow({
  job,
  onRestore,
  compareSelected,
  onToggleCompare,
  compareDisabled,
}: {
  job: BackupJob
  onRestore: (job: BackupJob) => void
  compareSelected: boolean
  onToggleCompare: (jobId: string) => void
  compareDisabled: boolean
}) {
  const restorable = job.type === 'full' && job.status === 'succeeded'
  return (
    <li className="flex flex-col gap-1.5 px-3 py-2.5" aria-label={`备份任务 ${JOB_TYPE_LABELS[job.type]} ${JOB_STATUS_LABELS[job.status]}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {/* F115：勾选两份本地备份做 manifest 比较（succeeded 的完整备份） */}
        {restorable && (
          <input
            type="checkbox"
            aria-label={`选择比较 ${job.id}`}
            data-compare-check={job.id}
            checked={compareSelected}
            disabled={compareDisabled && !compareSelected}
            onChange={() => onToggleCompare(job.id)}
            className="size-3.5 accent-[var(--lumi-accent)]"
          />
        )}
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

/** F115：两份备份 manifest 差异比较结果（只读）。 */
function CompareResultView({ result, onClear }: { result: BackupCompareResult; onClear: () => void }) {
  return (
    <div
      className="mt-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5 text-xs"
      data-backup-compare-result=""
    >
      <p className="font-medium text-[var(--lumi-text-primary)]">
        {result.identical ? '两份备份内容一致。' : '两份备份存在差异：'}
      </p>
      {result.schemaVersions !== null && (
        <p className="mt-0.5 text-[var(--lumi-text-tertiary)]">
          Lumi 库 schema：A {String(result.schemaVersions.a)} → B {String(result.schemaVersions.b)}
        </p>
      )}
      {result.categories.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5">
          {result.categories.map((category) => (
            <li key={category.name} className="text-[var(--lumi-text-secondary)]" data-compare-category={category.name}>
              {category.name}：A {category.aCount ?? '—'} / B {category.bCount ?? '—'}（差 {category.delta > 0 ? `+${category.delta}` : category.delta}）
            </li>
          ))}
        </ul>
      )}
      {result.incomparable.length > 0 && (
        <p className="mt-1 text-[var(--lumi-text-tertiary)]" data-compare-incomparable="">
          无法比较（诚实展示，不计 0）：{result.incomparable.join('；')}
        </p>
      )}
      <div className="mt-1.5">
        <Button size="sm" variant="ghost" onClick={onClear}>
          关闭比较
        </Button>
      </div>
    </div>
  )
}

export function BackupHistoryCard() {
  const jobs = useBackups()
  const [wizardOpen, setWizardOpen] = useState(false)
  // F115：勾选两份本地备份 → 比较（只读；incomparable 诚实）
  const [compareIds, setCompareIds] = useState<string[]>([])
  const [compareResult, setCompareResult] = useState<BackupCompareResult | null>(null)
  const compare = useMutation({
    mutationFn: (ids: string[]) => compareBackups(ids[0], ids[1]),
    onSuccess: (data) => setCompareResult(data),
  })
  const compareSelectable = compareIds.length < 2

  const toggleCompare = (jobId: string) => {
    setCompareResult(null)
    setCompareIds((prev) =>
      prev.includes(jobId) ? prev.filter((id) => id !== jobId) : [...prev, jobId].slice(-2),
    )
  }

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
        <>
          <ul className="mt-2 divide-y divide-[var(--lumi-separator)]">
            {jobs.data.slice(0, 20).map((job) => (
              <JobRow
                key={job.id}
                job={job}
                onRestore={() => setWizardOpen(true)}
                compareSelected={compareIds.includes(job.id)}
                onToggleCompare={toggleCompare}
                compareDisabled={!compareSelectable}
              />
            ))}
          </ul>
          {/* F115：恰好勾选两份 → 「比较所选」 */}
          <div className="mt-2 flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              data-backup-compare-go=""
              disabled={compareIds.length !== 2 || compare.isPending}
              onClick={() => compare.mutate(compareIds)}
            >
              {compare.isPending ? '比较中…' : `比较所选（${compareIds.length}/2）`}
            </Button>
            {compareIds.length < 2 && (
              <span className="text-xs text-[var(--lumi-text-tertiary)]">勾选两份成功的完整备份以比较。</span>
            )}
          </div>
          {compare.isError && (
            <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
              比较失败：{compare.error instanceof Error ? compare.error.message : '请稍后重试。'}
            </p>
          )}
          {compareResult !== null && (
            <CompareResultView result={compareResult} onClear={() => setCompareResult(null)} />
          )}
        </>
      )}

      <RestoreWizard open={wizardOpen} onClose={() => setWizardOpen(false)} />
    </div>
  )
}
