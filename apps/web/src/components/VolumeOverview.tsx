/** VolumeOverview — F12：订阅收件量概览（可折叠，按需查询）。
 *
 * 按来源展示最近 N 天发布条目数与最近同步/发布时间，帮助识别信息
 * 过载与异常停更。口径：publishedCount 基于「发布时间」；投影未覆盖
 * 的订阅显示「未知」而不是 0（投影落后 ≠ 没有新内容）。 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'

import { getSubscriptionVolume } from '../../api/client'
import { cx } from '../ui/cx'

export function VolumeOverview() {
  const [open, setOpen] = useState(false)
  const [days, setDays] = useState(7)
  const volume = useQuery({
    queryKey: ['sources', 'volume', days],
    queryFn: ({ signal }) => getSubscriptionVolume(signal, days),
    enabled: open,
    staleTime: 60_000,
  })

  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      className="mb-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2"
      data-volume-overview
    >
      <summary
        className={cx(
          'flex cursor-pointer select-none items-center gap-1.5 text-xs font-medium',
          'text-[var(--lumi-text-secondary)] focus-visible:outline-2',
          'focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        )}
      >
        <ChevronDown
          aria-hidden
          className={cx('size-3.5 transition-transform', open && 'rotate-180')}
        />
        收件量概览
      </summary>
      {open ? (
        <div className="mt-2">
          <div className="mb-2 flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
            <span>统计窗口</span>
            <select
              aria-label="统计窗口天数"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 text-xs text-[var(--lumi-text-primary)]"
            >
              <option value={3}>最近 3 天</option>
              <option value={7}>最近 7 天</option>
              <option value={30}>最近 30 天</option>
            </select>
            <span className="text-[var(--lumi-text-tertiary)]">按发布时间统计</span>
          </div>
          {volume.isPending ? (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">统计中…</p>
          ) : volume.isError ? (
            <p className="text-xs text-[var(--lumi-text-secondary)]" role="alert">
              收件量统计失败（不影响订阅管理）。
            </p>
          ) : (
            <ul className="flex flex-col divide-y divide-[var(--lumi-separator)]">
              {(volume.data?.items ?? []).map((item) => (
                <li key={item.feedUrl} className="flex items-center justify-between gap-2 py-1.5">
                  <span className="min-w-0 truncate text-xs text-[var(--lumi-text-primary)]">
                    {item.title || item.feedUrl}
                  </span>
                  <span
                    className="shrink-0 text-xs text-[var(--lumi-text-secondary)]"
                    data-volume-count={item.publishedCount === null ? 'unknown' : item.publishedCount}
                  >
                    {item.publishedCount === null
                      ? '未知（投影未覆盖）'
                      : `${item.publishedCount} 篇`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </details>
  )
}
