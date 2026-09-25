/** BackupOverview — 0018 G8：备份概览 + 立即创建完整备份 + 活动 job 状态。
 *
 * 数据全部来自真实 API（operations/status + backups job 列表）：
 * - readiness（SQLite 健康）；
 * - 最近成功 / 最近失败；
 * - 活动 job（queued/running）按 stage 如实展示，不伪造百分比；
 * - 单并发：有活动 job 时禁用创建（后端 backup_busy 双保险）；
 * - 页面刷新后 job 状态从服务端恢复（TanStack Query refetch）。
 */

import { useState } from 'react'
import {
  useBackupCapabilities,
  useCreateBackupMutation,
  useBackups,
  useOperationsStatus,
  usePreviewBackupScopeMutation,
} from '../../../api/queries'
import type { BackupJob, BackupScopeInclude, BackupScopePreview } from '../../../api/types'
import { Button } from '../../ui/Button'
import { Skeleton } from '../../ui/Skeleton'
import { cx } from '../../ui/cx'
import { AlertCircle, CheckCircle2, DatabaseBackup, HardDriveUpload, Loader2 } from 'lucide-react'
import {
  componentLabel,
  formatBytes,
  formatJobTime,
  freshrssReasonText,
  jobStageText,
} from './backup-format'

const SCOPE_ITEMS: { key: keyof BackupScopeInclude; label: string }[] = [
  { key: 'workspaces', label: '工作区' },
  { key: 'notes', label: '人工笔记' },
  { key: 'annotations', label: '批注' },
  { key: 'sourceConfig', label: '来源配置' },
]

function isFullScope(include: BackupScopeInclude): boolean {
  return SCOPE_ITEMS.every((item) => include[item.key])
}

const SCOPE_COMPONENT_LABELS: Record<string, string> = {
  workspaces: '工作区',
  notes: '人工笔记',
  annotations: '批注',
  sourceConfig: '来源配置',
}

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
      <Loader2 aria-hidden className="mt-0.5 size-4 shrink-0 animate-spin text-[var(--lumi-accent-text)]" />
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
  const capabilities = useBackupCapabilities()
  const create = useCreateBackupMutation()
  const scopePreview = usePreviewBackupScopeMutation()

  // N185：备份内容选择（默认全包含 = 与历史行为一致）+ 预览步骤
  const [include, setInclude] = useState<BackupScopeInclude>({
    workspaces: true,
    notes: true,
    annotations: true,
    sourceConfig: true,
  })
  const scoped = !isFullScope(include)
  const scopePreviewData: BackupScopePreview | undefined = scopePreview.data

  const activeJob = jobs.data?.find((job) => isActiveJob(job))
  const busy = activeJob !== undefined || create.isPending
  const lastSucceeded = jobs.data?.find((job) => job.type === 'full' && job.status === 'succeeded')
  const lastFailed = jobs.data?.find(
    (job) => (job.status === 'failed' || job.status === 'interrupted'),
  )
  // 点击前就如实告知完整备份能不能做、为什么不能；后端执行时仍会校验。
  const fullBackupReady = capabilities.data?.fullBackupReady
  const freshrssReason = freshrssReasonText(
    capabilities.data?.freshrssData.reasonCode,
    capabilities.data?.freshrssData.reason,
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
                  <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-accent-text)]" />
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
            <dd className="min-w-0 text-right text-xs leading-relaxed">
              {capabilities.data === undefined ? (
                <span className="text-[var(--lumi-text-tertiary)]">检查备份能力…</span>
              ) : (
                <span className="text-[var(--lumi-text-primary)]">
                  {capabilities.data.includes.length > 0 ? (
                    capabilities.data.includes.map(componentLabel).join('；')
                  ) : (
                    <span className="text-[var(--lumi-danger)]">当前没有任何可备份组件</span>
                  )}
                </span>
              )}
              <span className="mt-0.5 block text-[var(--lumi-text-tertiary)]">
                秘密（WebDAV 密码 / RSSHub 凭据 / API Key）不进入备份；恢复后需重新配置。
              </span>
            </dd>
          </div>
          {freshrssReason && (
            <div className="flex items-start justify-between gap-3 py-2">
              <dt className="shrink-0 text-[var(--lumi-text-secondary)]">FreshRSS 数据</dt>
              <dd className="min-w-0 text-right text-xs leading-relaxed text-[var(--lumi-danger)]">
                {freshrssReason}
              </dd>
            </div>
          )}
        </dl>
      )}

      {/* N185：备份内容选择 + 预览（默认全包含；凭据 / FreshRSS 内容
          永远排除，预览如实列出） */}
      <div className="mt-3" data-backup-scope="">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <span className="text-xs text-[var(--lumi-text-secondary)]">备份内容：</span>
          {SCOPE_ITEMS.map((item) => (
            <label key={item.key} className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={include[item.key]}
                onChange={(event) =>
                  setInclude((current) => ({ ...current, [item.key]: event.target.checked }))
                }
                className="size-3.5"
              />
              {item.label}
            </label>
          ))}
          <Button
            variant="secondary"
            size="sm"
            data-scope-preview=""
            disabled={scopePreview.isPending}
            onClick={() => scopePreview.mutate(include)}
          >
            {scopePreview.isPending ? '预览中…' : '预览备份内容'}
          </Button>
        </div>
        {scopePreview.isError && (
          <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
            预览失败：{scopePreview.error instanceof Error ? scopePreview.error.message : '请稍后重试。'}
          </p>
        )}
        {scopePreviewData && (
          <div
            className="mt-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5 text-xs"
            data-scope-preview-result=""
          >
            <p className="text-[var(--lumi-text-secondary)]">
              将包含：
              {scopePreviewData.components.map((component) => (
                <span key={component.component} data-scope-component={component.component}>
                  {' '}{SCOPE_COMPONENT_LABELS[component.component] ?? component.component} {component.count} 行；
                </span>
              ))}
            </p>
            <p className="mt-0.5 text-[var(--lumi-text-tertiary)]">
              永远排除：{scopePreviewData.alwaysExcluded.join('；')}。
            </p>
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={busy || fullBackupReady === false}
          onClick={() => create.mutate({ target: 'local', include: scoped ? include : undefined })}
        >
          {create.isPending && create.variables?.target === 'local' ? (
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
          ) : (
            <HardDriveUpload aria-hidden className="size-3.5" />
          )}
          创建完整备份（本机）
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy || fullBackupReady === false}
          onClick={() => create.mutate({ target: 'webdav', include: scoped ? include : undefined })}
        >
          {create.isPending && create.variables?.target === 'webdav' ? (
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
          ) : (
            <HardDriveUpload aria-hidden className="size-3.5" />
          )}
          备份并上传 WebDAV
        </Button>
      </div>
      {scoped && (
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]" data-scope-note="">
          已缩小备份范围（仅勾选的用户数据组件会被包含）；默认全包含时行为与完整备份完全一致。
        </p>
      )}
      {fullBackupReady === false && (
        <p role="alert" className={cx('mt-2 text-xs leading-relaxed text-[var(--lumi-danger)]')}>
          {freshrssReason ?? '完整备份当前不可用。'}
        </p>
      )}
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
