/** ApiSourceDetailDrawer — 单个 API 来源的详情抽屉。
 *
 * 五个 tab（ui/Tabs，Base UI 键盘导航）：
 * - 内容：概要（名称 / 地址 / 状态 / 更新频率 / 最近抓取）+ 启用开关；
 * - 抓取：分页设置（PATCH 保存）、结构变更预警（重新确认基线 / 写暂停
 *   恢复）、每日上限、每小时运行预算；
 * - 字段：字段映射编辑（PATCH 保存）+ 样本试映射与绑定；
 * - 日志：抓取状态字段 + 最近试抓结果（new302Api.last，从未试抓诚实
 *   显示）；
 * - 高级：凭据测试并轮换（write-only 掩码输入，不回显）、签名密钥
 *   轮换（管理员）、配置转移（导出明确标注不含秘密）。
 *
 * 契约：抽屉内不嵌套对话框/抽屉——原轮换 Dialog 改为面板内折叠
 * 二级视图；焦点 trap / Escape / 滚动锁由 DetailDrawer（Base UI）
 * 承担。 */

import { useEffect, useState, type ReactElement, type ReactNode } from 'react'
import { AlertCircle, ChevronDown, KeyRound, RefreshCw } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  new302Api,
  type ProbeResult,
} from '../../api/new301'
import {
  confirmApiSourceSchema,
  type ApiSource,
  type ApiSourcePaginationInput,
  type ApiSourceCredentialResult,
} from '../../api/client'
import {
  useRotateApiSourceCredentialMutation,
  useTestApiSourceCredentialMutation,
  useUpdateApiSourceMutation,
} from '../../api/queries'
import { errorText, NoteText, StatusLine, SubSection } from '../new271/panel'
import { Button } from '../ui/Button'
import { DetailDrawer } from '../ui/DetailDrawer'
import { Switch } from '../ui/Switch'
import { Tabs } from '../ui/Tabs'
import { cx } from '../ui/cx'
import { endpointHost, formatRelative, StatusBadge } from './api-source-shared'
import {
  EMPTY_FIELD_MAP,
  FIELD_MAP_FIELDS,
  type ApiSourceFieldMapState,
} from './field-map'
import { IntakeQuotaPanel, MappingSamplePanel, PaginationProbePanel, SchemaPausePanel } from './parts-a'
import { SigningKeyAdminPanel } from './parts-b'
import { TransferBundlePanel } from './parts-c'

const inputCls =
  'w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50'

const LAST_STATUS_LABELS: Record<string, string> = {
  ok: '成功',
  fetch_failed: '失败',
  subscribe_failed: '订阅失败',
}

/** ApiSource.pagination（宽松 Record）→ 受控 ApiSourcePaginationInput。 */
function toPaginationInput(raw: unknown): ApiSourcePaginationInput {
  if (raw === null || typeof raw !== 'object') return { mode: 'none' }
  const record = raw as Record<string, unknown>
  const mode =
    record.mode === 'page' || record.mode === 'cursor' ? record.mode : 'none'
  return {
    mode,
    ...(typeof record.page_param === 'string' ? { page_param: record.page_param } : {}),
    ...(typeof record.first_page === 'number' ? { first_page: record.first_page } : {}),
    ...(typeof record.cursor_path === 'string' ? { cursor_path: record.cursor_path } : {}),
    ...(typeof record.max_pages === 'number' ? { max_pages: record.max_pages } : {}),
    ...(typeof record.max_items === 'number' ? { max_items: record.max_items } : {}),
  }
}

/** 概要行。 */
function InfoRow({ label, children }: { label: string; children: ReactNode }): ReactElement {
  return (
    <div className="flex gap-2 text-xs">
      <dt className="w-20 shrink-0 text-[var(--lumi-text-tertiary)]">{label}</dt>
      <dd className="min-w-0 flex-1 break-all text-[var(--lumi-text-primary)]">{children}</dd>
    </div>
  )
}

/** 内容 tab：概要 + 启用开关。 */
function ContentTab({ source }: { source: ApiSource }): ReactElement {
  const update = useUpdateApiSourceMutation()
  return (
    <div className="flex flex-col gap-3" data-detail-tab="content">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-[var(--lumi-text-secondary)]">启用来源</span>
        <Switch
          checked={source.enabled}
          label={`启用 ${source.name}`}
          disabled={update.isPending}
          onCheckedChange={(checked) =>
            update.mutate({ uuid: source.uuid, patch: { enabled: checked } })
          }
        />
      </div>
      <dl className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3">
        <InfoRow label="名称">{source.name}</InfoRow>
        <InfoRow label="地址">
          <span title={source.endpoint}>{endpointHost(source.endpoint)}</span>
        </InfoRow>
        <InfoRow label="状态">
          <StatusBadge source={source} />
        </InfoRow>
        <InfoRow label="更新频率">≤ {source.maxRunsPerHour} 次 / 小时</InfoRow>
        <InfoRow label="最近抓取">
          {source.lastStatus === 'fetch_failed' && source.lastError
            ? `失败：${source.lastError}`
            : formatRelative(source.lastSuccessAt)}
        </InfoRow>
        <InfoRow label="创建于">{formatRelative(source.createdAt)}</InfoRow>
      </dl>
      {source.subscribeError != null && source.subscribeError !== '' && (
        <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          FreshRSS 自动订阅失败：{source.subscribeError}
        </p>
      )}
      {update.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {update.error instanceof Error ? update.error.message : '保存失败。'}
        </p>
      )}
    </div>
  )
}

/** 分页设置：读当前值 → 编辑 → PATCH 保存（有界：≤50 页 / ≤1000 条）。 */
function PaginationEditor({ source }: { source: ApiSource }): ReactElement {
  const [value, setValue] = useState<ApiSourcePaginationInput>(() =>
    toPaginationInput(source.pagination),
  )
  const update = useUpdateApiSourceMutation()

  const smallInputCls =
    'w-28 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]'

  return (
    <div className="flex flex-col gap-2" data-detail-pagination="">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
          模式
          <select
            aria-label={`分页模式 ${source.name}`}
            value={value.mode}
            onChange={(e) => {
              const mode = e.target.value as ApiSourcePaginationInput['mode']
              setValue({ mode, ...(mode === 'none' ? {} : { max_pages: 5, max_items: 200 }) })
            }}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
          >
            <option value="none">不分页</option>
            <option value="page">页码 ?page=N</option>
            <option value="cursor">游标 ?cursor=</option>
          </select>
        </label>
        {value.mode === 'page' && (
          <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
            页参数名
            <input
              aria-label={`页参数名 ${source.name}`}
              value={value.page_param ?? ''}
              onChange={(e) => setValue({ ...value, page_param: e.target.value })}
              className={smallInputCls}
              placeholder="page"
            />
          </label>
        )}
        {value.mode === 'cursor' && (
          <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
            游标路径
            <input
              aria-label={`游标路径 ${source.name}`}
              value={value.cursor_path ?? ''}
              onChange={(e) => setValue({ ...value, cursor_path: e.target.value })}
              className={smallInputCls}
              placeholder="meta.next"
            />
          </label>
        )}
        {value.mode !== 'none' && (
          <>
            <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
              最多页数
              <input
                aria-label={`最多页数 ${source.name}`}
                type="number"
                min={1}
                max={50}
                value={value.max_pages ?? 5}
                onChange={(e) =>
                  setValue({
                    ...value,
                    max_pages: Math.min(50, Math.max(1, Number(e.target.value) || 5)),
                  })
                }
                className={smallInputCls}
              />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
              最多条数
              <input
                aria-label={`最多条数 ${source.name}`}
                type="number"
                min={1}
                max={1000}
                value={value.max_items ?? 200}
                onChange={(e) =>
                  setValue({
                    ...value,
                    max_items: Math.min(1000, Math.max(1, Number(e.target.value) || 200)),
                  })
                }
                className={smallInputCls}
              />
            </label>
          </>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => update.mutate({ uuid: source.uuid, patch: { pagination: value } })}
          disabled={update.isPending}
          data-pagination-save=""
        >
          <RefreshCw aria-hidden className="size-3.5" />
          {update.isPending ? '保存中…' : '保存分页设置'}
        </Button>
        {update.isSuccess && (
          <span role="status" className="text-xs text-[var(--lumi-text-tertiary)]">
            已保存。
          </span>
        )}
        {update.isError && (
          <span role="alert" className="text-xs text-[var(--lumi-danger)]">
            {update.error instanceof Error ? update.error.message : '保存失败。'}
          </span>
        )}
      </div>
      {value.mode !== 'none' && (
        <NoteText>
          有界分页：最多 50 页 / 1000 条；中途失败时本次不发布任何条目，空页或游标异常如实停止。
        </NoteText>
      )}
    </div>
  )
}

/** 每小时运行预算（可调）+ 下次允许运行时间。 */
const BUDGET_OPTIONS = [1, 2, 4, 8, 12, 30, 60]

function BudgetBlock({ source }: { source: ApiSource }): ReactElement {
  const update = useUpdateApiSourceMutation()
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--lumi-text-tertiary)]"
      data-budget-block=""
    >
      <label className="flex items-center gap-1">
        每小时运行预算
        <select
          aria-label={`每小时运行预算 ${source.name}`}
          value={source.maxRunsPerHour}
          disabled={update.isPending}
          onChange={(e) =>
            update.mutate({
              uuid: source.uuid,
              patch: { maxRunsPerHour: Number(e.target.value) },
            })
          }
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-primary)]"
        >
          {BUDGET_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n} 次
            </option>
          ))}
        </select>
      </label>
      <span>
        下次允许运行：
        {source.nextAllowedRun != null && source.nextAllowedRun !== ''
          ? new Date(source.nextAllowedRun).toLocaleString()
          : '现在'}
      </span>
      <span className="text-[var(--lumi-text-secondary)]">遇限流将等待，不使用替代密钥规避。</span>
    </div>
  )
}

/** 结构漂移徽标 + 基线 diff + 重新确认（confirm-schema 复用点）。 */
function SchemaDriftPanel({ source }: { source: ApiSource }): ReactElement {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const confirm = useMutation({
    mutationFn: () => confirmApiSourceSchema(source.uuid),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['api-sources'] })
    },
  })
  const drift = source.schemaDrift
  const hasDrift =
    drift !== null &&
    drift !== undefined &&
    (drift.missing.length > 0 || drift.type_changed.length > 0)
  if (!source.confirmedSchema && !hasDrift) return <StatusLine tone="info">尚未确认结构基线。</StatusLine>
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
      >
        <ChevronDown
          aria-hidden
          className={cx('size-3 transition-transform duration-[var(--lumi-motion-fast)]', open && 'rotate-180')}
        />
        结构变更预警
        {hasDrift ? (
          <span className="flex items-center gap-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-danger-soft)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="size-3" />
            结构已变化
          </span>
        ) : (
          <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
            基线一致
          </span>
        )}
      </button>
      {open && (
        <div className="mt-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5 text-xs">
          {source.confirmedSchema && !hasDrift && (
            <p className="text-[var(--lumi-text-secondary)]">
              当前数据与确认基线一致（可选新增字段：{drift?.new_optional.length ?? 0}）。
            </p>
          )}
          {hasDrift && (
            <div className="flex flex-col gap-1 text-[var(--lumi-text-secondary)]">
              {(drift?.missing.length ?? 0) > 0 && (
                <p>
                  缺失必需字段：
                  <span className="font-mono text-[var(--lumi-danger)]">{drift?.missing.join('、')}</span>
                </p>
              )}
              {(drift?.type_changed.length ?? 0) > 0 && (
                <p>
                  类型变化：
                  <span className="font-mono text-[var(--lumi-danger)]">{drift?.type_changed.join('、')}</span>
                </p>
              )}
              {(drift?.new_optional.length ?? 0) > 0 && (
                <p className="text-[var(--lumi-text-tertiary)]">
                  新增可选字段（仅提示）：{drift?.new_optional.join('、')}
                </p>
              )}
            </div>
          )}
          <div className="mt-2 flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => confirm.mutate()} disabled={confirm.isPending}>
              <RefreshCw aria-hidden className="size-3.5" />
              {confirm.isPending ? '确认中…' : '修订映射并重新确认'}
            </Button>
            {confirm.isError && (
              <span role="alert" className="text-[var(--lumi-danger)]">
                {confirm.error instanceof Error ? confirm.error.message : '确认失败'}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/** 抓取 tab：分页设置 / 受限试抓 / 结构变更预警 / 写暂停恢复 / 每日上限 / 预算。 */
function FetchTab({ source }: { source: ApiSource }): ReactElement {
  return (
    <div className="flex flex-col gap-4" data-detail-tab="fetch">
      <SubSection id="detail-pagination" label="分页设置">
        <PaginationEditor source={source} />
      </SubSection>
      <SubSection id="detail-probe" label="受限试抓（≤5 页）">
        <PaginationProbePanel sourceUuid={source.uuid} />
      </SubSection>
      <SubSection id="detail-drift" label="抓取变更预警">
        <div className="flex flex-col gap-3">
          <SchemaDriftPanel source={source} />
          <SchemaPausePanel sourceUuid={source.uuid} />
        </div>
      </SubSection>
      <SubSection id="detail-quota" label="每日上限">
        <IntakeQuotaPanel sourceUuid={source.uuid} />
      </SubSection>
      <SubSection id="detail-budget" label="每小时运行预算">
        <BudgetBlock source={source} />
      </SubSection>
    </div>
  )
}

/** 字段映射编辑（PATCH 保存）。 */
function FieldMapEditor({ source }: { source: ApiSource }): ReactElement {
  const [value, setValue] = useState<ApiSourceFieldMapState>(() => ({
    ...EMPTY_FIELD_MAP,
    ...source.fieldMap,
  }))
  const update = useUpdateApiSourceMutation()
  return (
    <div className="flex flex-col gap-2" data-detail-fieldmap="">
      {FIELD_MAP_FIELDS.map((field) => (
        <div key={field.key} className="flex items-center gap-2">
          <label
            htmlFor={`detail-field-${field.key}`}
            className="w-20 shrink-0 text-xs text-[var(--lumi-text-secondary)]"
          >
            {field.label}
          </label>
          <input
            id={`detail-field-${field.key}`}
            value={value[field.key]}
            onChange={(e) => setValue((prev) => ({ ...prev, [field.key]: e.target.value }))}
            className={cx(inputCls, 'min-h-8 flex-1')}
          />
        </div>
      ))}
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => update.mutate({ uuid: source.uuid, patch: { fieldMap: value } })}
          disabled={update.isPending}
          data-fieldmap-save=""
        >
          <RefreshCw aria-hidden className="size-3.5" />
          {update.isPending ? '保存中…' : '保存字段映射'}
        </Button>
        {update.isError && (
          <span role="alert" className="text-xs text-[var(--lumi-danger)]">
            {update.error instanceof Error ? update.error.message : '保存失败。'}
          </span>
        )}
      </div>
      <NoteText>留空 = 不映射；缺失的 id/title 会被服务端如实拒绝。</NoteText>
    </div>
  )
}

/** 字段 tab：映射编辑 + 样本试映射。 */
function FieldsTab({ source }: { source: ApiSource }): ReactElement {
  return (
    <div className="flex flex-col gap-4" data-detail-tab="fields">
      <SubSection id="detail-fieldmap" label="字段映射">
        <FieldMapEditor source={source} />
      </SubSection>
      <SubSection id="detail-mapping-samples" label="样本试映射">
        <MappingSamplePanel sourceUuid={source.uuid} />
      </SubSection>
    </div>
  )
}

/** 日志 tab：抓取状态字段 + 最近试抓（脱敏，页 URL 只显示形状）。 */
function LogsTab({ source }: { source: ApiSource }): ReactElement {
  const [probe, setProbe] = useState<ProbeResult | null>(null)
  const [probeMissing, setProbeMissing] = useState(false)
  const [probeError, setProbeError] = useState('')

  useEffect(() => {
    // 重置语义由调用方以 key={source.uuid} 重挂载承担，这里只做取数。
    let cancelled = false
    new302Api
      .last(source.uuid)
      .then((result) => {
        if (!cancelled) setProbe(result)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (err !== null && typeof err === 'object' && 'status' in err && (err as { status: number }).status === 404) {
          setProbeMissing(true)
        } else {
          setProbeError(errorText(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [source.uuid])

  return (
    <div className="flex flex-col gap-3" data-detail-tab="logs">
      <dl className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3">
        <InfoRow label="上次结果">
          {source.lastStatus == null || source.lastStatus === ''
            ? '未运行'
            : (LAST_STATUS_LABELS[source.lastStatus] ?? source.lastStatus)}
        </InfoRow>
        <InfoRow label="最近错误">
          {source.lastError ?? '—'}
        </InfoRow>
        <InfoRow label="最近成功">{formatRelative(source.lastSuccessAt)}</InfoRow>
        <InfoRow label="下次允许运行">
          {source.nextAllowedRun != null && source.nextAllowedRun !== ''
            ? new Date(source.nextAllowedRun).toLocaleString()
            : '现在'}
        </InfoRow>
      </dl>
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3">
        <p className="text-xs font-medium text-[var(--lumi-text-primary)]">最近试抓</p>
        {probeError !== '' && (
          <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">{probeError}</p>
        )}
        {probeMissing && (
          <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">从未试抓。</p>
        )}
        {probe !== null && (
          <div className="mt-1 flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
            <p>
              {probe.pageCount} 页 / {probe.itemCount} 条 · 停止原因 {probe.stopReason}
              {probe.duplicatePages > 0 ? ` · 重复页 ${probe.duplicatePages}` : ''}
              {probe.gapPages > 0 ? ` · 缺页 ${probe.gapPages}` : ''}
            </p>
            <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
              {probe.pages.map((page) => `第 ${String(page.page)} 页`).join('，')}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

/** 凭据测试并轮换（面板内二级折叠视图，不嵌套弹窗；write-only 掩码）。 */
function CredentialRotateSection({ source }: { source: ApiSource }): ReactElement {
  const [open, setOpen] = useState(false)
  const [credential, setCredential] = useState('')
  const [testResult, setTestResult] = useState<{
    ok: boolean
    statusClass: string
    latencyMs: number
  } | null>(null)
  const test = useTestApiSourceCredentialMutation()
  const rotate = useRotateApiSourceCredentialMutation()

  const canRun = credential.trim().length >= 16
  const TEST_STATUS_LABELS: Record<string, string> = {
    ok: '端点正常',
    rate_limited: '端点限流中（可达）',
    http_error: '端点返回错误',
    network_error: '端点不可达',
    invalid_payload: '端点响应不是 JSON',
    invalid_credential: '凭据格式不合法',
  }

  const closeSection = () => {
    setCredential('')
    setTestResult(null)
    test.reset()
    rotate.reset()
    setOpen(false)
  }

  const runRotate = () => {
    rotate.mutate(
      { uuid: source.uuid, newCredential: credential.trim() },
      {
        onSuccess: () => {
          setCredential('')
          setTestResult(null)
        },
      },
    )
  }

  return (
    <div data-credential-rotate="">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-1.5 py-1 text-xs font-medium text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
      >
        <KeyRound aria-hidden className="size-3.5" />
        测试并轮换凭据
      </button>
      {open && (
        <div className="mt-1.5 flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5">
          <p className="text-[11px] leading-relaxed text-[var(--lumi-text-secondary)]">
            轮换会先做一次<strong>只读预演</strong>（结构校验 + 端点探测，5 秒上限）：
            预演失败则当前凭据原样保留；成功后新凭据立即生效，旧 Atom 地址保留
            <strong> 10 分钟</strong>宽限。响应全程脱敏，凭据输入后不回显。
          </p>
          <label htmlFor={`rotate-credential-${source.uuid}`} className="block text-xs font-medium text-[var(--lumi-text-primary)]">
            新凭据（16–128 位字母/数字/连字符/下划线）
          </label>
          <input
            id={`rotate-credential-${source.uuid}`}
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={credential}
            onChange={(e) => setCredential(e.target.value)}
            className={inputCls}
          />
          {testResult !== null && (
            <p
              role="status"
              className={cx(
                'rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2 text-xs',
                testResult.ok ? 'text-[var(--lumi-category-green)]' : 'text-[var(--lumi-danger)]',
              )}
              data-credential-test-result=""
            >
              预演结果（脱敏）：{testResult.ok ? '通过' : '未通过'} ·{' '}
              {TEST_STATUS_LABELS[testResult.statusClass] ?? testResult.statusClass} · {testResult.latencyMs} ms
            </p>
          )}
          {test.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {test.error instanceof Error ? test.error.message : '预演失败。'}
            </p>
          )}
          {rotate.isSuccess && (
            <p
              role="status"
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]"
              data-rotate-ok=""
            >
              {rotate.data.note ?? '已轮换。旧 Atom 地址保留 10 分钟，请尽快替换 FreshRSS 订阅。'}
            </p>
          )}
          {rotate.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {rotate.error instanceof Error ? rotate.error.message : '轮换失败。'}
            </p>
          )}
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setTestResult(null)
                test.mutate(
                  { uuid: source.uuid, newCredential: credential.trim() },
                  {
                    onSuccess: (result: ApiSourceCredentialResult) =>
                      setTestResult({
                        ok: result.ok,
                        statusClass: result.statusClass,
                        latencyMs: result.latencyMs,
                      }),
                    onError: () => setTestResult(null),
                  },
                )
              }}
              disabled={!canRun || test.isPending || rotate.isPending}
            >
              {test.isPending ? '测试中…' : '仅测试（预演）'}
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={runRotate}
              disabled={!canRun || rotate.isPending || test.isPending}
              data-rotate-confirm=""
            >
              {rotate.isPending ? '轮换中…' : '测试并轮换'}
            </Button>
            <Button size="sm" variant="ghost" onClick={closeSection}>
              收起
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

/** 高级 tab：凭据轮换（write-only）+ 签名密钥轮换（管理员）+ 配置转移。 */
function AdvancedTab({ source }: { source: ApiSource }): ReactElement {
  return (
    <div className="flex flex-col gap-4" data-detail-tab="advanced">
      <CredentialRotateSection source={source} />
      <SubSection id="detail-signing-keys" label="签名密钥轮换（管理员）">
        <SigningKeyAdminPanel />
      </SubSection>
      <SubSection id="detail-transfer" label="配置转移（不含秘密）">
        <TransferBundlePanel />
      </SubSection>
      <NoteText>
        配置导出只包含结构与映射，不含任何秘密与运行状态；导入响应也不回显凭据。
      </NoteText>
    </div>
  )
}

type DetailTab = 'content' | 'fetch' | 'fields' | 'logs' | 'advanced'

export function ApiSourceDetailDrawer({
  source,
  open,
  onClose,
}: {
  source: ApiSource
  open: boolean
  onClose: () => void
}): ReactElement {
  // 初始固定「内容」：抽屉关闭即卸载，重开总是从这里开始。
  const [tab, setTab] = useState<DetailTab>('content')

  return (
    <DetailDrawer
      open={open}
      onClose={onClose}
      title={`来源详情：${source.name}`}
      id="api-source-detail"
    >
      <Tabs
        aria-label="来源详情分区"
        value={tab}
        onValueChange={setTab}
        options={[
          { value: 'content', label: '内容' },
          { value: 'fetch', label: '抓取' },
          { value: 'fields', label: '字段' },
          { value: 'logs', label: '日志' },
          { value: 'advanced', label: '高级' },
        ]}
        panels={{
          content: <ContentTab source={source} />,
          fetch: <FetchTab source={source} />,
          fields: <FieldsTab source={source} />,
          logs: <LogsTab key={source.uuid} source={source} />,
          advanced: <AdvancedTab source={source} />,
        }}
      />
    </DetailDrawer>
  )
}
