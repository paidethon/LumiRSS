/** NotificationCenterPanel — NEW-391 应用内通知收件箱 + NEW-394 撤销提示。
 *
 * - 只展示真实事件（BFF record_event 登记的收尾事实），本面板没有任何
 *   「造一条通知」的入口；
 * - 按类型过滤 + 全部已读（集合语义）+ 逐条 dismiss（保留清理是显式动作）；
 * - NEW-394：读取侧联判撤销登记——invalidReason 存在时不渲染任何动作
 *   按钮，只显示失效原因；本人可显式登记「原事件已撤销」。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createAggregationRule,
  deleteAggregationRule,
  dismissNotification,
  fetchAggregationRules,
  fetchGroupedNotifications,
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  registerRevocation,
  setAggregationRuleEnabled,
  type NotificationItem,
  type NotificationKind,
} from '../../api/new391'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  SubSection,
  actionButtonClass,
  inputClass,
  labelClass,
} from './parts'

const KIND_LABELS: Record<NotificationKind | 'all', string> = {
  all: '全部',
  task_completed: '任务完成',
  task_failed: '任务失败',
  share_event: '共享事件',
  help_answered: '帮助回复',
}

function InboxItem({ item }: { item: NotificationItem }) {
  const [revokeOpen, setRevokeOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [revokeError, setRevokeError] = useState('')
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['new391', 'notifications'] })
  }
  const markRead = useMutation({
    mutationFn: () => markNotificationRead(item.id),
    onSuccess: invalidate,
  })
  const dismiss = useMutation({
    mutationFn: () => dismissNotification(item.id),
    onSuccess: invalidate,
  })
  const revoke = useMutation({
    mutationFn: () => registerRevocation(item.id, reason.trim()),
    onSuccess: () => {
      setRevokeOpen(false)
      setReason('')
      setRevokeError('')
      invalidate()
    },
    onError: () => setRevokeError('登记失败：需要填写失效原因。'),
  })
  const revoked = item.invalidReason !== null
  return (
    <li
      data-n391-notification={item.id}
      className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
          {item.title}
          {item.readAt === null && (
            <span className="ml-2 align-middle text-xs text-[var(--lumi-accent)]">
              未读
            </span>
          )}
        </span>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">
          {KIND_LABELS[item.kind] ?? item.kind}
        </span>
      </div>
      {item.body && (
        <p className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
          {item.body}
        </p>
      )}
      {revoked ? (
        <StatusLine tone="error" testId={`invalid-${item.id}`}>
          动作已失效：{item.invalidReason}
        </StatusLine>
      ) : null}
      {revoked ? null : (
        <div className="flex flex-wrap items-center gap-2">
          {item.actionable && item.readAt === null && (
            <Button size="sm" loading={markRead.isPending} onClick={() => markRead.mutate()}>
              标记已读
            </Button>
          )}
          <button
            type="button"
            aria-expanded={revokeOpen}
            className={actionButtonClass}
            onClick={() => setRevokeOpen((v) => !v)}
          >
            原事件已撤销？
          </button>
        </div>
      )}
      {revokeOpen && (
        <div className="flex flex-col gap-1">
          <label className={labelClass} htmlFor={`revoke-reason-${item.id}`}>
            失效原因（原事件已撤销或权限失效时登记）
          </label>
          <input
            id={`revoke-reason-${item.id}`}
            className={inputClass}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          {revokeError && <StatusLine tone="error">{revokeError}</StatusLine>}
          <Button
            size="sm"
            loading={revoke.isPending}
            onClick={() => revoke.mutate()}
          >
            登记撤销
          </Button>
        </div>
      )}
      <Button
        size="sm"
        variant="ghost"
        loading={dismiss.isPending}
        onClick={() => dismiss.mutate()}
      >
        删除这条通知
      </Button>
    </li>
  )
}

export function NotificationCenterPanel() {
  const [kind, setKind] = useState<NotificationKind | 'all'>('all')
  const effective = kind === 'all' ? undefined : kind
  const inbox = useQuery({
    queryKey: ['new391', 'notifications', kind],
    queryFn: () => fetchNotifications({ kind: effective }),
  })
  const readAll = useMutation({
    mutationFn: () => markAllNotificationsRead(effective ?? null),
    onSuccess: () => {
      void inbox.refetch()
    },
  })
  return (
    <div data-n391-panel="notification-center" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="按类型过滤通知">
        {(Object.keys(KIND_LABELS) as (NotificationKind | 'all')[]).map((key) => (
          <Button
            key={key}
            size="sm"
            variant={kind === key ? 'primary' : 'secondary'}
            onClick={() => setKind(key)}
          >
            {KIND_LABELS[key]}
          </Button>
        ))}
      </div>
      {inbox.isLoading && <StatusLine tone="info">正在加载通知…</StatusLine>}
      {inbox.isError && (
        <StatusLine tone="error">通知加载失败，请稍后重试。</StatusLine>
      )}
      {inbox.data && (
        <>
          <div className="flex items-center justify-between gap-2">
            <NoteText>
              未读 {inbox.data.unread} 条；通知只来自真实事件，私人事件只给本人。
            </NoteText>
            <Button
              size="sm"
              loading={readAll.isPending}
              onClick={() => readAll.mutate()}
            >
              全部已读
            </Button>
          </div>
          {inbox.data.items.length === 0 ? (
            <NoteText>暂无通知——没有真实事件就没有通知行。</NoteText>
          ) : (
            <ul className="flex flex-col gap-2">
              {inbox.data.items.map((item) => (
                <InboxItem key={item.id} item={item} />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

/** 聚合规则入口（NEW-392）挂在同一收件箱面板下的独立导出，便于设置页
 * 按需组合；分组展开即逐条原始事件。 */
export function AggregationRulesPanel() {
  const [kind, setKind] = useState<NotificationKind>('task_failed')
  const [source, setSource] = useState('')
  const [label, setLabel] = useState('')
  const [error, setError] = useState('')
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['new391', 'rules'] })
    void queryClient.invalidateQueries({ queryKey: ['new391', 'grouped'] })
  }
  const rules = useQuery({
    queryKey: ['new391', 'rules'],
    queryFn: fetchAggregationRules,
  })
  const grouped = useQuery({
    queryKey: ['new391', 'grouped'],
    queryFn: fetchGroupedNotifications,
  })
  const create = useMutation({
    mutationFn: () => createAggregationRule(kind, source.trim(), label.trim()),
    onSuccess: () => {
      setSource('')
      setLabel('')
      setError('')
      invalidate()
    },
    onError: () => setError('创建失败：来源不能为空，同来源同类型至多一条。'),
  })
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      setAggregationRuleEnabled(id, enabled),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteAggregationRule(id),
    onSuccess: invalidate,
  })
  return (
    <div data-n391-panel="aggregation-rules" className="flex flex-col gap-3">
      <NoteText>
        聚合只改变展示：每个原始事件仍完整存在，展开摘要即逐条事件。
      </NoteText>
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label className={labelClass} htmlFor="agg-kind">
              通知类型
            </label>
            <select
              id="agg-kind"
              className={inputClass}
              value={kind}
              onChange={(event) => setKind(event.target.value as NotificationKind)}
            >
              {(Object.keys(KIND_LABELS) as NotificationKind[])
                .filter((key) => key !== 'all')
                .map((key) => (
                  <option key={key} value={key}>
                    {KIND_LABELS[key]}
                  </option>
                ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className={labelClass} htmlFor="agg-source">
              来源（精确匹配）
            </label>
            <input
              id="agg-source"
              className={inputClass}
              value={source}
              onChange={(event) => setSource(event.target.value)}
              placeholder="如 daily_digest"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className={labelClass} htmlFor="agg-label">
              标签（可选）
            </label>
            <input
              id="agg-label"
              className={inputClass}
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </div>
          <Button loading={create.isPending} onClick={() => create.mutate()}>
            创建规则
          </Button>
        </div>
        {error && <StatusLine tone="error">{error}</StatusLine>}
      </div>
      {rules.data && rules.data.rules.length > 0 && (
        <ul className="flex flex-col gap-1">
          {rules.data.rules.map((rule) => (
            <li
              key={rule.id}
              data-n391-rule={rule.id}
              className="flex items-center justify-between gap-2 text-sm text-[var(--lumi-text-primary)]"
            >
              <span>
                {rule.label || rule.source}（{KIND_LABELS[rule.kind as NotificationKind] ?? rule.kind}）
                {rule.enabled ? '' : ' · 已停用'}
              </span>
              <span className="flex gap-1">
                <Button
                  size="sm"
                  onClick={() =>
                    toggle.mutate({ id: rule.id, enabled: !rule.enabled })
                  }
                >
                  {rule.enabled ? '停用' : '启用'}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => remove.mutate(rule.id)}>
                  删除
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {grouped.data && (
        <div className="flex flex-col gap-2">
          {grouped.data.groups.length === 0 ? (
            <NoteText>当前没有聚合分组（未命中启用的规则）。</NoteText>
          ) : (
            grouped.data.groups.map((group) => (
              <SubSection
                key={`${group.kind}:${group.source}`}
                id={`group-${group.kind}-${group.source}`}
                label={`聚合：${KIND_LABELS[group.kind as NotificationKind] ?? group.kind} × ${group.source}（${group.total} 条 / 未读 ${group.unread}）`}
              >
                <ul className="flex flex-col gap-1">
                  {group.items.map((item) => (
                    <li key={item.id} className="text-sm text-[var(--lumi-text-secondary)]">
                      {item.title}
                      {item.invalidReason && (
                        <span className="ml-1 text-[var(--lumi-danger)]">
                          （已失效：{item.invalidReason}）
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </SubSection>
            ))
          )}
        </div>
      )}
    </div>
  )
}
