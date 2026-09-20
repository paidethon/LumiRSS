/** F001 来源新鲜度预警 —— 阈值设置对话框 + 超期来源面板。
 *
 * 口径诚实：面板条目标注判定依据（basis）——latest_entry = 按「最新
 * 发布时间」估算（发布旧 ≠ 抓取失败）；unknown = 无条目证据不判超期，
 * 服务端不下发该类条目。 */

import { useEffect, useState } from 'react'
import { AlertCircle, Loader2, ShieldAlert } from 'lucide-react'
import {
  useSetSourceOverrideMutation,
  useStaleSourcesQuery,
} from '../api/queries'
import type { StaleSourceItem } from '../api/client'
import { managementErrorText } from '../lib/management-errors'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

export const STALE_ALERT_HOURS_MIN = 1
export const STALE_ALERT_HOURS_MAX = 8760

/** basis → 人类可读判定依据（诚实标注，不冒充抓取状态）。 */
export function staleBasisLabel(basis: StaleSourceItem['basis']): string {
  if (basis === 'latest_entry') return '依据：最新发布时间'
  if (basis === 'fetch_time') return '依据：最近抓取时间'
  return '依据：未知'
}

/** F001 阈值设置对话框：小时数（空 = 关闭预警）。 */
export function SourceStaleAlertDialog({
  open,
  onClose,
  subscription,
}: {
  open: boolean
  onClose: () => void
  subscription: { feedUrl: string; title: string } | null
}) {
  const [hoursText, setHoursText] = useState('')
  const mutation = useSetSourceOverrideMutation()

  useEffect(() => {
    if (open) {
      setHoursText('')
      mutation.reset()
    }
    // reset 是稳定引用；依赖只看 open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const busy = mutation.isPending
  const trimmed = hoursText.trim()
  const parsed = trimmed === '' ? null : Number(trimmed)
  const valid =
    trimmed === '' ||
    (Number.isInteger(parsed) &&
      parsed !== null &&
      parsed >= STALE_ALERT_HOURS_MIN &&
      parsed <= STALE_ALERT_HOURS_MAX)

  function close() {
    if (busy) return
    onClose()
  }

  function save(hours: number | null) {
    if (!subscription || busy) return
    mutation.mutate(
      { feedUrl: subscription.feedUrl, staleAlertHours: hours },
      { onSuccess: onClose },
    )
  }

  const errorText = mutation.isError ? managementErrorText(mutation.error) : null

  return (
    <Dialog
      open={open}
      onClose={close}
      title="新鲜度预警"
      footer={
        <>
          <Button variant="ghost" onClick={close} disabled={busy}>
            取消
          </Button>
          <Button variant="ghost" onClick={() => save(null)} disabled={busy}>
            关闭预警
          </Button>
          <Button
            variant="primary"
            disabled={busy || !valid || trimmed === ''}
            onClick={() => save(parsed)}
          >
            {busy ? (
              <>
                <Loader2 aria-hidden className="size-4 animate-spin" />
                保存中…
              </>
            ) : (
              '保存'
            )}
          </Button>
        </>
      }
    >
      {subscription !== null && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (valid) save(parsed)
          }}
          className="flex flex-col gap-4"
        >
          <p className="text-sm text-[var(--lumi-text-secondary)]">
            为「{subscription.title}」设置超期小时数（超过该时长没有新内容时，
            在「异常来源」面板中提醒）。留空并保存 = 关闭该来源的预警。
          </p>
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="stale-alert-hours"
              className="text-sm font-medium text-[var(--lumi-text-primary)]"
            >
              超期阈值（小时，{STALE_ALERT_HOURS_MIN}–{STALE_ALERT_HOURS_MAX}）
            </label>
            <input
              id="stale-alert-hours"
              type="number"
              inputMode="numeric"
              min={STALE_ALERT_HOURS_MIN}
              max={STALE_ALERT_HOURS_MAX}
              value={hoursText}
              onChange={(e) => setHoursText(e.target.value)}
              placeholder="例如 48"
              autoFocus
              className="min-h-11 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-primary)] focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]"
              aria-invalid={!valid}
            />
            {!valid && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                请输入 {STALE_ALERT_HOURS_MIN}–{STALE_ALERT_HOURS_MAX} 之间的整数小时数，或留空关闭预警。
              </p>
            )}
          </div>
          {errorText !== null && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
            >
              <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
              <span className="min-w-0">
                <span className="block font-medium">{errorText.title}</span>
                {errorText.detail !== null && (
                  <span className="mt-0.5 block text-xs opacity-80">{errorText.detail}</span>
                )}
              </span>
            </div>
          )}
        </form>
      )}
    </Dialog>
  )
}

/** F001 超期来源面板（页头「异常来源」开关展开）。 */
export function StaleSourcesPanel() {
  const query = useStaleSourcesQuery(true)
  const items = query.data?.items ?? []

  if (query.isPending) {
    return (
      <section
        aria-label="异常来源"
        data-testid="stale-sources-panel"
        className="mb-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      >
        <Skeleton className="h-6 w-40" />
        <Skeleton className="mt-2 h-10 w-full" />
      </section>
    )
  }

  if (query.isError) {
    return (
      <section
        aria-label="异常来源"
        data-testid="stale-sources-panel"
        className="mb-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      >
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">
          超期来源加载失败
        </p>
        <Button size="sm" variant="secondary" className="mt-2" onClick={() => query.refetch()}>
          重试
        </Button>
      </section>
    )
  }

  return (
    <section
      aria-label="异常来源"
      data-testid="stale-sources-panel"
      className="mb-3 overflow-hidden rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]"
    >
      <h3 className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
        <ShieldAlert aria-hidden className="size-3.5" />
        异常来源（{items.length}）
      </h3>
      {items.length === 0 ? (
        <div className="border-t border-[var(--lumi-separator)]">
          <EmptyState
            icon={<ShieldAlert aria-hidden className="size-6" />}
            title="没有超期来源"
            description="在订阅行菜单「新鲜度预警」设置阈值后，超期来源会显示在这里。"
          />
        </div>
      ) : (
        <ul className="divide-y divide-[var(--lumi-separator)] border-t border-[var(--lumi-separator)]">
          {items.map((item) => (
            <li key={item.feedUrl} className="px-3.5 py-2.5" data-testid="stale-source-item">
              <span className="block truncate text-sm font-medium text-[var(--lumi-text-primary)]">
                {item.title || item.feedUrl}
              </span>
              <span className="mt-0.5 block text-xs text-[var(--lumi-text-secondary)]">
                约 {item.ageHours ?? '?'} 小时未更新 · 阈值 {item.staleAlertHours} 小时 ·{' '}
                {staleBasisLabel(item.basis)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
