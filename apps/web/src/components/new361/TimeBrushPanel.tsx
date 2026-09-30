/** TimeBrushPanel — NEW-361 时间范围刷选（SearchPage 研究工具）。
 *
 * 在本人搜索结果时间分布上选择区间：桶计数只由实际命中生成（BFF
 * 同链 SQL 聚合；空桶补 0 仅为渲染）。点击桶 = 把该桶区间交给父级
 * （父级用既有 GET /search 的 from/to 出文章），本组件不重复造
 * 文章列表路径。
 */

import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { CalendarRange } from 'lucide-react'
import { fetchTimeBrush } from '../../api/new361'
import { cx } from '../ui/cx'

const WINDOWS: { label: string; days: number }[] = [
  { label: '近 30 天', days: 30 },
  { label: '近 92 天', days: 92 },
  { label: '近一年', days: 365 },
]

function isoDay(offsetDays: number): string {
  const date = new Date(Date.now() - offsetDays * 86_400_000)
  return date.toISOString().slice(0, 10)
}

export function TimeBrushPanel({
  query,
  onApplyRange,
}: {
  query: string
  onApplyRange: (from: string, to: string) => void
}) {
  const [days, setDays] = useState(30)
  const enabled = query.trim() !== ''
  const brush = useQuery({
    queryKey: ['new361', 'time-brush', query, days],
    queryFn: () =>
      fetchTimeBrush({ q: query, from: isoDay(days - 1), to: isoDay(0) }),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
  const body = brush.data
  const maxCount = body ? Math.max(1, ...body.buckets.map((bucket) => bucket.count)) : 1

  return (
    <section
      data-testid="n361-time-brush"
      aria-label="时间范围刷选"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <CalendarRange aria-hidden className="size-3.5" />
        时间范围刷选
        {body && (
          <span className="font-normal text-[var(--lumi-text-tertiary)]">
            （实际命中 {body.total} 条 · {body.granularity === 'day' ? '按日' : '按月'}）
          </span>
        )}
      </p>
      <div role="group" aria-label="刷选窗口" className="flex gap-1.5">
        {WINDOWS.map((preset) => (
          <button
            key={preset.days}
            type="button"
            aria-pressed={days === preset.days}
            onClick={() => setDays(preset.days)}
            className={cx(
              'min-h-7 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              days === preset.days
                ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            {preset.label}
          </button>
        ))}
      </div>
      {brush.isPending && enabled && (
        <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">
          统计中…
        </p>
      )}
      {brush.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          分布刷选失败：{brush.error instanceof Error ? brush.error.message : '请稍后重试。'}
        </p>
      )}
      {body && (
        <>
          <div
            data-testid="n361-brush-buckets"
            role="group"
            aria-label="命中分布（点击桶查看该区间文章）"
            className="flex h-14 items-end gap-[2px]"
          >
            {body.buckets.map((bucket) => (
              <button
                key={bucket.key}
                type="button"
                data-testid="n361-brush-bucket"
                title={`${bucket.key}：${bucket.count} 条（点击查看）`}
                aria-label={`${bucket.key}：${bucket.count} 条`}
                onClick={() => onApplyRange(bucket.key, bucket.key)}
                className={cx(
                  'min-h-[2px] flex-1 rounded-t-[2px] transition-opacity',
                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  bucket.count > 0
                    ? 'bg-[var(--lumi-accent)] hover:opacity-80'
                    : 'cursor-default bg-[var(--lumi-border)]',
                )}
                style={
                  bucket.count > 0
                    ? { height: `${Math.max(10, Math.round((bucket.count / maxCount) * 100))}%` }
                    : { height: '2px' }
                }
              />
            ))}
          </div>
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            点击有命中的桶即可把结果刷选到该{body.granularity === 'day' ? '天' : '月'}。
          </p>
        </>
      )}
    </section>
  )
}
