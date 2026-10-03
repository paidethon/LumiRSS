/** OperationsSettingsSection — 设置 → 服务（R03 账户/服务拆分）。
 *
 * 用 /api/v1/operations/status 的真实探测结果 + /operations/diagnostics
 * 的配置存在性布尔渲染各服务状态。状态语义五态（取真实证据的最高档，
 * 绝不拔高）：
 * - 尚未检查：后端没有该服务的探测端点，或连接未配置；
 * - 进程存活：仅证明本体活着；
 * - 接口可达：网络层探测通过（RSSHub /healthz）；
 * - 认证成功：探测含凭据校验且通过（FreshRSS ClientLogin 200）；
 * - 业务可用：该服务的业务能力实测可用（BFF/本地存储/RAG）；
 * - 错误：探测失败（连接失败 / 认证失败 / 核心存储异常）。
 * 状态不能只靠颜色：每行都有文字标签；颜色只用语义 token。
 * AI / 邮件 / Obsidian / WebDAV 目前没有服务端健康探测 → 如实显示
 * 「尚未检查」，只给配置存在性（诊断包布尔，绝不含秘密值）。
 * 深度运维信息（进程内存 / 调度任务）在管理台，仅管理员可见。
 */

import { useState } from 'react'
import { AlertCircle, CheckCircle2, Bot, Database, Mail, NotebookText, Rss, Satellite, Server } from 'lucide-react'
import { useDiagnostics, useOperationsStatus, useRagStatus } from '../../api/queries'
import { formatTimestamp } from '../../lib/date-format'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { SettingsRow } from '../ui/SettingsRow'
import { cx } from '../ui/cx'

/** 服务状态五态 + 错误态（真实证据的最高档，绝不拔高）。 */
type ProbeState = 'unchecked' | 'alive' | 'reachable' | 'authenticated' | 'usable' | 'error'

const STATE_LABELS: Record<ProbeState, string> = {
  unchecked: '尚未检查',
  alive: '进程存活',
  reachable: '接口可达',
  authenticated: '认证成功',
  usable: '业务可用',
  error: '错误',
}

function StatusChip({ state }: { state: ProbeState }) {
  return (
    <span
      role="status"
      className="flex shrink-0 items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]"
    >
      <span
        className={cx(
          'size-2.5 shrink-0 rounded-full',
          // FIX-294：forced-colors 下纯背景状态点不可见——CanvasText 保底。
          state === 'error'
            ? 'bg-[var(--lumi-danger)] forced-colors:bg-[CanvasText]'
            : state === 'unchecked'
              ? 'bg-[var(--lumi-text-tertiary)] forced-colors:bg-[CanvasText]'
              : 'bg-[var(--lumi-accent)] forced-colors:bg-[CanvasText]',
        )}
        aria-hidden="true"
      />
      {STATE_LABELS[state]}
    </span>
  )
}

function ServiceRow({
  icon,
  name,
  detail,
  state,
  pending,
  diagnosis,
}: {
  icon: React.ReactNode
  name: string
  detail: string
  state: ProbeState
  pending?: string | null
  diagnosis?: React.ReactNode
}) {
  return (
    <SettingsRow
      label={name}
      help={detail}
      details={diagnosis}
      className="border-t border-[var(--lumi-separator)] first:border-t-0"
    >
      {pending != null && (
        <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] px-2 py-0.5 text-[11px] text-[var(--lumi-accent-text)]">
          {pending}
        </span>
      )}
      {icon}
      <StatusChip state={state} />
    </SettingsRow>
  )
}

/** 最后检查 + 延迟 + 错误类型的简短诊断行（有真实值才显示）。 */
function probeDiagnosis(lastCheckedAt: string | null | undefined, latencyMs?: number | null, errorType?: string | null): React.ReactNode {
  const parts: string[] = []
  if (typeof lastCheckedAt === 'string' && lastCheckedAt !== '') {
    parts.push(`最后检查 ${formatTimestamp(lastCheckedAt)}`)
  }
  if (typeof latencyMs === 'number') parts.push(`延迟 ${latencyMs} ms`)
  if (typeof errorType === 'string' && errorType !== '') parts.push(`错误类型 ${errorType}`)
  return parts.length > 0 ? <span>{parts.join(' · ')}</span> : undefined
}

export function OperationsSettingsSection() {
  const status = useOperationsStatus()
  const diag = useDiagnostics()
  const rag = useRagStatus()

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
  const presence = diag.data?.configPresence

  const rows: React.ReactNode[] = []

  // Lumi BFF：本次请求成功即业务可用；lumi degraded = 核心存储异常。
  const lumiDegraded = data.lumi.status !== 'healthy'
  rows.push(
    <ServiceRow
      key="lumi"
      icon={<Server aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
      name="Lumi 服务"
      detail={lumiDegraded ? `版本 ${data.lumi.version}；核心存储异常，服务降级。` : `版本 ${data.lumi.version}`}
      state={lumiDegraded ? 'error' : 'usable'}
    />,
  )

  const sqliteState: ProbeState = data.sqlite.status === 'healthy' ? 'usable' : 'error'
  rows.push(
    <ServiceRow
      key="sqlite"
      icon={<Database aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
      name="本地数据"
      detail={data.sqlite.status === 'healthy' && data.sqlite.schemaVersion != null ? `schema v${data.sqlite.schemaVersion}` : '数据库不可用。'}
      state={sqliteState}
      diagnosis={probeDiagnosis(data.sqlite.lastCheckedAt, data.sqlite.latencyMs, data.sqlite.error?.type ?? null)}
    />,
  )

  // FreshRSS：ClientLogin 200 = 认证成功（业务级抓取另行由订阅刷新验证）。
  const freshrss = data.freshrss
  const freshrssState: ProbeState =
    !freshrss.configured || freshrss.status === 'unconfigured'
      ? 'unchecked'
      : freshrss.status === 'healthy'
        ? 'authenticated'
        : freshrss.status === 'unauthenticated'
          ? 'reachable'
          : 'error'
  rows.push(
    <ServiceRow
      key="freshrss"
      icon={<Rss aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
      name="FreshRSS"
      detail={
        freshrssState === 'unchecked'
          ? '尚未配置连接。'
          : freshrss.status === 'unauthenticated'
            ? '服务可达，但凭据校验失败。'
            : '连接与凭据校验通过。'
      }
      state={freshrssState}
      diagnosis={probeDiagnosis(freshrss.lastCheckedAt, freshrss.latencyMs, freshrss.error?.type ?? null)}
    />,
  )

  // RSSHub：/healthz 200 = 接口可达（无鉴权、不证明路由业务可用）。
  const rsshub = data.rsshub
  const rsshubState: ProbeState =
    !rsshub.configured || rsshub.status === 'unconfigured'
      ? 'unchecked'
      : rsshub.status === 'healthy'
        ? 'reachable'
        : 'error'
  rows.push(
    <ServiceRow
      key="rsshub"
      icon={<Satellite aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
      name="RSSHub"
      detail={rsshubState === 'unchecked' ? '尚未配置实例。' : '健康检查通过。'}
      state={rsshubState}
      pending={rsshub.pendingConfigCount > 0 ? `${rsshub.pendingConfigCount} 项待生效` : null}
      diagnosis={probeDiagnosis(rsshub.lastCheckedAt, rsshub.latencyMs, rsshub.error?.type ?? null)}
    />,
  )

  // RAG：真实业务状态（客户端契约字段：enabled/chunks/lastError）。
  const ragStatus = rag.data
  const ragState: ProbeState =
    rag.isError || (ragStatus?.lastError != null && ragStatus.lastError !== '')
      ? 'error'
      : ragStatus === undefined
        ? 'unchecked'
        : !ragStatus.enabled
          ? 'unchecked'
          : 'alive'
  rows.push(
    <ServiceRow
      key="rag"
      icon={<CheckCircle2 aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
      name="语义索引"
      detail={
        ragStatus === undefined
          ? rag.isError
            ? '状态获取失败，请稍后重试。'
            : '状态获取中。'
          : !ragStatus.enabled
            ? '未启用。可在「AI」分类开启。'
            : `已启用，索引 ${ragStatus.chunks} 块。`
      }
      state={ragState}
      diagnosis={ragStatus?.lastError ? <span>{ragStatus.lastError}</span> : undefined}
    />,
  )

  // 无服务端健康探测的能力：只给配置存在性布尔（诊断包），如实「尚未检查」。
  rows.push(
    <ServiceRow
      key="ai"
      icon={<Bot aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
      name="AI 提供方"
      detail={presence === undefined ? '配置状态未知。' : presence.aiKey ? '密钥已配置；尚无服务端健康探测。' : '密钥未配置。'}
      state="unchecked"
      diagnosis={<span>实际可用性以首次 AI 调用结果为准（摘要 / 翻译）。</span>}
    />,
  )
  rows.push(
    <ServiceRow
      key="mail"
      icon={<Mail aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
      name="邮件收取"
      detail={presence === undefined ? '配置状态未知。' : presence.imap ? 'IMAP 已配置；尚无服务端健康探测。' : 'IMAP 未配置。'}
      state="unchecked"
      diagnosis={<span>连接质量以下次收信为准。</span>}
    />,
  )
  rows.push(
    <ServiceRow
      key="obsidian"
      icon={<NotebookText aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
      name="Obsidian 库"
      detail={presence === undefined ? '配置状态未知。' : presence.obsidian ? '库目录已配置。' : '库目录未配置。'}
      state="unchecked"
      diagnosis={<span>写入是否成功以导出操作回执为准。</span>}
    />,
  )

  // 备份：WebDAV 只有配置布尔 + 最近一次真实任务，不做假健康探测。
  const backup = data.backup
  const lastBackup = backup.lastBackup
  rows.push(
    <ServiceRow
      key="backup"
      icon={<CheckCircle2 aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />}
      name="备份"
      detail={backup.webdavConfigured ? 'WebDAV 已配置。' : 'WebDAV 未配置。'}
      state="unchecked"
      pending={
        lastBackup?.status === 'succeeded' && lastBackup.finishedAt
          ? `上次成功 ${formatTimestamp(lastBackup.finishedAt)}`
          : null
      }
      diagnosis={
        <span>
          {lastBackup != null
            ? `最近一次备份：${lastBackup.status === 'succeeded' ? '成功' : lastBackup.status === 'failed' ? '失败' : (lastBackup.status ?? '未知')}。`
            : '尚无备份记录。'}{' '}
          管理入口在「数据控制」。
        </span>
      }
    />,
  )

  return (
    <div className="flex flex-col gap-3 py-1">
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3.5 py-1">
        {rows}
      </div>
      <p className="text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
        状态来自服务端真实探测，按账户隔离；运维详情在管理台，仅管理员可见。
        RSSHub 不可用不影响已抓取内容的阅读。
      </p>
      <DiagnosticsExport />
    </div>
  )
}

/** F039：脱敏诊断包导出（预览字段列表 → 确认 → 下载 JSON）。
 * 预览展示与下载同一份数据形状；响应只有布尔/计数，绝不含秘密值。 */
function DiagnosticsExport() {
  const diag = useDiagnostics()
  const [previewing, setPreviewing] = useState(false)

  function download() {
    if (diag.data === undefined) return
    const blob = new Blob([JSON.stringify(diag.data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `lumirss-diagnostics-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mt-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5" data-lumi-diagnostics="">
      <p className="text-xs font-medium text-[var(--lumi-text-primary)]">诊断包（脱敏）</p>
      {previewing && diag.data ? (
        <>
          <ul className="mt-1.5 flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
            <li>· 版本 / schema 版本 / 认证模式 / 运行时长</li>
            <li>· 依赖状态：{diag.data.deps.map((dep) => dep.name).join('、')}（仅状态）</li>
            <li>· 近 24h 错误计数（按类型）</li>
            <li>· 配置存在性：freshrss / rsshub / ai_key / imap / obsidian（仅是/否）</li>
            <li>· 计数：订阅 {diag.data.counts.feeds} · 索引条目 {diag.data.counts.entriesIndexed} · 库条目 {diag.data.counts.libraryItems}</li>
          </ul>
          <div className="mt-1.5 flex gap-2">
            <Button size="sm" variant="primary" onClick={download}>确认下载 JSON</Button>
            <Button size="sm" variant="ghost" onClick={() => setPreviewing(false)}>取消</Button>
          </div>
        </>
      ) : (
        <Button size="sm" variant="secondary" className="mt-1" onClick={() => setPreviewing(true)} disabled={diag.isPending}>
          导出诊断包
        </Button>
      )}
    </div>
  )
}
