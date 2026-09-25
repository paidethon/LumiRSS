/** RecentLoginsPanel — N008 最近登录（新设备提醒 + 批量标记已读）。
 *
 * 只读展示服务端 login_events（cap 20）：kind=new_device 且未读 →
 * 「新设备」徽标；「标记已读」批量确认（信任确认后，同设备再登录不再
 * 提醒）。加载/错误/空态都诚实呈现（空 = 尚无记录，不虚构）。 */

import { Clock, ShieldCheck } from 'lucide-react'
import { useLoginEvents, useMarkLoginEventsSeenMutation } from '../../api/queries'
import { Button } from '../ui/Button'

function formatEventTime(epoch: number): string {
  try {
    return new Date(epoch * 1000).toLocaleString()
  } catch {
    return ''
  }
}

export function RecentLoginsPanel() {
  const events = useLoginEvents()
  const markSeen = useMarkLoginEventsSeenMutation()

  if (events.isPending || events.isError) return null
  const items = events.data ?? []
  if (items.length === 0) return null

  const unreadCount = items.filter((event) => !event.seen).length

  return (
    <div
      className="mt-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5"
      data-lumi-login-events-panel=""
    >
      <div className="flex items-center gap-2">
        <Clock aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
        <p className="text-xs font-medium text-[var(--lumi-text-primary)]">
          最近登录（{items.length}）
        </p>
      </div>
      <ul className="mt-1.5 flex flex-col gap-1.5">
        {items.map((event) => (
          <li
            key={event.id}
            className="flex items-center gap-2 text-xs"
            data-lumi-login-event-row=""
            data-kind={event.kind}
            data-seen={event.seen ? 'true' : 'false'}
          >
            <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">
              {event.deviceLabel || '未知设备'}
              <span className="ml-2 text-[var(--lumi-text-tertiary)]">
                {formatEventTime(event.createdAt)}
              </span>
            </span>
            {event.kind === 'new_device' && !event.seen && (
              <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-danger)] px-2 py-0.5 text-[11px] text-white">
                新设备
              </span>
            )}
          </li>
        ))}
      </ul>
      {unreadCount > 0 && (
        <div className="mt-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => markSeen.mutate(undefined)}
            disabled={markSeen.isPending}
            data-lumi-login-events-seen=""
          >
            <ShieldCheck aria-hidden className="size-4" />
            标记已读（{unreadCount}）
          </Button>
        </div>
      )}
      <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
        标记已读后，同一设备再次登录不再提醒；可在上方会话列表随时撤销登录。
      </p>
    </div>
  )
}
