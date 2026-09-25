/** W3 订阅工具面板集合（从订阅行菜单进入）。
 *
 * - F044 更换订阅地址向导（校验→影响清单→执行；诚实文案）；
 * - F045 内容过滤面板（服务端规则 CRUD + 试跑 + 临时显示被屏蔽）；
 * - F046 静音列表面板（来源+截止+提前解除；过期不显示）；
 * - F048 正文策略 / F055 阅读外观（per-source 覆盖）；
 * - F049 导入记录 / F050 维护检查台。
 * 复用 ui/ 原语（Dialog/Menu/Button），语义 token，430px 可用。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, RefreshCw, Trash2 } from 'lucide-react'
import {
  addReviewQueueItem,
  createFeedFilterRule,
  deleteFeedFilterRule,
  listAnnotations,
  listFeedFilterRules,
  listImportBatches,
  type ImportBatch,
  listReadingProgress,
  listReviewQueue,
  completeReviewQueueItem,
  postponeReviewQueueItem,
  migrateSubscription,
  retryImportBatch,
  runHealthCheck,
  trialFeedFilterRule,
  type ApiError,
  type HealthCheckItem,
} from '../api/client'
import type { FeedPreviewMetadata, RedirectHop } from '../api/types'
import { listSourceOverrides, previewFeed, setSourceOverride } from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { EmptyState } from './ui/EmptyState'
import { Switch } from './ui/Switch'
import { cx } from './ui/cx'
import { dateTimeFormatter } from '../lib/date-format'
import { useAppSettings } from '../store/app-settings'

const inputCls =
  'w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'

function errMsg(error: unknown): string {
  return error instanceof Error ? error.message : '请稍后重试。'
}

function isApiError(error: unknown): error is ApiError {
  return error instanceof Error && error.name === 'ApiError'
}

/** N035：重定向链视图 — 每跳掩码 URL + 状态；多跳时给最终域名，
 * 失败变体把「请求从未发出 / 未完成」的跳（status=null）标为失败跳。
 * url 的 query 凭据值已由服务端掩码，这里不再自行改写。 */
function RedirectChainView({
  hops,
  variant,
}: {
  hops: RedirectHop[]
  variant: 'success' | 'failure'
}) {
  const last = hops[hops.length - 1] ?? null
  let finalHost: string | null = null
  if (variant === 'success' && last !== null) {
    try {
      finalHost = new URL(last.url).hostname
    } catch {
      finalHost = null
    }
  }
  return (
    <div
      role="group"
      aria-label="重定向链"
      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5 text-xs"
    >
      <p className="font-medium text-[var(--lumi-text-primary)]">
        重定向链（{hops.length} 跳）
        {variant === 'success' && hops.length > 1 ? ' —— 该地址发生了重定向' : ''}
      </p>
      <ol className="mt-1.5 flex flex-col gap-1">
        {hops.map((hop, index) => {
          const failedHop = hop.status === null
          return (
            <li key={`${hop.url}-${index}`} className="flex min-w-0 items-start gap-1.5">
              <span aria-hidden className="shrink-0 text-[var(--lumi-text-tertiary)]">
                {index + 1}.
              </span>
              <span className="min-w-0 flex-1">
                <span
                  className={cx(
                    'block break-all font-mono text-[11px]',
                    failedHop && variant === 'failure'
                      ? 'text-[var(--lumi-danger)]'
                      : 'text-[var(--lumi-text-secondary)]',
                  )}
                >
                  {hop.url}
                </span>
                <span className="block text-[11px] text-[var(--lumi-text-tertiary)]">
                  {hop.status === null
                    ? variant === 'failure'
                      ? '失败跳：请求未完成（未发出或被拒绝）'
                      : '未记录状态'
                    : `HTTP ${hop.status}`}
                  {hop.final ? ' · 最终地址' : ''}
                </span>
              </span>
            </li>
          )
        })}
      </ol>
      {finalHost !== null && (
        <p className="mt-1.5 text-[var(--lumi-text-secondary)]">最终域名：{finalHost}</p>
      )}
    </div>
  )
}

// ---- F044 更换订阅地址向导 --------------------------------------------------

export interface MigrateDialogProps {
  open: boolean
  onClose: () => void
  subscriptionRef: string
  feedUrl: string
  title: string
}

export function MigrateSubscriptionDialog({ open, onClose, subscriptionRef, feedUrl, title }: MigrateDialogProps) {
  const queryClient = useQueryClient()
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [newUrl, setNewUrl] = useState('')
  const [previewError, setPreviewError] = useState<Error | null>(null)
  const [previewData, setPreviewData] = useState<FeedPreviewMetadata | null>(null)
  const [result, setResult] = useState<Awaited<ReturnType<typeof migrateSubscription>> | null>(null)
  const previewMutation = useMutation({
    mutationFn: () => previewFeed(newUrl.trim()),
    onSuccess: (metadata) => {
      setPreviewError(null)
      setPreviewData(metadata)
      setStep(2)
    },
    onError: (error) => {
      setPreviewData(null)
      setPreviewError(error as Error)
    },
  })
  const migrateMutation = useMutation({
    mutationFn: () => migrateSubscription(subscriptionRef, newUrl.trim()),
    onSuccess: async (data) => {
      setResult(data)
      setStep(3)
      await queryClient.invalidateQueries({ queryKey: ['subscriptions'] })
    },
  })

  useEffect(() => {
    if (open) {
      setStep(1)
      setNewUrl('')
      setPreviewError(null)
      setPreviewData(null)
      setResult(null)
    }
  }, [open])

  // N035：成功预览 / 校验失败两条路径都取重定向链（服务端已掩码 query）。
  // 成功侧单跳链 = 未发生重定向，不渲染该区块（避免噪音）；失败侧以
  // 服务端是否附链为准（仅多跳或存在失败跳时服务端才附）。
  const successRedirects = previewData?.redirectChain ?? null
  const successChain =
    successRedirects !== null && successRedirects.length > 1 ? successRedirects : null
  const failureChain =
    previewError !== null && isApiError(previewError) ? previewError.redirectChain : null

  return (
    <Dialog open={open} onClose={onClose} title={`更换订阅地址 — ${title}`}>
      {step === 1 && (
        <div className="flex flex-col gap-3">
          <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">当前地址：{feedUrl}</p>
          <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
            新地址
            <input
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="https://…"
              className={inputCls}
              aria-label="新订阅地址"
            />
          </label>
          {newUrl.trim() === feedUrl && (
            <p role="alert" className="flex items-center gap-1.5 text-xs text-[var(--lumi-danger)]">
              <AlertCircle aria-hidden className="size-3.5" /> 新地址与当前地址相同。
            </p>
          )}
          {previewError && (
            <>
              <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
                {errMsg(previewError)}
              </p>
              {failureChain !== null && <RedirectChainView hops={failureChain} variant="failure" />}
            </>
          )}
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={onClose}>取消</Button>
            <Button
              size="sm"
              variant="primary"
              disabled={newUrl.trim() === '' || newUrl.trim() === feedUrl || previewMutation.isPending}
              onClick={() => previewMutation.mutate()}
            >
              <RefreshCw aria-hidden className="size-3.5" />
              {previewMutation.isPending ? '校验中…' : '校验并继续'}
            </Button>
          </div>
        </div>
      )}
      {step === 2 && (
        <div className="flex flex-col gap-3">
          <p className="flex items-center gap-1.5 text-xs text-[var(--lumi-success, var(--lumi-text-primary))]">
            <CheckCircle2 aria-hidden className="size-3.5" /> 新地址可达且为有效 feed。
          </p>
          {successChain !== null && <RedirectChainView hops={successChain} variant="success" />}
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            <p className="font-medium text-[var(--lumi-text-primary)]">迁移前请了解：</p>
            <ul className="mt-1.5 list-disc pl-4">
              <li>FreshRSS 不支持原位改 URL——将新建订阅。</li>
              <li>已读/收藏状态不可迁移；旧条目仍可读。</li>
              <li>Lumi 备注/覆盖/静音设置会复制到新订阅。</li>
              <li>旧订阅保留不删除；确认新源正常后可自行退订。</li>
            </ul>
          </div>
          {migrateMutation.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">{errMsg(migrateMutation.error)}</p>
          )}
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setStep(1)}>上一步</Button>
            <Button
              size="sm"
              variant="primary"
              disabled={migrateMutation.isPending}
              onClick={() => migrateMutation.mutate()}
            >
              {migrateMutation.isPending ? '迁移中…' : '确认迁移'}
            </Button>
          </div>
        </div>
      )}
      {step === 3 && result && (
        <div className="flex flex-col gap-3">
          <p role="status" className="text-sm text-[var(--lumi-text-primary)]">迁移完成。</p>
          <ul className="list-disc pl-4 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            <li>备注随迁：{result.copiedNotes ? '是' : '无备注需要复制'}</li>
            <li>覆盖/静音随迁：{result.copiedOverrides ? '是' : '无需要复制'}</li>
            <li>{result.note}</li>
          </ul>
          <div className="flex justify-end">
            <Button size="sm" variant="primary" onClick={onClose}>完成</Button>
          </div>
        </div>
      )}
    </Dialog>
  )
}

// ---- F045 内容过滤面板 -------------------------------------------------------

export interface FilterRulesDialogProps {
  open: boolean
  onClose: () => void
  feedUrl: string
  title: string
}

export function FilterRulesDialog({ open, onClose, feedUrl, title }: FilterRulesDialogProps) {
  const queryClient = useQueryClient()
  const settings = useAppSettings((s) => s.settings)
  const updateSettings = useAppSettings((s) => s.update)
  const rulesQuery = useQuery({
    queryKey: ['feed-filter-rules', feedUrl],
    queryFn: () => listFeedFilterRules(feedUrl),
    enabled: open,
  })
  const [field, setField] = useState<'title' | 'author'>('title')
  const [op, setOp] = useState<'contains' | 'equals'>('contains')
  const [value, setValue] = useState('')
  const [trialTitle, setTrialTitle] = useState('')
  const createMutation = useMutation({
    mutationFn: () => createFeedFilterRule({ feedUrl, field, op, value: value.trim() }),
    onSuccess: async () => {
      setValue('')
      await queryClient.invalidateQueries({ queryKey: ['feed-filter-rules', feedUrl] })
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteFeedFilterRule(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['feed-filter-rules', feedUrl] })
    },
  })
  const trialMutation = useMutation({
    mutationFn: () => trialFeedFilterRule({ feedUrl, sampleTitle: trialTitle }),
  })
  const rules = rulesQuery.data?.items ?? []

  return (
    <Dialog open={open} onClose={onClose} title={`内容过滤 — ${title}`}>
      <div className="flex flex-col gap-3">
        <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
          <input
            type="checkbox"
            checked={settings.includeHiddenEntries === true}
            onChange={(e) => updateSettings({ includeHiddenEntries: e.target.checked })}
          />
          临时显示被屏蔽条目（带标记）
        </label>

        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="字段" value={field} onChange={(e) => setField(e.target.value as 'title' | 'author')} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs">
            <option value="title">标题</option>
            <option value="author">作者</option>
          </select>
          <select aria-label="匹配方式" value={op} onChange={(e) => setOp(e.target.value as 'contains' | 'equals')} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs">
            <option value="contains">包含</option>
            <option value="equals">等于</option>
          </select>
          <input aria-label="规则值" value={value} onChange={(e) => setValue(e.target.value)} className={cx(inputCls, 'flex-1 min-w-32')} placeholder="关键词" />
          <Button size="sm" variant="secondary" disabled={value.trim() === '' || createMutation.isPending} onClick={() => createMutation.mutate()}>
            添加
          </Button>
        </div>
        {createMutation.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">{errMsg(createMutation.error)}</p>
        )}

        {rulesQuery.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">加载中…</p>}
        {rules.length === 0 && rulesQuery.isSuccess && (
          <p className="text-xs text-[var(--lumi-text-tertiary)]">暂无规则——被屏蔽条目不会出现在时间线（服务端过滤）。</p>
        )}
        <ul className="flex flex-col gap-1.5">
          {rules.map((rule) => (
            <li key={rule.id} className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs">
              <span className="text-[var(--lumi-text-secondary)]">
                {rule.field === 'title' ? '标题' : '作者'}{rule.op === 'contains' ? ' 包含 ' : ' = '}
                <span className="font-mono text-[var(--lumi-text-primary)]">{rule.value}</span>
              </span>
              <span className="flex-1" />
              <button
                type="button"
                aria-label={`删除规则 ${rule.value}`}
                onClick={() => deleteMutation.mutate(rule.id)}
                className="text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-danger)]"
              >
                <Trash2 aria-hidden className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>

        <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5">
          <p className="text-xs font-medium text-[var(--lumi-text-primary)]">试跑</p>
          <div className="mt-1.5 flex items-center gap-2">
            <input aria-label="样例标题" value={trialTitle} onChange={(e) => setTrialTitle(e.target.value)} className={cx(inputCls, 'flex-1 min-w-32')} placeholder="输入样例标题" />
            <Button size="sm" variant="ghost" disabled={trialTitle.trim() === '' || trialMutation.isPending} onClick={() => trialMutation.mutate()}>
              试跑
            </Button>
          </div>
          {trialMutation.data && (
            <p role="status" className="mt-1.5 text-xs text-[var(--lumi-text-secondary)]">
              {trialMutation.data.matched
                ? `命中：${trialMutation.data.reason}`
                : '未命中任何规则。'}
            </p>
          )}
        </div>
      </div>
    </Dialog>
  )
}

// ---- F046 静音列表 ----------------------------------------------------------

export function MuteListDialog({
  open,
  onClose,
  overrides,
  onUnmute,
}: {
  open: boolean
  onClose: () => void
  overrides: { feedUrl: string; hiddenUntil?: string | null; staleAlertHours?: number | null }[]
  onUnmute: (feedUrl: string) => void
}) {
  const now = Date.now()
  const active = overrides.flatMap((item) => {
    if (!item.hiddenUntil) return []
    const until = Date.parse(item.hiddenUntil)
    if (!Number.isFinite(until) || until <= now) return []
    return [{ feedUrl: item.feedUrl, hiddenUntil: item.hiddenUntil as string }]
  })
  return (
    <Dialog open={open} onClose={onClose} title="静音列表">
      {active.length === 0 ? (
        <EmptyState title="没有静音中的来源" description="在订阅行菜单选择「隐藏 7 天/30 天」后，这里会显示截止时间与提前解除入口。" />
      ) : (
        <ul className="flex flex-col gap-1.5">
          {active.map((item) => (
            <li key={item.feedUrl} className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2 text-xs">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[var(--lumi-text-primary)]">{item.feedUrl}</span>
                <span className="text-[var(--lumi-text-tertiary)]">截止 {dateTimeFormatter.format(Date.parse(item.hiddenUntil))}</span>
              </span>
              <Button size="sm" variant="ghost" onClick={() => onUnmute(item.feedUrl)}>
                提前解除
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  )
}

// ---- F048/F055/N015 来源策略、阅读外观与分时静音 ----------------------------

/** N015：一个分时静音窗口（days 与 JS getDay 对齐：0=周日 … 6=周六）。 */
export interface MuteWindow {
  days: number[]
  start: string
  end: string
}

/** N015：窗口行客户端校验（与服务端同规则；返回第一处问题或 null）。 */
export function muteWindowError(windows: MuteWindow[]): string | null {
  if (windows.length > 7) return '每来源最多 7 个静音窗口。'
  for (const window of windows) {
    if (window.days.length === 0) return '每个窗口至少选择一天。'
    if (!/^\d{2}:\d{2}$/.test(window.start) || !/^\d{2}:\d{2}$/.test(window.end)) {
      return '窗口时间必须是 HH:MM。'
    }
    if (window.start === window.end) return '窗口开始与结束不能相同。'
  }
  return null
}

const DAY_LABELS = ['日', '一', '二', '三', '四', '五', '六'] as const

function MuteWindowRow({
  window,
  index,
  onChange,
  onRemove,
}: {
  window: MuteWindow
  index: number
  onChange: (next: MuteWindow) => void
  onRemove: () => void
}) {
  const toggleDay = (day: number) => {
    const days = window.days.includes(day)
      ? window.days.filter((d) => d !== day)
      : [...window.days, day]
    onChange({ ...window, days })
  }
  return (
    <li
      className="flex flex-wrap items-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2 text-xs"
      data-testid={`mute-window-${index}`}
    >
      <span className="flex gap-0.5" role="group" aria-label={`窗口 ${index + 1} 生效日`}>
        {DAY_LABELS.map((label, day) => (
          <button
            key={day}
            type="button"
            aria-pressed={window.days.includes(day)}
            aria-label={`周${label}`}
            onClick={() => toggleDay(day)}
            className={
              window.days.includes(day)
                ? 'size-7 rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent)]'
                : 'size-7 rounded-[var(--lumi-radius-sm)] text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]'
            }
          >
            {label}
          </button>
        ))}
      </span>
      <input
        type="time"
        aria-label={`窗口 ${index + 1} 开始`}
        value={window.start}
        onChange={(e) => onChange({ ...window, start: e.target.value })}
        className="rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
      />
      <span aria-hidden>–</span>
      <input
        type="time"
        aria-label={`窗口 ${index + 1} 结束`}
        value={window.end}
        onChange={(e) => onChange({ ...window, end: e.target.value })}
        className="rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
      />
      <button
        type="button"
        aria-label={`删除窗口 ${index + 1}`}
        onClick={onRemove}
        className="ml-auto text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-danger)]"
      >
        <Trash2 aria-hidden className="size-3.5" />
      </button>
    </li>
  )
}

export function SourcePolicyDialog({
  open,
  onClose,
  feedUrl,
  title,
}: {
  open: boolean
  onClose: () => void
  feedUrl: string
  title: string
}) {
  const queryClient = useQueryClient()
  // F048/F055：per-source 策略与阅读样式走服务端 source_overrides（重启后仍在）。
  const overridesQuery = useQuery({
    queryKey: ['source-overrides'],
    queryFn: () => listSourceOverrides(),
    enabled: open,
  })
  const current = overridesQuery.data?.items.find((item) => item.feedUrl === feedUrl)
  const [policy, setPolicy] = useState<'rss' | 'web'>('rss')
  const [fontSize, setFontSize] = useState<number | ''>('')
  const [lineHeight, setLineHeight] = useState<number | ''>('')
  const [width, setWidth] = useState<number | ''>('')
  // F066：AI 使用范围（该来源是否参与 AI 消耗；派生数据保留不再更新）。
  const [aiDisabled, setAiDisabled] = useState(false)
  // N015：分时静音窗口（每周循环；命中期间不出现在通用时间线）。
  const [muteWindows, setMuteWindows] = useState<MuteWindow[]>([])
  // 服务端值按「内容签名」同步（键为签名而非对象引用）：react-query 的
  // data 引用在无关重渲染时会更换，按引用同步会把未保存编辑冲掉。
  // 用户一旦编辑（editedRef）即停同步——编辑不被服务端重置；保存成功后
  // 对话框关闭，下次打开重新同步。
  const editedRef = useRef(false)
  const serverSignature = current === undefined ? '' : JSON.stringify(current)
  useEffect(() => {
    if (editedRef.current) return
    setPolicy((current?.extractPolicy as 'rss' | 'web' | undefined) ?? 'rss')
    const style = (current?.readerStyle ?? {}) as Record<string, number | undefined>
    setFontSize(typeof style.fontSize === 'number' ? style.fontSize : '')
    setLineHeight(typeof style.lineHeight === 'number' ? style.lineHeight : '')
    setWidth(typeof style.width === 'number' ? style.width : '')
    setAiDisabled(Boolean(current?.aiDisabled))
    const stored = current?.muteWindows
    setMuteWindows(
      Array.isArray(stored)
        ? stored.map((w) => ({
            days: [...(w.days as number[])],
            start: String(w.start),
            end: String(w.end),
          }))
        : [],
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverSignature, open])
  const overrideActive =
    policy !== 'rss' || fontSize !== '' || lineHeight !== '' || width !== ''
  const muteError = muteWindowError(muteWindows)
  /** 标记用户已编辑：停掉服务端→表单的同步（保护未保存编辑）。 */
  const markEdited = () => {
    editedRef.current = true
  }
  const saveMutation = useMutation({
    mutationFn: (patch: {
      extractPolicy: string
      readerStyle: Record<string, number> | null
      aiDisabled?: boolean
      muteWindows?: MuteWindow[] | null
    }) =>
      setSourceOverride({ feedUrl, ...patch }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['source-overrides'] })
      onClose()
    },
  })

  return (
    <Dialog open={open} onClose={onClose} title={`${title} — 来源设置`}>
      <div className="flex flex-col gap-3">
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          继承状态：{overrideActive ? '已覆盖（优先于全局）' : '继承中（跟随全局设置）'}
        </p>
        <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          正文策略
          <select aria-label="正文策略" value={policy} onChange={(e) => { markEdited(); setPolicy(e.target.value as 'rss' | 'web') }} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm">
            <option value="rss">RSS 正文（默认）</option>
            <option value="web">抓取原文正文（全文型站点）</option>
          </select>
        </label>
        <div className="grid grid-cols-3 gap-2">
          <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
            字号
            <input aria-label="覆盖字号" type="number" min={12} max={28} value={fontSize} onChange={(e) => { markEdited(); setFontSize(e.target.value === '' ? '' : Number(e.target.value)) }} className={inputCls} placeholder="全局" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
            行距
            <input aria-label="覆盖行距" type="number" step={0.05} min={1.4} max={2.6} value={lineHeight} onChange={(e) => { markEdited(); setLineHeight(e.target.value === '' ? '' : Number(e.target.value)) }} className={inputCls} placeholder="全局" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
            宽度（移动端忽略）
            <input aria-label="覆盖宽度" type="number" min={480} max={1600} value={width} onChange={(e) => { markEdited(); setWidth(e.target.value === '' ? '' : Number(e.target.value)) }} className={inputCls} placeholder="全局" />
          </label>
        </div>
        {/* F066：AI 使用范围 */}
        <div className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-2.5">
          <Switch checked={aiDisabled} onCheckedChange={(v) => { markEdited(); setAiDisabled(v) }} label="禁用该来源的 AI" />
          <span className="text-xs text-[var(--lumi-text-secondary)]">
            AI 使用范围：<span data-testid="ai-scope-status">{aiDisabled ? '已禁用' : '允许 AI'}</span>
          </span>
          <span className="text-[11px] text-[var(--lumi-text-tertiary)]">
            禁用后：摘要/译文/对话返回 403，摘要译文等已生成内容保留但不再更新，图谱索引移除该来源；订阅数据不受影响。
          </span>
        </div>
        {/* N015：分时静音（每周循环窗口；只影响通用时间线，抓取/搜索不受影响） */}
        <div className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-2.5">
          <p className="text-xs font-medium text-[var(--lumi-text-primary)]">分时静音</p>
          <p className="text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
            静音窗口内的更新不出现在「全部/未读」时间线（按服务器本地时间，每周循环）；
            抓取、搜索与来源页阅读不受影响。结束早于开始表示跨越午夜。
          </p>
          {muteWindows.length === 0 ? (
            <p className="text-xs text-[var(--lumi-text-tertiary)]" data-testid="mute-windows-empty">
              未设置静音窗口。
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5" data-testid="mute-windows-list">
              {muteWindows.map((window, index) => (
                <MuteWindowRow
                  key={index}
                  window={window}
                  index={index}
                  onChange={(next) => {
                    markEdited()
                    setMuteWindows((prev) => prev.map((w, i) => (i === index ? next : w)))
                  }}
                  onRemove={() => { markEdited(); setMuteWindows((prev) => prev.filter((_, i) => i !== index)) }}
                />
              ))}
            </ul>
          )}
          {muteError !== null && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]" data-testid="mute-windows-error">
              {muteError}
            </p>
          )}
          <div>
            <Button
              size="sm"
              variant="secondary"
              className="min-h-9"
              disabled={muteWindows.length >= 7}
              onClick={() => { markEdited(); setMuteWindows((prev) => [...prev, { days: [], start: '22:00', end: '06:00' }]) }}
            >
              添加静音窗口
            </Button>
          </div>
        </div>
        {saveMutation.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">{errMsg(saveMutation.error)}</p>
        )}
        <div className="flex items-center justify-end gap-2">
          <Button
            size="sm"
            variant="ghost"
            disabled={saveMutation.isPending}
            onClick={() => saveMutation.mutate({ extractPolicy: 'rss', readerStyle: null, aiDisabled: false, muteWindows: null })}
          >
            恢复跟随全局
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={saveMutation.isPending || muteError !== null}
            onClick={() =>
              saveMutation.mutate({
                extractPolicy: policy,
                readerStyle: {
                  ...(fontSize !== '' ? { fontSize } : {}),
                  ...(lineHeight !== '' ? { lineHeight } : {}),
                  ...(width !== '' ? { width } : {}),
                },
                aiDisabled,
                muteWindows: muteWindows.length > 0 ? muteWindows : null,
              })
            }
          >
            {saveMutation.isPending ? '保存中…' : '保存'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

// ---- F049 导入记录 -----------------------------------------------------------

export function ImportBatchesDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const batchesQuery = useQuery({
    queryKey: ['import-batches'],
    queryFn: () => listImportBatches(20),
    enabled: open,
  })
  const [detail, setDetail] = useState<ImportBatch | null>(null)
  const retryMutation = useMutation({
    mutationFn: (id: string) => retryImportBatch(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['import-batches'] })
    },
  })
  const batches = batchesQuery.data?.items ?? []
  return (
    <Dialog open={open} onClose={onClose} title="导入记录">
      {batchesQuery.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">加载中…</p>}
      {batchesQuery.isSuccess && batches.length === 0 && (
        <EmptyState title="还没有导入记录" description="OPML / 书签导入后会在这里留下批次（成功/跳过/失败计数与失败原因）。" />
      )}
      {detail === null ? (
        <ul className="flex flex-col gap-1.5">
          {batches.map((batch) => (
            <li key={batch.id} className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2 text-xs">
              <span className="min-w-0 flex-1">
                <span className="block text-[var(--lumi-text-primary)]">
                  {batch.kind === 'opml' ? 'OPML' : batch.kind === 'bookmarks' ? '书签' : 'MD 笔记'} · {dateTimeFormatter.format(Date.parse(batch.createdAt))}
                </span>
                <span className="text-[var(--lumi-text-tertiary)]">
                  成功 {batch.counts.imported ?? 0} · 跳过 {batch.counts.skipped ?? 0} · 失败 {batch.counts.failed ?? 0}
                </span>
              </span>
              <Button size="sm" variant="ghost" onClick={() => setDetail(batch)}>详情</Button>
              {(batch.counts.failed ?? 0) > 0 && (
                <Button size="sm" variant="secondary" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(batch.id)}>
                  仅重试失败
                </Button>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className="flex flex-col gap-2">
          <Button size="sm" variant="ghost" onClick={() => setDetail(null)}>返回列表</Button>
          <p className="text-xs text-[var(--lumi-text-secondary)]">
            {detail.kind === 'opml' ? 'OPML' : detail.kind === 'bookmarks' ? '书签' : 'MD 笔记'} 批次 · 失败 {detail.counts.failed ?? 0} 项
            {detail.errors.truncated && '（错误已截断，仅保留前 50 条）'}
          </p>
          <ul className="flex max-h-64 flex-col gap-1 overflow-y-auto">
            {detail.errors.items.map((error, index) => (
              <li key={index} className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] px-2 py-1.5 text-xs">
                <span className="block truncate font-mono text-[var(--lumi-text-primary)]">{error.url}</span>
                <span className="text-[var(--lumi-danger)]">{error.reason}</span>
              </li>
            ))}
            {detail.errors.items.length === 0 && <li className="text-xs text-[var(--lumi-text-tertiary)]">没有失败项。</li>}
          </ul>
        </div>
      )}
      {retryMutation.isError && <p role="alert" className="text-xs text-[var(--lumi-danger)]">{errMsg(retryMutation.error)}</p>}
    </Dialog>
  )
}

// ---- F050 维护检查台 ---------------------------------------------------------

const HEALTH_LABELS: Record<HealthCheckItem['status'], string> = {
  ok: '正常',
  auth_error: '鉴权失败',
  not_found: '不存在',
  rate_limited: '被限流',
  timeout: '超时',
  bad_content: '非 feed 内容',
  network_error: '网络错误',
}

export function HealthCheckDialog({
  open,
  onClose,
  subscriptions,
}: {
  open: boolean
  onClose: () => void
  subscriptions: { subscriptionRef: string; title: string; feedUrl: string }[]
}) {
  const [selected, setSelected] = useState<string[]>([])
  const [results, setResults] = useState<HealthCheckItem[] | null>(null)
  const [running, setRunning] = useState(false)
  const [cancelled, setCancelled] = useState(false)
  const cancelRef = useRef(false)

  const byRef = useMemo(
    () => new Map(subscriptions.map((sub) => [sub.subscriptionRef, sub])),
    [subscriptions],
  )
  const toggle = (ref: string) =>
    setSelected((prev) => (prev.includes(ref) ? prev.filter((r) => r !== ref) : [...prev, ref]))

  const run = async (refs: string[]) => {
    setRunning(true)
    setCancelled(false)
    cancelRef.current = false
    setResults(null)
    try {
      const response = await runHealthCheck(refs, 5)
      if (!cancelRef.current) setResults(response.items)
    } finally {
      setRunning(false)
    }
  }

  useEffect(() => {
    if (open) {
      setSelected([])
      setResults(null)
      setRunning(false)
    }
  }, [open])

  const failed = results?.filter((item) => item.status !== 'ok') ?? []
  return (
    <Dialog open={open} onClose={onClose} title="维护检查">
      <div className="flex flex-col gap-3">
        <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          选择来源后并发探测 feed 地址（纯诊断：不修改任何配置）。
        </p>
        <div className="max-h-40 overflow-y-auto rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
          {subscriptions.length === 0 && <p className="text-xs text-[var(--lumi-text-tertiary)]">暂无订阅。</p>}
          {subscriptions.map((sub) => (
            <label key={sub.subscriptionRef} className="flex items-center gap-2 py-1 text-xs text-[var(--lumi-text-secondary)]">
              <input type="checkbox" checked={selected.includes(sub.subscriptionRef)} onChange={() => toggle(sub.subscriptionRef)} />
              <span className="truncate">{sub.title}</span>
            </label>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="primary" disabled={selected.length === 0 || running} onClick={() => void run(selected)}>
            {running ? '检查中…' : '运行检查'}
          </Button>
          {running && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                cancelRef.current = true
                setCancelled(true)
              }}
            >
              取消
            </Button>
          )}
          {results !== null && !running && failed.length > 0 && (
            <Button size="sm" variant="secondary" onClick={() => void run(failed.map((item) => item.ref))}>
              仅重查失败项
            </Button>
          )}
        </div>
        {cancelled && <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">已取消（当前结果可能不完整）。</p>}
        {results !== null && (
          <ul className="flex flex-col gap-1">
            {results.map((item) => {
              const sub = byRef.get(item.ref)
              return (
                <li key={item.ref} className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs">
                  <span
                    className={cx(
                      'size-2 rounded-full',
                      item.status === 'ok' ? 'bg-[var(--lumi-accent)]' : 'bg-[var(--lumi-danger)]',
                    )}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">{sub?.title ?? item.ref}</span>
                  <span className="text-[var(--lumi-text-tertiary)]">
                    {HEALTH_LABELS[item.status]}{item.httpStatus ? ` · HTTP ${item.httpStatus}` : ''}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </Dialog>
  )
}

// ---- F056 继续阅读（Sidebar 卡片数据钩子；组件在 Sidebar 使用） --------------

export function useContinueReading() {
  return useQuery({
    queryKey: ['reading-progress'],
    queryFn: () => listReadingProgress(5),
    staleTime: 15_000,
  })
}

export function useReviewQueue(status: 'due' | 'done') {
  return useQuery({
    queryKey: ['review-queue', status],
    queryFn: () => listReviewQueue(status),
    enabled: status === 'due',
  })
}

export async function scheduleReview(annotationId: string): Promise<{ ok: boolean; conflict: boolean }> {
  const due = new Date(Date.now() + 86_400_000).toISOString()
  try {
    await addReviewQueueItem({ annotationId, dueAt: due })
    return { ok: true, conflict: false }
  } catch (error) {
    if (error instanceof Error && error.message.includes('409')) {
      return { ok: false, conflict: true }
    }
    throw error
  }
}

export async function completeAndPostpone(id: string, days: number): Promise<void> {
  if (days <= 0) {
    await completeReviewQueueItem(id)
    return
  }
  await postponeReviewQueueItem(id, new Date(Date.now() + days * 86_400_000).toISOString())
}

// useReadingProgressReporter 移至 lib/reading-progress-reporter（Reader 首屏
// 只该带上报 hook，不该拖入整个订阅面板模块）；此处 re-export 兼容。
export { useReadingProgressReporter } from '../lib/reading-progress-reporter'

/** F051/F052/F058 批注检索（管理器用）。 */
export function useAnnotationSearch(q: string) {
  return useQuery({
    queryKey: ['annotations', { q }],
    queryFn: () => listAnnotations(q === '' ? {} : { q }),
  })
}
