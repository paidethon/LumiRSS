/** NEW-201..210 来源运维工作台 —— 单一对话框入口，10 项能力分页签。
 *
 * 共享装配纪律：本目录是新文件；SubscriptionsPage 只加一个入口按钮 +
 * lazy 挂载（wiring commit）。每个页签都是真功能面板（列表/表单/
 * 确认动作走真实 API），无占位页：
 * - 201 接管向导：OPML 预演 → 勾选 → 应用（不重复订阅由服务端保证）；
 * - 202 停更观察：观察期列表/新建/延长/收尾（事实面判定如实展示）；
 * - 203 分流视图：CRUD + 视图条目（读取侧过滤，点击打开原文）；
 * - 204 镜像比对：两 URL 并排覆盖差异 → 抉择台账；
 * - 205 保留策略：预演（保留/回收事实面）→ 显式确认启用；
 * - 206 阅读日历：月历分桶 + 当日条目（点击打开）；
 * - 207 RSSHub 表单：路由目录选路由 → 填参 → 校验 → 确认添加；
 * - 208 认证到期提醒：到期日登记/分桶/续期/dismiss（无凭据字段）；
 * - 209 回收箱：退订配置列表 → 恢复/放弃；
 * - 210 停机计划：暂停区间设置/取消（activeNow 如实标注）。
 * 复用 ui/ 原语（Dialog/Tabs/Button），语义 token，无硬编码色。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  closeObservation,
  createObservation,
  createPausePlan,
  createReminder,
  createView,
  discardBinRow,
  extendObservation,
  getFeedCalendar,
  getRssHubFormSchema,
  getViewEntries,
  listBin,
  listObservations,
  listPausePlans,
  listReminders,
  listRssHubRoutes,
  listViews,
  mirrorCompare,
  recordMirrorChoice,
  renewReminder,
  restoreBinRow,
  retentionDryRun,
  retentionEnable,
  applyRssHubForm,
  takeoverApply,
  takeoverPreview,
  cancelPausePlan,
  deleteView,
  dismissReminder,
  validateRssHubForm,
  type RetentionDryRun,
  type TakeoverPlan,
  type MirrorCompareResult,
  type RssHubFormSchema,
  type CalendarView,
} from './api'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { Tabs } from '../ui/Tabs'
import { useReaderUi, ALL_SCOPE } from '../../store/reader-ui'

const inputCls =
  'w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'
const cellCls = 'border-b border-[var(--lumi-border)] px-2 py-1.5 align-top text-sm'

function errMsg(error: unknown): string {
  return error instanceof Error ? error.message : '请稍后重试。'
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs text-[var(--lumi-text-secondary)]">
      <span className="mb-1 block">{label}</span>
      {children}
    </label>
  )
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-end gap-2">{children}</div>
}

// ---- NEW-210 停机计划 ----

function PausePanel() {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['new201-ops', 'pauses'], queryFn: listPausePlans })
  const [feedUrl, setFeedUrl] = useState('')
  const [endAt, setEndAt] = useState('')
  const [openEnded, setOpenEnded] = useState(false)
  const [reason, setReason] = useState('')
  const create = useMutation({
    mutationFn: () =>
      createPausePlan({
        feedUrl,
        ...(endAt && !openEnded ? { endAt: new Date(endAt).toISOString() } : {}),
        ...(openEnded ? { openEnded: true } : {}),
        ...(reason ? { reason } : {}),
      }),
    onSuccess: () => {
      setFeedUrl('')
      setEndAt('')
      setReason('')
      void qc.invalidateQueries({ queryKey: ['new201-ops', 'pauses'] })
    },
  })
  const cancel = useMutation({
    mutationFn: (id: string) => cancelPausePlan(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['new201-ops', 'pauses'] }),
  })
  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--lumi-text-secondary)]">
        {list.data?.note ?? '暂停区间在 Lumi 侧消费；FreshRSS 逐源调度需原生界面调整。'}
      </p>
      <Row>
        <Field label="来源 feed URL">
          <input className={inputCls} value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} placeholder="https://…" />
        </Field>
        <Field label="恢复时间（可选）">
          <input type="datetime-local" className={inputCls} value={endAt} onChange={(e) => setEndAt(e.target.value)} disabled={openEnded} />
        </Field>
        <label className="flex items-center gap-1 text-xs">
          <input type="checkbox" checked={openEnded} onChange={(e) => setOpenEnded(e.target.checked)} />
          开放式（直到取消）
        </label>
        <Field label="理由（可选）">
          <input className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <Button variant="primary" size="sm" disabled={!feedUrl || create.isPending} onClick={() => create.mutate()}>
          设置暂停
        </Button>
      </Row>
      {create.isError && <p role="alert">{errMsg(create.error)}</p>}
      {list.data && list.data.items.length === 0 && (
        <p className="text-sm text-[var(--lumi-text-secondary)]">当前没有停机计划。</p>
      )}
      <table className="w-full">
        <tbody>
          {list.data?.items.map((plan) => (
            <tr key={plan.id}>
              <td className={cellCls}>{plan.feedUrl}</td>
              <td className={cellCls}>
                {plan.activeNow ? '暂停中' : plan.status === 'active' ? '未生效/已结束' : '已取消'}
              </td>
              <td className={cellCls}>{plan.endAt ?? '直到取消'}</td>
              <td className={cellCls}>
                {plan.status === 'active' && (
                  <Button size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate(plan.id)}>
                    取消计划
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---- NEW-208 认证到期提醒 ----

const BUCKET_LABEL: Record<string, string> = {
  overdue: '已过期',
  due_soon: '即将到期',
  later: '暂远',
}

function CredentialPanel() {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['new201-ops', 'reminders'], queryFn: () => listReminders() })
  const [feedUrl, setFeedUrl] = useState('')
  const [expiresOn, setExpiresOn] = useState('')
  const [note, setNote] = useState('')
  const [renewDates, setRenewDates] = useState<Record<string, string>>({})
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new201-ops', 'reminders'] })
  const create = useMutation({
    mutationFn: () => createReminder({ feedUrl, expiresOn, ...(note ? { note } : {}) }),
    onSuccess: () => {
      setFeedUrl('')
      setExpiresOn('')
      setNote('')
      invalidate()
    },
  })
  const renew = useMutation({
    mutationFn: ({ id, date }: { id: string; date: string }) => renewReminder(id, date),
    onSuccess: invalidate,
  })
  const dismiss = useMutation({
    mutationFn: (id: string) => dismissReminder(id),
    onSuccess: invalidate,
  })
  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--lumi-text-secondary)]">
        只登记到期提醒（无凭据字段）；更新凭据请走受控入口。
      </p>
      <Row>
        <Field label="来源 feed URL">
          <input className={inputCls} value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} />
        </Field>
        <Field label="凭据到期日">
          <input type="date" className={inputCls} value={expiresOn} onChange={(e) => setExpiresOn(e.target.value)} />
        </Field>
        <Field label="备注（找谁续）">
          <input className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <Button variant="primary" size="sm" disabled={!feedUrl || !expiresOn || create.isPending} onClick={() => create.mutate()}>
          登记提醒
        </Button>
      </Row>
      {create.isError && <p role="alert">{errMsg(create.error)}</p>}
      <table className="w-full">
        <tbody>
          {list.data?.items.map((item) => (
            <tr key={item.id}>
              <td className={cellCls}>{item.feedUrl}</td>
              <td className={cellCls}>{item.expiresOn}</td>
              <td className={cellCls}>{item.bucket ? BUCKET_LABEL[item.bucket] ?? item.bucket : '已静默'}</td>
              <td className={cellCls}>
                <input
                  type="date"
                  className={inputCls}
                  value={renewDates[item.id] ?? ''}
                  onChange={(e) => setRenewDates((prev) => ({ ...prev, [item.id]: e.target.value }))}
                  aria-label={`续期到（${item.feedUrl}）`}
                />
                <Button
                  size="sm"
                  className="ml-1"
                  disabled={!renewDates[item.id] || renew.isPending}
                  onClick={() => renew.mutate({ id: item.id, date: renewDates[item.id] })}
                >
                  续期
                </Button>
                <Button size="sm" className="ml-1" disabled={dismiss.isPending} onClick={() => dismiss.mutate(item.id)}>
                  静默
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---- NEW-209 回收箱 ----

function RecycleBinPanel() {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['new201-ops', 'bin'], queryFn: listBin })
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new201-ops', 'bin'] })
  const restore = useMutation({
    mutationFn: (id: string) => restoreBinRow(id),
    onSuccess: invalidate,
  })
  const discard = useMutation({
    mutationFn: (id: string) => discardBinRow(id),
    onSuccess: invalidate,
  })
  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--lumi-text-secondary)]">{list.data?.note}</p>
      {list.data?.items.length === 0 && (
        <p className="text-sm text-[var(--lumi-text-secondary)]">回收箱为空（退订时可选择进入回收箱）。</p>
      )}
      <table className="w-full">
        <tbody>
          {list.data?.items.map((row) => (
            <tr key={row.id}>
              <td className={cellCls}>{row.title ?? row.feedUrl}</td>
              <td className={cellCls}>{row.categoryLabel ?? '未分组'}</td>
              <td className={cellCls}>
                {row.status === 'kept'
                  ? row.expired
                    ? '已过保留期（可放弃）'
                    : `保留至 ${row.purgeAfter.slice(0, 10)}`
                  : row.status === 'restored'
                    ? '已恢复'
                    : '已放弃'}
              </td>
              <td className={cellCls}>
                {row.status === 'kept' && (
                  <>
                    <Button size="sm" variant="primary" disabled={restore.isPending} onClick={() => restore.mutate(row.id)}>
                      恢复订阅
                    </Button>
                    <Button size="sm" className="ml-1" disabled={discard.isPending} onClick={() => discard.mutate(row.id)}>
                      放弃
                    </Button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {restore.isError && <p role="alert">{errMsg(restore.error)}</p>}
    </div>
  )
}

// ---- NEW-202 停更观察 ----

const VERDICT_LABEL: Record<string, string> = {
  still_posting: '仍在发文',
  no_new_posts: '观察期内无新文',
  fetch_failure: '抓取失败（非停更）',
  no_data: '资料缺失（非停更）',
}

function ObservationPanel() {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['new201-ops', 'observations'], queryFn: () => listObservations() })
  const [feedUrl, setFeedUrl] = useState('')
  const [days, setDays] = useState(14)
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new201-ops', 'observations'] })
  const create = useMutation({
    mutationFn: () => createObservation({ feedUrl, days }),
    onSuccess: () => {
      setFeedUrl('')
      invalidate()
    },
  })
  const extend = useMutation({
    mutationFn: (id: string) => extendObservation(id, 30),
    onSuccess: invalidate,
  })
  const close = useMutation({
    mutationFn: ({ id, resolution }: { id: string; resolution: 'continue' | 'unsubscribed' }) =>
      closeObservation(id, resolution),
    onSuccess: invalidate,
  })
  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--lumi-text-secondary)]">
        系统绝不自动停订；抓取失败与资料缺失不构成停更证据。
      </p>
      <Row>
        <Field label="来源 feed URL">
          <input className={inputCls} value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} />
        </Field>
        <Field label="观察天数（7-180）">
          <input type="number" min={7} max={180} className={inputCls} value={days} onChange={(e) => setDays(Number(e.target.value))} />
        </Field>
        <Button variant="primary" size="sm" disabled={!feedUrl || create.isPending} onClick={() => create.mutate()}>
          开始观察
        </Button>
      </Row>
      {create.isError && <p role="alert">{errMsg(create.error)}</p>}
      <table className="w-full">
        <tbody>
          {list.data?.items.map((item) => (
            <tr key={item.id}>
              <td className={cellCls}>{item.feedUrl}</td>
              <td className={cellCls}>
                {VERDICT_LABEL[item.verdict ?? ''] ?? item.verdict ?? '—'}
                {item.fetchPaused ? '（抓取暂停中）' : ''}
              </td>
              <td className={cellCls}>
                {item.expired ? '已到期待复核' : `至 ${item.endsAt.slice(0, 10)}`}
              </td>
              <td className={cellCls}>
                {item.status === 'active' && (
                  <>
                    <Button size="sm" disabled={extend.isPending} onClick={() => extend.mutate(item.id)}>
                      续 30 天
                    </Button>
                    <Button size="sm" className="ml-1" disabled={close.isPending} onClick={() => close.mutate({ id: item.id, resolution: 'continue' })}>
                      收尾（保留订阅）
                    </Button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---- NEW-206 阅读日历 ----

function CalendarPanel({ onOpenEntry }: { onOpenEntry: (ref: string) => void }) {
  const [feedUrl, setFeedUrl] = useState('')
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [submitted, setSubmitted] = useState<{ feedUrl: string; month: string } | null>(null)
  const calendar = useQuery({
    queryKey: ['new201-ops', 'calendar', submitted],
    queryFn: () => getFeedCalendar(submitted!.feedUrl, submitted!.month),
    enabled: submitted !== null,
  })
  const view: CalendarView | undefined = calendar.data
  return (
    <div className="space-y-3">
      <Row>
        <Field label="来源 feed URL">
          <input className={inputCls} value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} />
        </Field>
        <Field label="月份">
          <input type="month" className={inputCls} value={month} onChange={(e) => setMonth(e.target.value)} />
        </Field>
        <Button variant="primary" size="sm" disabled={!feedUrl || !month} onClick={() => setSubmitted({ feedUrl, month })}>
          查看月历
        </Button>
      </Row>
      {calendar.isError && <p role="alert">{errMsg(calendar.error)}</p>}
      {view && (
        <div className="space-y-1 text-sm">
          <p className="text-xs text-[var(--lumi-text-secondary)]">
            {view.coverage === 'no_projection_data'
              ? '该来源在投影中暂无条目（资料缺失 ≠ 当月没有发文）。'
              : `当月 ${view.totalEntries} 条${view.fetchPaused ? '；该来源抓取暂停中，数据可能滞后' : ''}。`}
          </p>
          {view.days.map((day) => (
            <div key={day.date}>
              <p className="mt-2 text-xs font-medium">{day.date}（{day.count} 条）</p>
              <ul>
                {day.sample.map((entry) => (
                  <li key={entry.entryRef}>
                    <button
                      type="button"
                      className="text-sm underline decoration-dotted"
                      onClick={() => onOpenEntry(entry.entryRef)}
                    >
                      {entry.title || entry.publishedAt}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {view.coverage === 'projection' && view.days.length === 0 && (
            <p className="text-sm text-[var(--lumi-text-secondary)]">当月没有发文。</p>
          )}
        </div>
      )}
    </div>
  )
}

// ---- NEW-203 分流视图 ----

function ViewsPanel({ onOpenEntry }: { onOpenEntry: (ref: string) => void }) {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['new201-ops', 'views'], queryFn: () => listViews() })
  const [feedUrl, setFeedUrl] = useState('')
  const [name, setName] = useState('')
  const [field, setField] = useState('title')
  const [value, setValue] = useState('')
  const [openViewId, setOpenViewId] = useState<string | null>(null)
  const entries = useQuery({
    queryKey: ['new201-ops', 'view-entries', openViewId],
    queryFn: () => getViewEntries(openViewId!),
    enabled: openViewId !== null,
  })
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new201-ops', 'views'] })
  const create = useMutation({
    mutationFn: () => createView({ feedUrl, name, field, value }),
    onSuccess: () => {
      setName('')
      setValue('')
      invalidate()
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteView(id),
    onSuccess: invalidate,
  })
  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--lumi-text-secondary)]">
        分流是读取侧视图：同一抓取任务、条目身份不变。
      </p>
      <Row>
        <Field label="来源 feed URL">
          <input className={inputCls} value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} />
        </Field>
        <Field label="视图名">
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="匹配列">
          <select className={inputCls} value={field} onChange={(e) => setField(e.target.value)}>
            <option value="title">标题</option>
            <option value="content">正文</option>
            <option value="author">作者</option>
          </select>
        </Field>
        <Field label="包含关键词">
          <input className={inputCls} value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
        <Button variant="primary" size="sm" disabled={!feedUrl || !name || !value || create.isPending} onClick={() => create.mutate()}>
          创建视图
        </Button>
      </Row>
      {create.isError && <p role="alert">{errMsg(create.error)}</p>}
      <ul className="space-y-1">
        {list.data?.items.map((view) => (
          <li key={view.id} className="text-sm">
            <button
              type="button"
              className="underline decoration-dotted"
              onClick={() => setOpenViewId((prev) => (prev === view.id ? null : view.id))}
            >
              {view.name}
            </button>
            <span className="ml-2 text-xs text-[var(--lumi-text-secondary)]">
              {view.field} ⊃ {view.value}
            </span>
            <Button size="sm" className="ml-2" disabled={remove.isPending} onClick={() => remove.mutate(view.id)}>
              删除
            </Button>
          </li>
        ))}
      </ul>
      {entries.data && (
        <div>
          <p className="text-xs text-[var(--lumi-text-secondary)]">{entries.data.note}</p>
          <ul>
            {entries.data.entries.map((entry) => (
              <li key={entry.entryRef}>
                <button type="button" className="text-sm underline decoration-dotted" onClick={() => onOpenEntry(entry.entryRef)}>
                  {entry.title || entry.entryRef}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {openViewId && entries.data && entries.data.entries.length === 0 && (
        <p className="text-sm text-[var(--lumi-text-secondary)]">视图暂未命中条目。</p>
      )}
    </div>
  )
}

// ---- NEW-205 保留策略 ----

function RetentionPanel() {
  const [feedUrl, setFeedUrl] = useState('')
  const [days, setDays] = useState(180)
  const [dryRun, setDryRun] = useState<RetentionDryRun | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [enabled, setEnabled] = useState<{ pruned: number } | null>(null)
  const preview = useMutation({ mutationFn: () => retentionDryRun({ feedUrl, days }), onSuccess: setDryRun })
  const enable = useMutation({
    mutationFn: () => retentionEnable({ feedUrl, days, confirmed }),
    onSuccess: (result) => setEnabled({ pruned: result.pruned }),
  })
  return (
    <div className="space-y-3">
      <Row>
        <Field label="来源 feed URL">
          <input className={inputCls} value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} />
        </Field>
        <Field label="保留天数（7-3650）">
          <input type="number" min={7} max={3650} className={inputCls} value={days} onChange={(e) => setDays(Number(e.target.value))} />
        </Field>
        <Button size="sm" variant="primary" disabled={!feedUrl || preview.isPending} onClick={() => preview.mutate()}>
          预演
        </Button>
      </Row>
      {preview.isError && <p role="alert">{errMsg(preview.error)}</p>}
      {dryRun && (
        <div className="space-y-1 text-sm">
          <p>将保留：收藏 {dryRun.preserved.starredEntries} 条 · 批注 {dryRun.preserved.annotations} 条 · 书签 {dryRun.preserved.libraryBookmarks} 条</p>
          <p>将回收（普通缓存）：{dryRun.reclaimed.prunableEntries} 条（早于 {dryRun.reclaimed.cutoff.slice(0, 10)}）</p>
          <p className="text-xs text-[var(--lumi-text-secondary)]">{dryRun.note}</p>
          <label className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            我已看过预演，确认启用该保留策略
          </label>
          <Button size="sm" variant="primary" disabled={!confirmed || enable.isPending} onClick={() => enable.mutate()}>
            启用
          </Button>
        </div>
      )}
      {enable.isError && <p role="alert">{errMsg(enable.error)}</p>}
      {enabled && <p className="text-sm">已启用；本次回收 {enabled.pruned} 条普通缓存。</p>}
    </div>
  )
}

// ---- NEW-201 接管向导 ----

function TakeoverPanel() {
  const qc = useQueryClient()
  const [opml, setOpml] = useState('')
  const [plan, setPlan] = useState<TakeoverPlan | null>(null)
  const [subscribeChecked, setSubscribeChecked] = useState<Set<string>>(new Set())
  const [moveChecked, setMoveChecked] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<string | null>(null)
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new201-ops', 'takeover'] })
  const preview = useMutation({
    mutationFn: () => takeoverPreview(opml),
    onSuccess: (nextPlan) => {
      setPlan(nextPlan)
      setSubscribeChecked(new Set(nextPlan.toSubscribe.map((item) => item.feedUrl)))
      setMoveChecked(new Set())
      setResult(null)
    },
  })
  const apply = useMutation({
    mutationFn: () =>
      takeoverApply({
        items: [
          ...plan!.toSubscribe
            .filter((item) => subscribeChecked.has(item.feedUrl))
            .map((item) => ({
              action: 'subscribe',
              feedUrl: item.feedUrl,
              title: item.title || undefined,
              categoryLabel: item.categoryLabel ?? undefined,
            })),
          ...plan!.alreadySubscribed
            .filter((item) => item.categoryDiffers && moveChecked.has(item.feedUrl))
            .map((item) => ({
              action: 'move',
              feedUrl: item.feedUrl,
              categoryLabel: item.opmlCategory ?? undefined,
            })),
        ],
        label: '从旧实例接管',
      }),
    onSuccess: (summary) => {
      setResult(`新建 ${summary.created} · 已订跳过 ${summary.skippedExisting} · 继承目录 ${summary.moved} · 失败 ${summary.failed}`)
      invalidate()
    },
  })
  return (
    <div className="space-y-3">
      <Field label="粘贴旧实例导出的 OPML">
        <textarea className={inputCls} rows={4} value={opml} onChange={(e) => setOpml(e.target.value)} />
      </Field>
      <Button size="sm" variant="primary" disabled={!opml || preview.isPending} onClick={() => preview.mutate()}>
        预演映射
      </Button>
      {preview.isError && <p role="alert">{errMsg(preview.error)}</p>}
      {plan && (
        <div className="space-y-2 text-sm">
          <p>将新建（已勾选的才会订阅）：</p>
          <ul>
            {plan.toSubscribe.map((item) => (
              <li key={item.feedUrl}>
                <label className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={subscribeChecked.has(item.feedUrl)}
                    onChange={(e) =>
                      setSubscribeChecked((prev) => {
                        const next = new Set(prev)
                        if (e.target.checked) next.add(item.feedUrl)
                        else next.delete(item.feedUrl)
                        return next
                      })
                    }
                  />
                  {item.title || item.feedUrl}
                  {item.categoryLabel ? `（目录：${item.categoryLabel}）` : ''}
                </label>
              </li>
            ))}
          </ul>
          <p>已在订阅（绝不重复订阅）：</p>
          <ul>
            {plan.alreadySubscribed.map((item) => (
              <li key={item.feedUrl}>
                <label className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    disabled={!item.categoryDiffers}
                    checked={moveChecked.has(item.feedUrl)}
                    onChange={(e) =>
                      setMoveChecked((prev) => {
                        const next = new Set(prev)
                        if (e.target.checked) next.add(item.feedUrl)
                        else next.delete(item.feedUrl)
                        return next
                      })
                    }
                  />
                  {item.feedUrl}
                  {item.categoryDiffers ? `（可继承目录：${item.opmlCategory}）` : '（目录一致）'}
                </label>
              </li>
            ))}
          </ul>
          {plan.invalidCount > 0 && (
            <p className="text-xs text-[var(--lumi-text-secondary)]">导出中 {plan.invalidCount} 项不可用，已跳过。</p>
          )}
          <Button size="sm" variant="primary" disabled={apply.isPending} onClick={() => apply.mutate()}>
            应用
          </Button>
        </div>
      )}
      {apply.isError && <p role="alert">{errMsg(apply.error)}</p>}
      {result && <p className="text-sm">{result}</p>}
    </div>
  )
}

// ---- NEW-204 镜像比对 ----

function MirrorPanel() {
  const [urlA, setUrlA] = useState('')
  const [urlB, setUrlB] = useState('')
  const [result, setResult] = useState<MirrorCompareResult | null>(null)
  const compare = useMutation({ mutationFn: () => mirrorCompare(urlA, urlB), onSuccess: setResult })
  const choose = useMutation({
    mutationFn: (picked: 'A' | 'B') => recordMirrorChoice({ urlA, urlB, picked }),
  })
  return (
    <div className="space-y-3">
      <Row>
        <Field label="候选 A URL">
          <input className={inputCls} value={urlA} onChange={(e) => setUrlA(e.target.value)} />
        </Field>
        <Field label="候选 B URL">
          <input className={inputCls} value={urlB} onChange={(e) => setUrlB(e.target.value)} />
        </Field>
        <Button size="sm" variant="primary" disabled={!urlA || !urlB || compare.isPending} onClick={() => compare.mutate()}>
          比对
        </Button>
      </Row>
      {compare.isError && <p role="alert">{errMsg(compare.error)}</p>}
      {result && (
        <div className="space-y-1 text-sm">
          <p>候选 A：{result.sideA.error ?? `${result.sideA.title ?? ''}（${result.sideA.entryCount ?? 0} 条）`}</p>
          <p>候选 B：{result.sideB.error ?? `${result.sideB.title ?? ''}（${result.sideB.entryCount ?? 0} 条）`}</p>
          {result.comparison ? (
            <p>
              共有 {result.comparison.commonCount} · 仅 A {result.comparison.onlyACount} · 仅 B{' '}
              {result.comparison.onlyBCount}
            </p>
          ) : (
            <p className="text-xs text-[var(--lumi-text-secondary)]">一侧不可用，无法比对覆盖差异。</p>
          )}
          <Row>
            <Button size="sm" disabled={choose.isPending} onClick={() => choose.mutate('A')}>
              选用 A（记录台账）
            </Button>
            <Button size="sm" disabled={choose.isPending} onClick={() => choose.mutate('B')}>
              选用 B（记录台账）
            </Button>
          </Row>
          {choose.isSuccess && <p className="text-xs text-[var(--lumi-text-secondary)]">抉择已记录；订阅请在来源页确认执行。</p>}
        </div>
      )}
    </div>
  )
}

// ---- NEW-207 RSSHub 参数表单 ----

function RssHubFormPanel() {
  const routes = useQuery({ queryKey: ['new201-ops', 'rsshub-routes'], queryFn: listRssHubRoutes })
  const [routeId, setRouteId] = useState('')
  const schema = useQuery({
    queryKey: ['new201-ops', 'rsshub-schema', routeId],
    queryFn: () => getRssHubFormSchema(routeId),
    enabled: routeId !== '',
  })
  const [values, setValues] = useState<Record<string, string>>({})
  const [errors, setErrors] = useState<{ key: string; message: string }[]>([])
  const [generatedPath, setGeneratedPath] = useState<string | null>(null)
  const [appliedUrl, setAppliedUrl] = useState<string | null>(null)
  const validate = useMutation({
    mutationFn: () => validateRssHubForm(routeId, values),
    onSuccess: (result) => {
      setErrors(result.valid ? [] : result.errors)
      setGeneratedPath(result.generatedPath ?? null)
      setAppliedUrl(null)
    },
  })
  const apply = useMutation({
    mutationFn: () => applyRssHubForm(routeId, { params: values, confirmed: true }),
    onSuccess: (result) => setAppliedUrl(result.subscription.feedUrl),
    onError: () => setAppliedUrl(null),
  })
  const typedSchema: RssHubFormSchema | undefined = schema.data
  return (
    <div className="space-y-3">
      <Field label="路由（来自 Lumi 目录）">
        <select
          className={inputCls}
          value={routeId}
          onChange={(e) => {
            setRouteId(e.target.value)
            setValues({})
            setErrors([])
            setGeneratedPath(null)
          }}
        >
          <option value="">选择路由…</option>
          {routes.data?.routes.map((route) => (
            <option key={route.id} value={route.id}>
              {route.title}
            </option>
          ))}
        </select>
      </Field>
      {typedSchema && (
        <div className="space-y-2">
          <p className="text-xs text-[var(--lumi-text-secondary)]">{typedSchema.description}（{typedSchema.pathTemplate}）</p>
          {typedSchema.parameters.map((parameter) => (
            <Field key={parameter.key} label={`${parameter.label}${parameter.required ? '（必填）' : ''} — ${parameter.help}`}>
              <input
                className={inputCls}
                value={values[parameter.key] ?? ''}
                placeholder={parameter.example}
                onChange={(e) => setValues((prev) => ({ ...prev, [parameter.key]: e.target.value }))}
              />
            </Field>
          ))}
          <Row>
            <Button size="sm" onClick={() => validate.mutate()}>
              校验参数
            </Button>
            <Button
              size="sm"
              variant="primary"
              disabled={!generatedPath || apply.isPending}
              onClick={() => apply.mutate()}
            >
              确认添加订阅
            </Button>
          </Row>
          {generatedPath && (
            <p className="text-xs text-[var(--lumi-text-secondary)]">生成地址：{generatedPath}（服务端拼装，无需手拼）</p>
          )}
          {errors.map((error) => (
            <p key={error.key} role="alert" className="text-xs">
              {error.key}：{error.message}
            </p>
          ))}
          {appliedUrl && <p className="text-sm">已订阅：{appliedUrl}</p>}
        </div>
      )}
      {apply.isError && <p role="alert">{errMsg(apply.error)}</p>}
    </div>
  )
}

// ---- 对话框本体 ----

export type SourceOpsTab =
  | 'pause'
  | 'credential'
  | 'recycle'
  | 'observation'
  | 'calendar'
  | 'views'
  | 'retention'
  | 'takeover'
  | 'mirror'
  | 'rsshub'

const TAB_OPTIONS: { value: SourceOpsTab; label: string }[] = [
  { value: 'pause', label: '停机计划' },
  { value: 'observation', label: '停更观察' },
  { value: 'recycle', label: '回收箱' },
  { value: 'views', label: '分流视图' },
  { value: 'calendar', label: '阅读日历' },
  { value: 'retention', label: '保留策略' },
  { value: 'takeover', label: '接管向导' },
  { value: 'mirror', label: '镜像比对' },
  { value: 'rsshub', label: 'RSSHub 表单' },
  { value: 'credential', label: '认证到期' },
]

export function SourceOpsDialog({
  open,
  onClose,
  initialTab = 'pause',
}: {
  open: boolean
  onClose: () => void
  initialTab?: SourceOpsTab
}) {
  const [tab, setTab] = useState<SourceOpsTab>(initialTab)
  const selectEntry = useReaderUi((state) => state.selectEntry)
  const selectScope = useReaderUi((state) => state.selectScope)
  const openEntry = (ref: string) => {
    selectScope(ALL_SCOPE)
    selectEntry(ref)
    onClose()
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="来源运维工作台"
      panelClassName="max-w-2xl"
    >
      <Tabs
        aria-label="来源运维能力"
        value={tab}
        onValueChange={setTab}
        options={TAB_OPTIONS}
        panels={{
          pause: <PausePanel />,
          observation: <ObservationPanel />,
          recycle: <RecycleBinPanel />,
          views: <ViewsPanel onOpenEntry={openEntry} />,
          calendar: <CalendarPanel onOpenEntry={openEntry} />,
          retention: <RetentionPanel />,
          takeover: <TakeoverPanel />,
          mirror: <MirrorPanel />,
          rsshub: <RssHubFormPanel />,
          credential: <CredentialPanel />,
        }}
      />
    </Dialog>
  )
}
