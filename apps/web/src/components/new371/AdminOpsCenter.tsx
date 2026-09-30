/** AdminOpsCenter — NEW-371..380 运行治理中心（管理台新增分组面板）。
 *
 * 十项治理能力各是一个「情境展开」子区：折叠 = 不挂载 = 零查询；
 * 展开才拉取各自的真实端点。所有写操作走管理台统一的临时提权流程
 * （403 step_up_required → notifyStepUpRequired → 密码对话框 → 匹配
 * 作用域令牌重试）。诚实边界逐项如实呈现：
 * - 371：暂停分 enforcedBy=loop（真实消费）/ declared（治理意图记录）；
 * - 372：优先级只影响下一轮清扫（appliesAt=next_sweep，无抢占）；
 * - 373：演练绝不进入维护；确认后才排程真实窗口；
 * - 374：账单只有计数/字节，绝无文章内容；
 * - 377：锁类没有强制解锁入口（防双写）；
 * - 378：探测只做本地检查；秘密只有 已配置/未配置 状态位；
 * - 380：清单脱敏生成，确认后才可导出。
 */

import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { isStepUpRequiredError, notifyStepUpRequired } from '../../lib/step-up'
import {
  applyConfigDraft,
  assignSupportTicket,
  clearTaskPriority,
  closeSupportTicket,
  confirmHandoffSummary,
  createConfigDraft,
  createHandoffSummary,
  createMaintenanceDrill,
  discardConfigDraft,
  executeQuotaBatch,
  exportHandoffSummary,
  getAdminResourceBill,
  getConfigDraftSchema,
  getFeatureDependencies,
  getOwnResourceBill,
  getSupportTicket,
  getTaskBlockers,
  getTaskCalendar,
  getTaskPriorities,
  listSupportTickets,
  pauseTaskKind,
  probeFeatureDependencies,
  replySupportTicket,
  resumeTaskKind,
  scheduleMaintenanceWindow,
  setTaskPriority,
  type ConfigDraft,
  type FeatureDependencyGraph,
  type HandoffPayload,
  type MaintenanceDrill,
  type QuotaBatchPreview,
  type ResourceBill,
  type SupportTicketDetail,
  type SupportTicketRow,
  type TaskBlockerReport,
  type TaskCalendar,
  type TaskPriorityList,
  previewQuotaBatch,
} from '../../api/new371'
import {
  NoteText,
  StatusLine,
  SubSection,
  actionButtonClass,
  errorText,
  Field,
  inputClass,
} from './parts'

function toStepUpError(error: unknown): string {
  if (isStepUpRequiredError(error)) {
    const extra = error instanceof Error ? (error as { extra?: Record<string, string> | null }).extra : null
    notifyStepUpRequired({
      operation: extra?.operation ?? null,
      targetUserId: extra?.targetUserId ?? null,
    })
    return '该操作需要临时提权验证（输入管理员密码后再试一次）。'
  }
  return errorText(error)
}

function LoadError({ error }: { error: unknown }) {
  return <StatusLine tone="error">{toStepUpError(error)}</StatusLine>
}

// ---- NEW-371 后台任务日历 ----------------------------------------------------

function TaskCalendarSection() {
  const query = useQuery({ queryKey: ['n371-task-calendar'], queryFn: getTaskCalendar })
  const [kind, setKind] = useState('search_sync')
  const [reason, setReason] = useState('')
  const [impact, setImpact] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const pause = useMutation({
    mutationFn: () => pauseTaskKind(kind, reason, impact),
    onSuccess: (data) => {
      setMessage(data.paused ? `已登记暂停：${kind}` : '')
      setReason('')
      setImpact('')
      void query.refetch()
    },
    onError: (error) => setMessage(toStepUpError(error)),
  })
  const resume = useMutation({
    mutationFn: (target: string) => resumeTaskKind(target),
    onSuccess: () => {
      setMessage('已恢复。')
      void query.refetch()
    },
    onError: (error) => setMessage(toStepUpError(error)),
  })

  if (query.isLoading) {
    return <StatusLine tone="info">加载中…</StatusLine>
  }
  if (query.isError) return <LoadError error={query.error} />
  const calendar = query.data as TaskCalendar
  return (
    <div className="flex flex-col gap-3" data-n371-calendar>
      <ul className="flex flex-col gap-2">
        {calendar.kinds.map((item) => (
          <li
            key={item.kind}
            data-n371-kind={item.kind}
            className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-[var(--lumi-text-primary)]">{item.label}</span>
              <span className="text-xs tabular-nums text-[var(--lumi-text-tertiary)]">
                {item.scheduled ? `间隔 ${item.intervalSeconds ?? '—'}s` : '未排程'}
              </span>
            </div>
            {item.pause.active ? (
              <div className="flex flex-col gap-1">
                <StatusLine tone="error">
                  暂停中（{item.enforcedBy === 'loop' ? '循环消费' : '仅治理意图'}）：{item.impact}
                </StatusLine>
                <button
                  type="button"
                  className={actionButtonClass}
                  onClick={() => resume.mutate(item.kind)}
                  disabled={resume.isPending}
                >
                  恢复该任务
                </button>
              </div>
            ) : (
              <NoteText>无生效中的暂停。</NoteText>
            )}
            {item.pauseNote && <NoteText>{item.pauseNote}</NoteText>}
          </li>
        ))}
      </ul>
      <NoteText>{calendar.notes[0]}</NoteText>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          pause.mutate()
        }}
      >
        <Field label="任务档">
          <select aria-label="任务档" className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}>
            {calendar.kinds.map((item) => (
              <option key={item.kind} value={item.kind}>
                {item.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="暂停原因">
          <input aria-label="暂停原因" className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} required />
        </Field>
        <Field label="影响说明（必填）">
          <input aria-label="影响说明" className={inputClass} value={impact} onChange={(e) => setImpact(e.target.value)} required />
        </Field>
        <button type="submit" className={actionButtonClass} disabled={pause.isPending}>
          登记暂停（需临时提权）
        </button>
      </form>
      {message && <StatusLine tone="info">{message}</StatusLine>}
    </div>
  )
}

// ---- NEW-372 任务优先级 ------------------------------------------------------

function TaskPrioritySection() {
  const query = useQuery({ queryKey: ['n372-task-priorities'], queryFn: getTaskPriorities })
  const [userId, setUserId] = useState('')
  const [level, setLevel] = useState('high')
  const [message, setMessage] = useState<string | null>(null)
  const setPriority = useMutation({
    mutationFn: () => setTaskPriority(userId, level),
    onSuccess: (data) => {
      setMessage(`已设为 ${data.priority}（下一轮清扫生效，不打断在执行任务）。`)
      void query.refetch()
    },
    onError: (error) => setMessage(toStepUpError(error)),
  })
  const clear = useMutation({
    mutationFn: (target: string) => clearTaskPriority(target),
    onSuccess: () => {
      setMessage('已恢复默认。')
      void query.refetch()
    },
    onError: (error) => setMessage(toStepUpError(error)),
  })
  if (query.isLoading) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <LoadError error={query.error} />
  const list = query.data as TaskPriorityList
  return (
    <div className="flex flex-col gap-3" data-n371-priority>
      {list.items.length === 0 ? (
        <NoteText>尚无显式调整——所有账户按默认优先级（普通）执行。</NoteText>
      ) : (
        <ul className="flex flex-col gap-2">
          {list.items.map((row) => (
            <li key={row.userId} className="flex items-center justify-between gap-2 text-sm">
              <span className="text-[var(--lumi-text-primary)]">
                {row.username ?? row.userId} — {row.priorityLabel}
              </span>
              <button type="button" className={actionButtonClass} onClick={() => clear.mutate(row.userId)}>
                恢复默认
              </button>
            </li>
          ))}
        </ul>
      )}
      <NoteText>顺序只影响下一轮清扫；正在执行的任务绝不被打断。</NoteText>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          setPriority.mutate()
        }}
      >
        <Field label="账户 ID">
          <input aria-label="账户 ID" className={inputClass} value={userId} onChange={(e) => setUserId(e.target.value)} required />
        </Field>
        <Field label="优先级">
          <select aria-label="优先级" className={inputClass} value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="low">低</option>
            <option value="normal">普通</option>
            <option value="high">高</option>
          </select>
        </Field>
        <button type="submit" className={actionButtonClass} disabled={setPriority.isPending}>
          设置优先级
        </button>
      </form>
      {message && <StatusLine tone="info">{message}</StatusLine>}
    </div>
  )
}

// ---- NEW-373 维护通知演练 ----------------------------------------------------

function MaintenanceSection() {
  const [title, setTitle] = useState('')
  const [notice, setNotice] = useState('')
  const [startsAt, setStartsAt] = useState('')
  const [endsAt, setEndsAt] = useState('')
  const [drill, setDrill] = useState<MaintenanceDrill | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const fields = () => ({ title, notice, startsAt, endsAt })
  const drillMutation = useMutation({
    mutationFn: () => createMaintenanceDrill(fields()),
    onSuccess: (data) => {
      setDrill(data)
      setMessage('演练完成：未创建窗口，实例未进入维护。')
    },
    onError: (error) => setMessage(toStepUpError(error)),
  })
  const scheduleMutation = useMutation({
    mutationFn: () => scheduleMaintenanceWindow(fields()),
    onSuccess: () => setMessage('已排程真实维护窗口（成员将看到同一通知）。'),
    onError: (error) => setMessage(toStepUpError(error)),
  })
  return (
    <div className="flex flex-col gap-3" data-n371-maintenance>
      <form className="flex flex-col gap-2">
        <Field label="窗口标题">
          <input aria-label="窗口标题" className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} required />
        </Field>
        <Field label="通知文案">
          <input aria-label="通知文案" className={inputClass} value={notice} onChange={(e) => setNotice(e.target.value)} required />
        </Field>
        <Field label="开始时刻（RFC3339，如 2026-06-01T08:00:00Z）">
          <input aria-label="开始时刻" className={inputClass} value={startsAt} onChange={(e) => setStartsAt(e.target.value)} required />
        </Field>
        <Field label="结束时刻">
          <input aria-label="结束时刻" className={inputClass} value={endsAt} onChange={(e) => setEndsAt(e.target.value)} required />
        </Field>
        <div className="flex gap-2">
          <button
            type="button"
            className={actionButtonClass}
            onClick={() => drillMutation.mutate()}
            disabled={drillMutation.isPending}
          >
            预览各角色视图（演练，无副作用）
          </button>
          <button
            type="button"
            className={actionButtonClass}
            onClick={() => scheduleMutation.mutate()}
            disabled={scheduleMutation.isPending}
          >
            确认并排程真实维护（需临时提权）
          </button>
        </div>
      </form>
      {drill && (
        <ul className="flex flex-col gap-2" data-n371-drill-preview>
          {Object.values(drill.preview).map((view) => (
            <li key={view.role} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2">
              <span className="text-sm font-medium text-[var(--lumi-text-primary)]">{view.role}</span>
              <NoteText>{view.banner.notice}</NoteText>
              <NoteText>{view.roleNote}</NoteText>
            </li>
          ))}
        </ul>
      )}
      {message && <StatusLine tone="info">{message}</StatusLine>}
    </div>
  )
}

// ---- NEW-374 用户资源账单 ----------------------------------------------------

function BillView({ bill }: { bill: ResourceBill }) {
  return (
    <div className="flex flex-col gap-2" data-n371-bill>
      <ul className="grid grid-cols-2 gap-1 text-sm tabular-nums text-[var(--lumi-text-primary)]">
        {Object.entries(bill.counts).map(([key, value]) => (
          <li key={key}>
            {key}: {value}
          </li>
        ))}
      </ul>
      <NoteText>
        磁盘合计 {bill.storage.totalBytes} 字节（库 {bill.storage.databaseBytes} / 资产 {bill.storage.assetBytes}）。
      </NoteText>
      <NoteText>
        AI 当日调用 {bill.compute.aiCallsToday ?? '未知'}；最近备份计算 {bill.compute.recentBackupSeconds ?? 0} 秒。
      </NoteText>
      <NoteText>{bill.contentNote}</NoteText>
    </div>
  )
}

function ResourceBillSection() {
  const [userId, setUserId] = useState('')
  const [adminBill, setAdminBill] = useState<ResourceBill | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const selfQuery = useQuery({
    queryKey: ['n374-own-bill'],
    queryFn: getOwnResourceBill,
    enabled: false,
  })
  return (
    <div className="flex flex-col gap-3" data-n371-bill-section>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          getAdminResourceBill(userId)
            .then(setAdminBill)
            .catch((error: unknown) => setMessage(toStepUpError(error)))
        }}
      >
        <Field label="账户 ID（留空看自己的账单）">
          <input aria-label="账户 ID（留空看自己的账单）" className={inputClass} value={userId} onChange={(e) => setUserId(e.target.value)} />
        </Field>
        <button type="submit" className={actionButtonClass}>
          查看账单（他人账单只含计数并留查阅台账）
        </button>
      </form>
      <button
        type="button"
        className={actionButtonClass}
        onClick={() => void selfQuery.refetch()}
        disabled={selfQuery.isFetching}
      >
        我的资源账单（与查阅同一口径）
      </button>
      {selfQuery.isLoading && <StatusLine tone="info">加载中…</StatusLine>}
      {selfQuery.isError && <LoadError error={selfQuery.error} />}
      {selfQuery.data && <BillView bill={selfQuery.data} />}
      {adminBill && <BillView bill={adminBill} />}
      {message && <StatusLine tone="info">{message}</StatusLine>}
    </div>
  )
}

// ---- NEW-375 配额变更批次 ----------------------------------------------------

function QuotaBatchSection() {
  const [userId, setUserId] = useState('')
  const [cap, setCap] = useState('10')
  const [batch, setBatch] = useState<QuotaBatchPreview | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const preview = useMutation({
    mutationFn: () => previewQuotaBatch([{ userId, caps: { aiQuotaPerDay: Number(cap) } }]),
    onSuccess: setBatch,
    onError: (error) => setMessage(toStepUpError(error)),
  })
  const execute = useMutation({
    mutationFn: (batchId: string) => executeQuotaBatch(batchId),
    onSuccess: (data) => {
      setMessage(`批次已执行（${data.results.filter((r) => r.outcome === 'ok').length} 个账户生效）。`)
      setBatch(null)
    },
    onError: (error) => setMessage(toStepUpError(error)),
  })
  return (
    <div className="flex flex-col gap-3" data-n371-quota-batch>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          preview.mutate()
        }}
      >
        <Field label="账户 ID">
          <input aria-label="账户 ID" className={inputClass} value={userId} onChange={(e) => setUserId(e.target.value)} required />
        </Field>
        <Field label="AI 日上限">
          <input
            aria-label="AI 日上限"
            className={inputClass}
            type="number"
            min={1}
            value={cap}
            onChange={(e) => setCap(e.target.value)}
            required
          />
        </Field>
        <button type="submit" className={actionButtonClass} disabled={preview.isPending}>
          预览（存草案，不改任何账户）
        </button>
      </form>
      {batch && (
        <div className="flex flex-col gap-2" data-n371-batch-preview>
          {batch.preview.map((item) => (
            <div key={item.userId} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2">
              <span className="text-sm font-medium text-[var(--lumi-text-primary)]">{item.userId}</span>
              {item.outcome === 'skipped' ? (
                <StatusLine tone="error">{item.reason}</StatusLine>
              ) : (
                <NoteText>
                  现有 {JSON.stringify(item.currentCaps)} → 拟 {JSON.stringify(item.proposed)}
                  {item.overQuotaImpact &&
                    `；当日已用 ${item.overQuotaImpact.aiCallsToday}，按新上限预计至少 ${item.overQuotaImpact.projectedDeniedMin} 次被拒`}
                </NoteText>
              )}
            </div>
          ))}
          <button
            type="button"
            className={actionButtonClass}
            onClick={() => execute.mutate(batch.batchId)}
            disabled={execute.isPending}
          >
            确认执行（需临时提权）
          </button>
        </div>
      )}
      {message && <StatusLine tone="info">{message}</StatusLine>}
    </div>
  )
}

// ---- NEW-376 实例配置草案 ----------------------------------------------------

function ConfigDraftSection() {
  const schema = useQuery({ queryKey: ['n376-config-schema'], queryFn: getConfigDraftSchema })
  const [key, setKey] = useState('allow_public_registration')
  const [value, setValue] = useState('')
  const [draft, setDraft] = useState<ConfigDraft | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const create = useMutation({
    mutationFn: () => createConfigDraft(key, value),
    onSuccess: setDraft,
    onError: (error) => setMessage(toStepUpError(error)),
  })
  const apply = useMutation({
    mutationFn: (draftId: string) => applyConfigDraft(draftId),
    onSuccess: () => setMessage('已应用（与注册政策同一执行点）。'),
    onError: (error) => setMessage(toStepUpError(error)),
  })
  const discard = useMutation({
    mutationFn: (draftId: string) => discardConfigDraft(draftId),
    onSuccess: () => {
      setMessage('草案已废弃。')
      setDraft(null)
    },
    onError: (error) => setMessage(toStepUpError(error)),
  })
  return (
    <div className="flex flex-col gap-3" data-n371-config-draft>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate()
        }}
      >
        <Field label="配置键（仅非敏感白名单键）">
          <select aria-label="配置键" className={inputClass} value={key} onChange={(e) => setKey(e.target.value)}>
            {(schema.data?.keys ?? [{ key: 'allow_public_registration', type: 'bool', label: '公开注册开关' }]).map(
              (item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ),
            )}
          </select>
        </Field>
        <Field label="拟变更值（布尔键填 0 或 1）">
          <input aria-label="拟变更值" className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} required />
        </Field>
        <button type="submit" className={actionButtonClass} disabled={create.isPending}>
          形成草案
        </button>
      </form>
      {draft && (
        <div className="flex flex-col gap-2" data-n371-draft-view>
          <NoteText>
            当前 {draft.currentValue} → 草案 {draft.draftValue}
            {draft.differs === false && '（与当前一致）'}
          </NoteText>
          {draft.effectiveNotes.map((note) => (
            <NoteText key={note}>生效条件：{note}</NoteText>
          ))}
          <div className="flex gap-2">
            <button
              type="button"
              className={actionButtonClass}
              onClick={() => apply.mutate(draft.draftId)}
              disabled={apply.isPending}
            >
              应用（需临时提权）
            </button>
            <button
              type="button"
              className={actionButtonClass}
              onClick={() => discard.mutate(draft.draftId)}
              disabled={discard.isPending}
            >
              废弃草案
            </button>
          </div>
        </div>
      )}
      {message && <StatusLine tone="info">{message}</StatusLine>}
    </div>
  )
}

// ---- NEW-377 后台任务阻塞定位 ------------------------------------------------

function TaskBlockersSection() {
  const query = useQuery({ queryKey: ['n377-task-blockers'], queryFn: getTaskBlockers })
  if (query.isLoading) return <StatusLine tone="info">诊断中…</StatusLine>
  if (query.isError) return <LoadError error={query.error} />
  const report = query.data as TaskBlockerReport
  return (
    <div className="flex flex-col gap-3" data-n371-blockers>
      <NoteText>
        配额 {report.counts.quota ?? 0} · 限流 {report.counts.rate_limit ?? 0} · 锁 {report.counts.lock ?? 0} · 依赖{' '}
        {report.counts.dependency ?? 0}
      </NoteText>
      {report.blockers.length === 0 ? (
        <StatusLine tone="ok">当前没有检测到阻塞。</StatusLine>
      ) : (
        <ul className="flex flex-col gap-2">
          {report.blockers.map((blocker, index) => (
            <li key={index} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2">
              <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
                {blocker.category}
                {blocker.userId ? ` · ${blocker.userId}` : ''}
                {blocker.scopeKind ? ` · ${blocker.scopeKind}` : ''}
              </span>
              <NoteText>安全处置：{blocker.safeAction}</NoteText>
            </li>
          ))}
        </ul>
      )}
      {report.notes.map((note) => (
        <NoteText key={note}>{note}</NoteText>
      ))}
    </div>
  )
}

// ---- NEW-378 实例功能依赖图 --------------------------------------------------

function FeatureDepsSection() {
  const query = useQuery({ queryKey: ['n378-feature-deps'], queryFn: getFeatureDependencies })
  const [message, setMessage] = useState<string | null>(null)
  const probe = useMutation({
    mutationFn: probeFeatureDependencies,
    onSuccess: () => {
      setMessage('本地探测完成（外部连通性请看系统面板服务健康）。')
      void query.refetch()
    },
    onError: (error) => setMessage(toStepUpError(error)),
  })
  if (query.isLoading) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <LoadError error={query.error} />
  const graph = query.data as FeatureDependencyGraph
  return (
    <div className="flex flex-col gap-3" data-n371-feature-deps>
      <ul className="flex flex-col gap-2">
        {graph.features.map((feature) => (
          <li key={feature.key} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-[var(--lumi-text-primary)]">{feature.label}</span>
              <span className="text-xs text-[var(--lumi-text-tertiary)]">{feature.ready ? '就绪' : '未就绪'}</span>
            </div>
            <ul className="mt-1 flex flex-col gap-0.5">
              {feature.deps.map((dep) => (
                <li key={dep.key} className="text-sm text-[var(--lumi-text-secondary)]">
                  {dep.kind}：{dep.status === 'configured' ? '已配置' : dep.status === 'missing' ? '缺失' : '未探测'}
                  {dep.probedAt ? `（探测于 ${dep.probedAt}）` : ''}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      <button type="button" className={actionButtonClass} onClick={() => probe.mutate()} disabled={probe.isPending}>
        运行本地探测（零网络）
      </button>
      {message && <StatusLine tone="info">{message}</StatusLine>}
    </div>
  )
}

// ---- NEW-379 用户问题工单 ----------------------------------------------------

function TicketsSection() {
  const query = useQuery({ queryKey: ['n379-tickets'], queryFn: listSupportTickets })
  const [selected, setSelected] = useState<SupportTicketRow | null>(null)
  const [detail, setDetail] = useState<SupportTicketDetail | null>(null)
  const [assignee, setAssignee] = useState('')
  const [reply, setReply] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const refresh = () => {
    void query.refetch()
    if (selected) void getSupportTicket(selected.id).then(setDetail)
  }
  const act = (fn: () => Promise<unknown>, note: string) =>
    fn()
      .then(() => {
        setMessage(note)
        refresh()
      })
      .catch((error: unknown) => setMessage(toStepUpError(error)))
  if (query.isLoading) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError || query.data === undefined) return <LoadError error={query.error} />
  const data = query.data
  return (
    <div className="flex flex-col gap-3" data-n371-tickets>
      <NoteText>
        待处理 {data.counts.open ?? 0} · 已指派 {data.counts.assigned ?? 0} · 已答复 {data.counts.answered ?? 0} · 已关闭{' '}
        {data.counts.closed ?? 0}
      </NoteText>
      {data.items.length === 0 ? (
        <StatusLine tone="ok">当前没有工单。</StatusLine>
      ) : (
        <ul className="flex flex-col gap-2">
          {data.items.map((ticket) => (
            <li key={ticket.id} className="flex items-center justify-between gap-2 text-sm">
              <span className="min-w-0 truncate text-[var(--lumi-text-primary)]">
                {ticket.subject}（{ticket.status}）
              </span>
              <button
                type="button"
                className={actionButtonClass}
                onClick={() => {
                  setSelected(ticket)
                  void getSupportTicket(ticket.id).then(setDetail)
                }}
              >
                详情
              </button>
            </li>
          ))}
        </ul>
      )}
      {detail && (
        <div className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2" data-n371-ticket-detail>
          <NoteText>{detail.body}</NoteText>
          {detail.replies.map((item, index) => (
            <NoteText key={index}>
              {item.authorRole}：{item.body}
            </NoteText>
          ))}
          <Field label="指派给（管理员账户 ID）">
            <input aria-label="指派给" className={inputClass} value={assignee} onChange={(e) => setAssignee(e.target.value)} />
          </Field>
          <button
            type="button"
            className={actionButtonClass}
            onClick={() => act(() => assignSupportTicket(detail.id, assignee), '已指派。')}
          >
            指派
          </button>
          <Field label="回复内容">
            <input aria-label="回复内容" className={inputClass} value={reply} onChange={(e) => setReply(e.target.value)} />
          </Field>
          <div className="flex gap-2">
            <button
              type="button"
              className={actionButtonClass}
              onClick={() => act(() => replySupportTicket(detail.id, reply), '已回复。')}
            >
              回复
            </button>
            <button
              type="button"
              className={actionButtonClass}
              onClick={() => act(() => closeSupportTicket(detail.id), '已关闭。')}
            >
              关闭
            </button>
          </div>
        </div>
      )}
      {message && <StatusLine tone="info">{message}</StatusLine>}
    </div>
  )
}

// ---- NEW-380 运维交接摘要 ----------------------------------------------------

function HandoffSection() {
  const [summary, setSummary] = useState<{ id: string; payload: HandoffPayload } | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const build = useMutation({
    mutationFn: createHandoffSummary,
    onSuccess: (data) => setSummary({ id: data.summaryId, payload: data.payload }),
    onError: (error) => setMessage(toStepUpError(error)),
  })
  const confirm = useMutation({
    mutationFn: () => confirmHandoffSummary(summary?.id ?? ''),
    onSuccess: () => setMessage('已确认（对清单内容负责）。'),
    onError: (error) => setMessage(toStepUpError(error)),
  })
  const doExport = useMutation({
    mutationFn: () => exportHandoffSummary(summary?.id ?? ''),
    onSuccess: (data) => setMessage(`已导出（${data.exportedAt}）。${data.redactionNote}`),
    onError: (error) => setMessage(toStepUpError(error)),
  })
  return (
    <div className="flex flex-col gap-3" data-n371-handoff>
      <button type="button" className={actionButtonClass} onClick={() => build.mutate()} disabled={build.isPending}>
        生成脱敏交接清单
      </button>
      {summary && (
        <div className="flex flex-col gap-2">
          <NoteText>
            未完成项：工单 {summary.payload.openItems.tickets.length} · 任务暂停 {summary.payload.openItems.taskPauses.length}
            · 配额草案 {summary.payload.openItems.quotaBatchesDraft.length} · 配置草案{' '}
            {summary.payload.openItems.configDrafts.length} · 排程维护 {summary.payload.openItems.maintenanceWindows.length}
          </NoteText>
          <NoteText>{summary.payload.redactionNote}</NoteText>
          <div className="flex gap-2">
            <button
              type="button"
              className={actionButtonClass}
              onClick={() => confirm.mutate()}
              disabled={confirm.isPending}
            >
              确认（需临时提权）
            </button>
            <button
              type="button"
              className={actionButtonClass}
              onClick={() => doExport.mutate()}
              disabled={doExport.isPending}
            >
              导出
            </button>
          </div>
        </div>
      )}
      {message && <StatusLine tone="info">{message}</StatusLine>}
    </div>
  )
}

// ---- 面板 ---------------------------------------------------------------------

export function AdminOpsCenter() {
  return (
    <section aria-label="运行治理" data-testid="admin-ops-center" className="flex flex-col gap-3">
      <div>
        <h2 className="text-base font-semibold text-[var(--lumi-text-primary)]">运行治理</h2>
        <p className="text-sm text-[var(--lumi-text-tertiary)]">
          周期任务、配额与配置的治理面：全部走既有安全入口，无任何 shell。
        </p>
      </div>
      <SubSection id="n371-calendar" label="后台任务日历">
        <TaskCalendarSection />
      </SubSection>
      <SubSection id="n372-priority" label="任务优先级">
        <TaskPrioritySection />
      </SubSection>
      <SubSection id="n373-maintenance" label="维护通知演练">
        <MaintenanceSection />
      </SubSection>
      <SubSection id="n374-bill" label="用户资源账单">
        <ResourceBillSection />
      </SubSection>
      <SubSection id="n375-quota-batch" label="配额变更批次">
        <QuotaBatchSection />
      </SubSection>
      <SubSection id="n376-config-draft" label="实例配置草案">
        <ConfigDraftSection />
      </SubSection>
      <SubSection id="n377-blockers" label="后台任务阻塞定位">
        <TaskBlockersSection />
      </SubSection>
      <SubSection id="n378-feature-deps" label="实例功能依赖图">
        <FeatureDepsSection />
      </SubSection>
      <SubSection id="n379-tickets" label="用户问题工单">
        <TicketsSection />
      </SubSection>
      <SubSection id="n380-handoff" label="运维交接摘要">
        <HandoffSection />
      </SubSection>
    </section>
  )
}
