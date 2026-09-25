/** RestoreWizard — 0018 G8：分阶段恢复向导（Dialog）。
 *
 * 严格实现 spec AD-0018-9 状态机：
 * select（本地/WebDAV 来源）→ preview（下载/定位 + checksum + manifest +
 * compatibility）→ confirm（显式输入 RESTORE；说明会自动创建当前状态安全
 * 备份）→ execute（执行）→ result（健康验证结果 + FreshRSS 离线恢复说明 /
 * 失败安全恢复信息）。
 *
 * 禁止单按钮直接恢复；不兼容 manifest 在 preview 阶段拒绝；执行错误只显示
 * safeError（无 stacktrace / 凭据）。
 */

import { useState } from 'react'
import {
  useBackupVerifyMutation,
  useBackups,
  useRemoteBackups,
  useRestoreExecuteMutation,
  useRestorePreviewMutation,
} from '../../../api/queries'
import type { BackupJob, BackupVerifyReport, RestorePreview, RestoreResult } from '../../../api/types'
import { clearPendingSettingsSync } from '../../../store/settings-sync'
import { Button } from '../../ui/Button'
import { Dialog } from '../../ui/Dialog'
import { Skeleton } from '../../ui/Skeleton'
import { cx } from '../../ui/cx'
import { AlertCircle, CheckCircle2, Loader2, ShieldCheck, XCircle } from 'lucide-react'
import { componentLabel, formatBytes, formatJobTime } from './backup-format'

type Step = 'select' | 'preview' | 'conflicts' | 'confirm' | 'result' | 'verify'

const CONFIRM_TEXT = 'RESTORE'

interface SelectedSource {
  source: 'local' | 'remote'
  jobId?: string
  fileName?: string
  label: string
}

function SourcePicker({
  localJobs,
  onPick,
  onVerify,
  onBack,
}: {
  localJobs: BackupJob[]
  onPick: (picked: SelectedSource) => void
  onVerify: (jobId: string) => void
  onBack: () => void
}) {
  const remote = useRemoteBackups(true)
  const restorable = localJobs.filter((job) => job.type === 'full' && job.status === 'succeeded')

  return (
    <div className="flex flex-col gap-4">
      <section aria-label="本机备份">
        <h4 className="text-xs font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
          本机备份
        </h4>
        {restorable.length === 0 ? (
          <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            本机暂无可恢复的备份。先在「备份概览」创建一个完整备份。
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-[var(--lumi-separator)] rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]">
            {restorable.slice(0, 8).map((job) => (
              <li key={job.id} className="flex items-center justify-between gap-2 px-3 py-2.5">
                <button
                  type="button"
                  onClick={() =>
                    onPick({ source: 'local', jobId: job.id, label: job.summary?.filename ?? job.id })
                  }
                  className="min-w-0 flex-1 text-left transition-colors hover:opacity-80 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <span className="block truncate text-sm text-[var(--lumi-text-primary)]">
                    {job.summary?.filename ?? job.id}
                  </span>
                  <span className="mt-0.5 block text-xs text-[var(--lumi-text-tertiary)]">
                    {formatJobTime(job.finishedAt ?? job.createdAt)} · {formatBytes(job.summary?.sizeBytes)}
                  </span>
                </button>
                <span className="flex shrink-0 items-center gap-1.5">
                  <Button
                    variant="ghost"
                    size="sm"
                    data-verify-job={job.id}
                    aria-label="仅校验完整性（不恢复）"
                    onClick={() => onVerify(job.id)}
                  >
                    仅校验
                  </Button>
                  <button
                    type="button"
                    onClick={() =>
                      onPick({ source: 'local', jobId: job.id, label: job.summary?.filename ?? job.id })
                    }
                    className="text-xs text-[var(--lumi-accent-text)] transition-colors hover:opacity-80 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                  >
                    选择
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="WebDAV 备份">
        <h4 className="text-xs font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
          WebDAV 备份
        </h4>
        {remote.isError ? (
          <p role="alert" className="mt-2 text-xs leading-relaxed text-[var(--lumi-danger)]">
            远端列表不可用：{remote.error instanceof Error ? remote.error.message : '请稍后重试。'}
            {remote.error instanceof Error && remote.error.message.includes('WebDAV') && (
              <span className="mt-0.5 block text-[var(--lumi-text-tertiary)]">
                如需从 WebDAV 恢复，请先在本页下方配置并保存 WebDAV。
              </span>
            )}
          </p>
        ) : remote.data === undefined ? (
          <div className="mt-2" aria-label="正在加载远端备份列表">
            <Skeleton className="h-10 w-full" />
          </div>
        ) : remote.data.backups.length === 0 ? (
          <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            WebDAV 上暂无备份文件。
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-[var(--lumi-separator)] rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]">
            {remote.data.backups.slice(0, 8).map((file) => (
              <li key={file.fileName}>
                <button
                  type="button"
                  onClick={() => onPick({ source: 'remote', fileName: file.fileName, label: file.fileName })}
                  className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left transition-colors hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-[var(--lumi-text-primary)]">{file.fileName}</span>
                    <span className="mt-0.5 block text-xs text-[var(--lumi-text-tertiary)]">
                      {formatBytes(file.sizeBytes)}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs text-[var(--lumi-accent-text)]">选择</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="flex justify-end">
        <Button size="sm" variant="ghost" onClick={onBack}>取消</Button>
      </div>
    </div>
  )
}

function PreviewPane({
  preview,
  onConfirm,
  onCancel,
}: {
  preview: RestorePreview
  onConfirm: () => void
  onCancel: () => void
}) {
  const compatible = preview.compatible
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-2.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3.5 py-2.5">
        <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-accent-text)]" />
        <div className="min-w-0 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          <p className="text-sm font-medium text-[var(--lumi-text-primary)]">校验通过</p>
          <p className="mt-0.5">文件 {preview.fileName}：checksum（SHA-256）与 manifest 均已验证。</p>
          {preview.createdAt && <p className="mt-0.5">备份创建于 {formatJobTime(preview.createdAt)}。</p>}
        </div>
      </div>

      <dl className="divide-y divide-[var(--lumi-separator)] text-sm">
        <div className="flex items-start justify-between gap-3 py-2">
          <dt className="shrink-0 text-[var(--lumi-text-secondary)]">将恢复的数据</dt>
          <dd className="min-w-0 text-right text-xs leading-relaxed text-[var(--lumi-text-primary)]">
            {preview.components.map(componentLabel).join('、')}
            <span className="mt-0.5 block text-[var(--lumi-text-tertiary)]">
              共 {preview.files.length} 个文件 · {formatBytes(preview.files.reduce((sum, f) => sum + f.size, 0))}
            </span>
          </dd>
        </div>
        <div className="flex items-start justify-between gap-3 py-2">
          <dt className="shrink-0 text-[var(--lumi-text-secondary)]">数据版本</dt>
          <dd className="text-right text-xs text-[var(--lumi-text-primary)]">
            备份 schema v{preview.lumiDbSchemaVersion} · 当前 v{preview.currentDbSchemaVersion}
          </dd>
        </div>
        <div className="flex items-start justify-between gap-3 py-2">
          <dt className="shrink-0 text-[var(--lumi-text-secondary)]">秘密</dt>
          <dd className="text-right text-xs leading-relaxed text-[var(--lumi-text-primary)]">
            不含 Lumi 秘密值{preview.excludedSecrets.length > 0 && `（排除 ${preview.excludedSecrets.length} 类）`}
            ；恢复后需重新配置 WebDAV / RSSHub 凭据。归档可能含
            FreshRSS 敏感数据，请当作敏感文件妥善保管。
          </dd>
        </div>
      </dl>

      {compatible ? (
        <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          恢复将覆盖当前 Lumi 数据。执行时会先自动创建「当前状态安全备份」，失败时可用它回退；
          FreshRSS 数据将进入离线恢复就绪状态（给出官方步骤，Lumi 不写运行中的 FreshRSS）。
        </p>
      ) : (
        <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          此备份的数据版本（schema v{preview.lumiDbSchemaVersion}）与当前应用
          （v{preview.currentDbSchemaVersion}）不兼容，无法恢复。请先升级应用后再试。
        </p>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onCancel}>取消</Button>
        <Button
          size="sm"
          variant="danger"
          disabled={!compatible}
          onClick={onConfirm}
        >
          继续恢复…
        </Button>
      </div>
    </div>
  )
}

/** N187：冲突决策步骤——逐对象 skip|overwrite（缺省 skip = 保留现状）。
 * 清单来自 preview.conflicts（活动状态 vs 备份成员的 exists/differs 对比）。 */
function ConflictStep({
  conflicts,
  decisions,
  onChange,
  onCancel,
  onContinue,
}: {
  conflicts: NonNullable<RestorePreview['conflicts']>
  decisions: Record<string, 'skip' | 'overwrite'>
  onChange: (path: string, strategy: 'skip' | 'overwrite') => void
  onCancel: () => void
  onContinue: () => void
}) {
  const conflictCount = conflicts.filter((item) => item.differs || item.exists).length
  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-text-primary)]">
        <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-accent-text)]" />
        备份中的对象与当前状态存在重叠。请为每个对象选择处理方式：
        「保留现状」不动现有数据；「覆盖」用备份内容替换。
      </p>
      <ul
        data-testid="restore-conflict-list"
        className="max-h-64 divide-y divide-[var(--lumi-separator)] overflow-y-auto rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]"
      >
        {conflicts.map((item) => {
          const current = decisions[item.path] ?? 'skip'
          return (
            <li key={item.path} className="flex items-center gap-2 px-3 py-2 text-xs">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-[var(--lumi-text-primary)]">{item.path}</p>
                <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
                  {componentLabel(item.component)}
                  {item.exists ? (item.differs ? ' · 与当前内容不同' : ' · 与当前内容相同') : ' · 当前不存在'}
                </p>
              </div>
              <label className="flex shrink-0 items-center gap-1">
                <input
                  type="radio"
                  name={`conflict-${item.path}`}
                  checked={current === 'skip'}
                  onChange={() => onChange(item.path, 'skip')}
                />
                保留现状
              </label>
              <label className="flex shrink-0 items-center gap-1">
                <input
                  type="radio"
                  name={`conflict-${item.path}`}
                  checked={current === 'overwrite'}
                  onChange={() => onChange(item.path, 'overwrite')}
                />
                覆盖
              </label>
            </li>
          )
        })}
      </ul>
      <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
        共 {conflicts.length} 个对象（{conflictCount} 个与当前状态重叠）。缺省全部「保留现状」。
      </p>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onCancel}>取消</Button>
        <Button size="sm" variant="danger" onClick={onContinue}>
          继续确认…
        </Button>
      </div>
    </div>
  )
}

function ConfirmPane({
  onConfirmed,
  onCancel,
  busy,
}: {
  onConfirmed: (confirmation: string) => void
  onCancel: () => void
  busy: boolean
}) {
  const [text, setText] = useState('')
  const ready = text.trim() === CONFIRM_TEXT
  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-text-primary)]">
        <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-danger)]" />
        这是破坏性操作：恢复会覆盖当前全部 Lumi 数据（设置、AI 缓存、对话）。
        FreshRSS 数据会进入离线恢复流程。
      </p>
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        已自动采取的保护：执行前先创建当前状态安全备份；恢复与备份互斥执行。
        确认请输入 <code className="rounded bg-[var(--lumi-surface)] px-1 font-mono">RESTORE</code>：
      </p>
      <input
        type="text"
        value={text}
        aria-label={`输入 ${CONFIRM_TEXT} 以确认恢复`}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
        className={cx(
          'w-full min-h-9 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
          'bg-[var(--lumi-surface)] px-2.5 font-mono text-sm text-[var(--lumi-text-primary)]',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        )}
      />
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>取消</Button>
        <Button size="sm" variant="danger" disabled={!ready || busy} onClick={() => onConfirmed(text.trim())}>
          {busy && <Loader2 aria-hidden className="size-3.5 animate-spin" />}
          执行恢复
        </Button>
      </div>
    </div>
  )
}

function ResultPane({ result, onReload }: { result: RestoreResult; onReload: () => void }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-text-primary)]">
        <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-accent-text)]" />
        恢复完成：本地数据已恢复，健康检查通过（{result.health?.sqlite ?? 'sqlite ok'}）。
      </p>
      <dl className="divide-y divide-[var(--lumi-separator)] text-sm">
        {result.safetyBackupId && (
          <div className="flex items-start justify-between gap-3 py-2">
            <dt className="shrink-0 text-[var(--lumi-text-secondary)]">恢复前安全备份</dt>
            <dd className="min-w-0 text-right font-mono text-xs text-[var(--lumi-text-primary)]">
              {result.safetyBackupId}
              <span className="mt-0.5 block font-sans text-[var(--lumi-text-tertiary)]">
                出现问题时可在备份历史中找到它
              </span>
            </dd>
          </div>
        )}
        <div className="flex items-start justify-between gap-3 py-2">
          <dt className="shrink-0 text-[var(--lumi-text-secondary)]">FreshRSS 数据</dt>
          <dd className="min-w-0 text-right text-xs leading-relaxed text-[var(--lumi-text-primary)]">
            {result.freshrss === 'not_included'
              ? '此备份不含 FreshRSS 数据。'
              : '已就绪待离线恢复：按运行手册执行官方 compose 恢复步骤（Lumi 不会写入运行中的 FreshRSS）。'}
          </dd>
        </div>
      </dl>
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        恢复已替换整个本地数据库；请刷新应用以载入恢复后的数据（避免旧缓存残留）；
        秘密（WebDAV / RSSHub 凭据）需重新配置。
      </p>
      {/* AUDIT-012：确定性重载——刷新后从恢复后的服务端重新 hydration，
          既清空陈旧的服务端缓存，也重置本地设置。 */}
      <div className="flex justify-end">
        <Button size="sm" onClick={onReload}>
          刷新应用
        </Button>
      </div>
    </div>
  )
}

/** N186：独立自检报告（只读发现，不建恢复会话、不触发恢复）。 */
function VerifyReportPane({
  report,
  onBack,
}: {
  report: BackupVerifyReport
  onBack: () => void
}) {
  const findings: { key: keyof BackupVerifyReport['findings']; label: string }[] = [
    { key: 'checksumOk', label: 'SHA-256 校验和' },
    { key: 'manifestCountsMatch', label: 'manifest 计数一致' },
    { key: 'readable', label: '成员可读（SQLite integrity）' },
    { key: 'versionCompatible', label: '版本兼容' },
  ]
  return (
    <div className="flex flex-col gap-3" data-verify-report="">
      <div className="flex items-start gap-2.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3.5 py-2.5">
        {report.ok ? (
          <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-accent-text)]" />
        ) : (
          <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-danger)]" />
        )}
        <div className="min-w-0 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
            {report.ok ? '完整性自检通过' : '完整性自检发现问题'}
          </p>
          <p className="mt-0.5">本操作只读校验，未创建恢复会话、未修改任何文件。</p>
        </div>
      </div>

      <ul className="flex flex-col gap-1 text-xs">
        {findings.map((finding) => (
          <li key={finding.key} className="flex items-center justify-between gap-3" data-verify-finding={finding.key}>
            <span className="text-[var(--lumi-text-secondary)]">{finding.label}</span>
            {report.findings[finding.key] ? (
              <span className="flex items-center gap-1 text-[var(--lumi-accent-text)]">
                <CheckCircle2 aria-hidden className="size-3.5" />通过
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[var(--lumi-danger)]">
                <XCircle aria-hidden className="size-3.5" />未通过
              </span>
            )}
          </li>
        ))}
      </ul>

      {(report.issues.corruptFile.length > 0 ||
        report.issues.missingAttachment.length > 0 ||
        report.issues.versionIncompatible !== null) && (
        <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5 text-xs" data-verify-issues="">
          {report.issues.corruptFile.length > 0 && (
            <p className="text-[var(--lumi-danger)]">损坏/可疑成员：{report.issues.corruptFile.join('、')}</p>
          )}
          {report.issues.missingAttachment.length > 0 && (
            <p className="mt-1 text-[var(--lumi-danger)]">缺失附件：{report.issues.missingAttachment.join('、')}</p>
          )}
          {report.issues.versionIncompatible != null && (
            <p className="mt-1 text-[var(--lumi-danger)]">
              版本不兼容（{String(report.issues.versionIncompatible.field)}：备份{' '}
              {String(report.issues.versionIncompatible.backup)} / 当前{' '}
              {String(report.issues.versionIncompatible.current)}）。
            </p>
          )}
        </div>
      )}

      <div className="flex justify-end">
        <Button size="sm" variant="ghost" onClick={onBack}>
          返回
        </Button>
      </div>
    </div>
  )
}

export function RestoreWizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const jobs = useBackups()
  const previewMutation = useRestorePreviewMutation()
  const executeMutation = useRestoreExecuteMutation()
  const verifyMutation = useBackupVerifyMutation()

  const [step, setStep] = useState<Step>('select')
  const [selected, setSelected] = useState<SelectedSource | null>(null)
  const [preview, setPreview] = useState<RestorePreview | null>(null)
  // N187：逐对象冲突决策（path → 'skip'|'overwrite'；缺省 skip）。
  const [decisions, setDecisions] = useState<Record<string, 'skip' | 'overwrite'>>({})
  const [result, setResult] = useState<RestoreResult | null>(null)
  const [verifySource, setVerifySource] = useState<string>('')

  const reset = () => {
    setStep('select')
    setSelected(null)
    setPreview(null)
    setDecisions({})
    setResult(null)
    setVerifySource('')
    previewMutation.reset()
    executeMutation.reset()
    verifyMutation.reset()
  }

  const close = () => {
    onClose()
    // 关闭后再清状态，避免关闭动画期间内容闪烁
    window.setTimeout(reset, 0)
  }

  const pick = (picked: SelectedSource) => {
    setSelected(picked)
    setPreview(null)
    previewMutation.mutate(
      { source: picked.source, jobId: picked.jobId, fileName: picked.fileName },
      {
        onSuccess: (data) => {
          setPreview(data)
          setStep('preview')
        },
        // 失败也进入 preview 步骤：展示安全错误 + 「返回重选」
        onError: () => setStep('preview'),
      },
    )
  }

  // N186：仅校验——独立自检，不创建恢复会话、绝不触发恢复
  const verifyOnly = (jobId: string) => {
    const job = (jobs.data ?? []).find((item) => item.id === jobId)
    setVerifySource(job?.summary?.filename ?? jobId)
    verifyMutation.mutate(
      { source: 'local', jobId },
      { onSuccess: () => setStep('verify'), onError: () => setStep('verify') },
    )
  }

  const execute = (confirmation: string) => {
    if (!preview) return
    executeMutation.mutate(
      { restoreSessionId: preview.restoreSessionId, confirmation, decisions },
      {
        onSuccess: (data) => {
          // AUDIT-012：恢复成功后立即丢弃未落库的本地设置变更，
          // 防止陈旧本地值在重载前 PATCH 覆盖刚恢复的服务端设置。
          clearPendingSettingsSync()
          setResult(data)
          setStep('result')
        },
      },
    )
  }

  // AUDIT-012：确定性强制重载（比手工逐个无效化数十个查询更安全）。
  const reloadApp = () => {
    clearPendingSettingsSync()
    window.location.reload()
  }

  const previewFailed = previewMutation.isError
  const executeFailed = executeMutation.isError

  return (
    <Dialog
      open={open}
      onClose={executeMutation.isPending ? () => {} : close}
      title="从备份恢复"
      panelClassName="max-w-lg"
      footer={
        step === 'preview' && previewFailed ? (
          <div className="flex justify-end">
            <Button size="sm" variant="ghost" onClick={() => { setStep('select'); previewMutation.reset() }}>
              返回重选
            </Button>
          </div>
        ) : undefined
      }
    >
      {step === 'select' && (
        <SourcePicker localJobs={jobs.data ?? []} onPick={pick} onVerify={verifyOnly} onBack={close} />
      )}

      {step === 'verify' && (
        <>
          <p className="mb-3 text-xs text-[var(--lumi-text-tertiary)]">来源：{verifySource}</p>
          {verifyMutation.isPending && (
            <div role="status" aria-label="正在校验备份完整性" className="flex flex-col gap-2 py-2">
              <p className="flex items-center gap-2 text-sm text-[var(--lumi-text-secondary)]">
                <Loader2 aria-hidden className="size-4 animate-spin" />
                正在校验 checksum / manifest / 版本…
              </p>
              <Skeleton className="h-16 w-full" />
            </div>
          )}
          {!verifyMutation.isPending && verifyMutation.isError && (
            <div role="alert" className="flex flex-col gap-2">
              <p className="flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-danger)]">
                <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
                校验失败：{verifyMutation.error instanceof Error ? verifyMutation.error.message : '备份文件无效。'}
              </p>
              <div className="flex justify-end">
                <Button size="sm" variant="ghost" onClick={() => { setStep('select'); verifyMutation.reset() }}>
                  返回
                </Button>
              </div>
            </div>
          )}
          {!verifyMutation.isPending && !verifyMutation.isError && verifyMutation.data && (
            <VerifyReportPane
              report={verifyMutation.data}
              onBack={() => { setStep('select'); verifyMutation.reset() }}
            />
          )}
        </>
      )}

      {step !== 'select' && selected && (
        <p className="mb-3 text-xs text-[var(--lumi-text-tertiary)]">
          来源：{selected.label}
        </p>
      )}

      {(step === 'preview' || (previewMutation.isPending && step === 'select')) && (
        <>
          {previewMutation.isPending && (
            <div role="status" aria-label="正在校验备份文件" className="flex flex-col gap-2 py-2">
              <p className="flex items-center gap-2 text-sm text-[var(--lumi-text-secondary)]">
                <Loader2 aria-hidden className="size-4 animate-spin" />
                正在下载 / 校验 checksum 与 manifest…
              </p>
              <Skeleton className="h-16 w-full" />
            </div>
          )}
          {!previewMutation.isPending && previewFailed && (
            <div role="alert" className="flex flex-col gap-3">
              <p className="flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-danger)]">
                <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
                校验失败：{previewMutation.error instanceof Error ? previewMutation.error.message : '备份文件无效。'}
              </p>
              <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                可能原因：文件损坏（checksum 不匹配）、不是 LumiRSS 备份、版本过旧。
                原始备份文件未被修改或删除。
              </p>
            </div>
          )}
          {!previewMutation.isPending && preview && !previewFailed && (
            <PreviewPane
              preview={preview}
              onConfirm={() =>
                // N187：存在冲突对象 → 先进入冲突决策步骤（缺省 skip）。
                setStep(
                  (preview.conflicts?.length ?? 0) > 0 ? 'conflicts' : 'confirm',
                )
              }
              onCancel={close}
            />
          )}
        </>
      )}

      {step === 'conflicts' && preview && (
        <ConflictStep
          conflicts={preview.conflicts ?? []}
          decisions={decisions}
          onChange={(path, strategy) =>
            setDecisions((prev) => ({ ...prev, [path]: strategy }))
          }
          onCancel={close}
          onContinue={() => setStep('confirm')}
        />
      )}

      {step === 'confirm' && (
        <>
          {executeFailed && (
            <p role="alert" className="mb-3 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              恢复失败：{executeMutation.error instanceof Error ? executeMutation.error.message : '未知错误'}
              。当前状态安全备份已保留，数据未处于损坏中间态；可安全重试。
            </p>
          )}
          <ConfirmPane onConfirmed={execute} onCancel={close} busy={executeMutation.isPending} />
        </>
      )}

      {step === 'result' && result && <ResultPane result={result} onReload={reloadApp} />}
    </Dialog>
  )
}
