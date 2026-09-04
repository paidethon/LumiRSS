/** OperationsSettingsSection — 0018 Gate 9：设置 → 账户与服务。
 *
 * 用 /api/v1/operations/status 的真实结果渲染 LumiRSS / FreshRSS / RSSHub /
 * Backup 状态。没有真实数据时显示「未配置 / 连接失败」，绝不伪造指标。
 * 状态不能只靠颜色：每个状态都带文字标签。
 */

import { AlertCircle, CheckCircle2, Database, Rss, Satellite, Server } from 'lucide-react'
import { useOperationsStatus } from '../../api/queries'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

const LABELS: Record<string, string> = {
  healthy: '正常',
  unconfigured: '未配置',
  unauthenticated: '认证失败',
  unavailable: '连接失败',
}

function StatusDot({ status }: { status: string }) {
  return (
    <span
      className={cx(
        'size-2.5 shrink-0 rounded-full',
        status === 'healthy' ? 'bg-[var(--lumi-accent)]' : 'bg-[var(--lumi-text-tertiary)]',
      )}
      aria-hidden="true"
    />
  )
}

function Row({
  icon,
  name,
  detail,
  status,
  pending,
}: {
  icon: React.ReactNode
  name: string
  detail: string
  status: string
  pending?: string | null
}) {
  return (
    <div className="flex items-center gap-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3.5 py-2.5">
      {icon}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]">{name}</p>
        <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          {detail}
        </p>
      </div>
      {pending != null && (
        <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] px-2 py-0.5 text-[11px] text-[var(--lumi-accent-text)]">
          {pending}
        </span>
      )}
      <span
        role="status"
        className="flex shrink-0 items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]"
      >
        <StatusDot status={status} />
        {LABELS[status] ?? status}
      </span>
    </div>
  )
}

export function OperationsSettingsSection() {
  const status = useOperationsStatus()

  if (status.isError) {
    return (
      <p role="alert" className="flex items-start gap-1.5 text-sm text-[var(--lumi-danger)]">
        <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
        无法获取服务状态：{status.error instanceof Error ? status.error.message : '请稍后重试。'}
      </p>
    )
  }

  if (status.data === undefined) {
    return (
      <div className="flex flex-col gap-2 py-1" aria-label="正在加载服务状态">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    )
  }

  const data = status.data
  const freshrss = data.freshrss
  const rsshub = data.rsshub
  const backup = data.backup

  const freshrssDetail = freshrss.status === 'unconfigured'
    ? '尚未配置 FreshRSS 连接。'
    : typeof freshrss.latencyMs === 'number'
      ? `延迟 ${freshrss.latencyMs} ms`
      : ''

  const rsshubDetail = rsshub.status === 'unconfigured'
    ? '尚未配置 RSSHub 实例。'
    : typeof rsshub.latencyMs === 'number'
      ? `延迟 ${rsshub.latencyMs} ms`
      : ''

  const lastBackup = backup.lastBackup
  const backupDetail = backup.webdavConfigured
    ? 'WebDAV 已配置'
    : 'WebDAV 未配置'
  const backupPending = lastBackup?.status === 'succeeded' && lastBackup.finishedAt
    ? `上次成功 ${new Date(lastBackup.finishedAt).toLocaleString()}`
    : null

  return (
    <div className="flex flex-col gap-3 py-1">
      <Row
        icon={<Server aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
        name="LumiRSS"
        detail={`版本 ${data.lumi.version}`}
        status="healthy"
      />
      <Row
        icon={<Database aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
        name="本地数据（lumi.sqlite）"
        detail={`状态 ${LABELS[data.sqlite.status] ?? data.sqlite.status}`}
        status={data.sqlite.status === 'healthy' ? 'healthy' : 'unavailable'}
      />
      <Row
        icon={<Rss aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
        name="FreshRSS"
        detail={freshrssDetail}
        status={freshrss.status}
      />
      <Row
        icon={<Satellite aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
        name="RSSHub"
        detail={rsshubDetail}
        status={rsshub.status}
        pending={rsshub.pendingConfigCount > 0 ? `${rsshub.pendingConfigCount} 项待生效` : null}
      />
      <Row
        icon={<CheckCircle2 aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
        name="备份"
        detail={backupDetail}
        status={backup.webdavConfigured ? 'healthy' : 'unconfigured'}
        pending={backupPending}
      />
      <p className="text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
        FreshRSS / RSSHub 状态来自服务端真实探测；RSSHub 不可用不影响已抓取内容的阅读。
        详细配置请在「RSSHub」「订阅与来源」「备份与恢复」分类中管理。
      </p>
    </div>
  )
}
