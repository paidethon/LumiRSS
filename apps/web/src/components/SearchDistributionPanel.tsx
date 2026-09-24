/** SearchDistributionPanel — N145 来源分布 + 近 30 日柱状（SearchPage）。
 *
 * 与结果区同参（同 query + 过滤链 + 权限作用域）拉取 SQL 聚合：
 * - 来源列表（top 20，超界诚实标注）：点击来源 = 应用该来源过滤
 *   （与手工在高级面板选同一来源得到同一结果集）；
 * - 30 日柱状分布：纯 CSS 柱条（无图表库），hover 标注日期与计数。
 */

import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { BarChart3 } from 'lucide-react'
import type { SearchDistributionResult } from '../api/types'
import { fetchDistribution, type DistributionParams } from '../lib/search-insight'
import { cx } from './ui/cx'

export function SearchDistributionPanel({
  params,
  activeFeedUrl,
  onSelectSource,
}: {
  /** 与结果区一致的查询参数。 */
  params: DistributionParams
  /** 当前已应用的来源过滤（高亮 + 可点击取消）。 */
  activeFeedUrl: string | null
  onSelectSource: (feedUrl: string | null) => void
}) {
  const enabled = params.q.trim() !== ''
  const distribution = useQuery({
    queryKey: ['search', 'distribution', params],
    queryFn: ({ signal }) => fetchDistribution(params, signal),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })

  const body: SearchDistributionResult | undefined = distribution.data
  const maxDay = body ? Math.max(1, ...body.days.map((d) => d.count)) : 1

  return (
    <div
      data-testid="distribution-panel"
      className="mt-2 flex flex-col gap-2.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      aria-label="来源分布"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <BarChart3 aria-hidden className="size-3.5" />
        来源分布
        {body && (
          <span className="font-normal text-[var(--lumi-text-tertiary)]">
            （共约 {body.total} 条）
          </span>
        )}
      </p>

      {distribution.isPending && <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">统计中…</p>}
      {distribution.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          分布统计失败：{distribution.error instanceof Error ? distribution.error.message : '请稍后重试。'}
        </p>
      )}

      {body && (
        <>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="按来源过滤结果">
            <button
              type="button"
              data-testid="distribution-source-all"
              aria-pressed={activeFeedUrl === null}
              onClick={() => onSelectSource(null)}
              className={cx(
                'min-h-7 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs',
                'transition-colors duration-[var(--lumi-motion-fast)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                activeFeedUrl === null
                  ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                  : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
              )}
            >
              全部来源
            </button>
            {body.sources.map((source) => (
              <button
                key={source.feedUrl}
                type="button"
                data-testid="distribution-source"
                aria-pressed={activeFeedUrl === source.feedUrl}
                onClick={() => onSelectSource(source.feedUrl)}
                title={source.feedUrl}
                className={cx(
                  'flex min-h-7 max-w-56 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs',
                  'transition-colors duration-[var(--lumi-motion-fast)]',
                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  activeFeedUrl === source.feedUrl
                    ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                    : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
                )}
              >
                <span className="truncate">{source.feedTitle || source.feedUrl}</span>
                <span className="shrink-0 tabular-nums opacity-70">{source.count}</span>
              </button>
            ))}
          </div>
          {!body.sourcesComplete && (
            <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
              来源较多，仅显示前 20 个（其余未列出）。
            </p>
          )}

          <div
            data-testid="distribution-days"
            role="img"
            aria-label={`近 30 日分布（${body.dayFrom} 至 ${body.dayTo}）`}
            className="flex h-14 items-end gap-[3px]"
          >
            {body.days.map((day) => (
              <span
                key={day.day}
                title={`${day.day}：${day.count} 条`}
                className={cx(
                  'min-h-[2px] flex-1 rounded-t-[2px]',
                  day.count > 0
                    ? 'bg-[var(--lumi-accent)]'
                    : 'bg-[var(--lumi-border)]',
                )}
                style={day.count > 0 ? { height: `${Math.max(8, Math.round((day.count / maxDay) * 100))}%` } : { height: '2px' }}
              />
            ))}
          </div>
          <p className="flex justify-between text-[10px] text-[var(--lumi-text-tertiary)]">
            <span>{body.dayFrom}</span>
            <span>近 30 日</span>
            <span>{body.dayTo}</span>
          </p>
        </>
      )}
    </div>
  )
}