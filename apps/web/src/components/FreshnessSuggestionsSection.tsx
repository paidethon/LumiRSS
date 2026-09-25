/** N014 自适应低活跃建议 —— SourcesPage 的建议面板。
 *
 * GET /api/v1/sources/freshness-suggestions（依据 = 派生投影 trailing
 * 8 周：yield 条目/周 + medianGapDays 相邻发布间隔中位数）。接受建议 =
 * 记录 refreshAdvisory=accepted 决定（**纯记录**——FreshRSS greader
 * API 无 per-feed 刷新频率，调度粒度由实例 CRON_MIN 决定）；面板诚实
 * 展示这条边界，并提供 FreshRSS 原生界面入口（P09 native-url）。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Gauge } from 'lucide-react'
import {
  applyFreshnessAdvisory,
  getFreshRssNativeUrl,
  getFreshnessSuggestions,
} from '../api/client'
import { Button } from './ui/Button'
import { Skeleton } from './ui/Skeleton'

export function FreshnessSuggestionsSection() {
  const queryClient = useQueryClient()
  const suggestionsQuery = useQuery({
    queryKey: ['freshness-suggestions'],
    queryFn: () => getFreshnessSuggestions(),
  })
  const nativeUrlQuery = useQuery({
    queryKey: ['freshrss-native-url'],
    queryFn: () => getFreshRssNativeUrl(),
    retry: false,
  })
  const applyMutation = useMutation({
    mutationFn: (feedUrl: string) => applyFreshnessAdvisory(feedUrl),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['freshness-suggestions'] })
    },
  })

  if (suggestionsQuery.isPending) {
    return (
      <section aria-label="低活跃建议" className="flex flex-col gap-1.5">
        <h2 className="px-0.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--lumi-text-tertiary)]">
          低活跃建议
        </h2>
        <Skeleton className="h-16 w-full" />
      </section>
    )
  }
  if (suggestionsQuery.isError) {
    return (
      <section aria-label="低活跃建议" className="flex flex-col gap-1.5">
        <h2 className="px-0.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--lumi-text-tertiary)]">
          低活跃建议
        </h2>
        <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2.5 text-xs text-[var(--lumi-danger)]" role="alert">
          <p>低活跃建议加载失败。</p>
          <Button size="sm" variant="ghost" className="mt-1.5" onClick={() => suggestionsQuery.refetch()}>
            重试
          </Button>
        </div>
      </section>
    )
  }

  const items = suggestionsQuery.data.items
  const nativeOrigin = nativeUrlQuery.data?.origin ?? null

  return (
    <section aria-label="低活跃建议" className="flex flex-col gap-1.5">
      <h2 className="px-0.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--lumi-text-tertiary)]">
        低活跃建议
      </h2>
      {items.length === 0 ? (
        <p className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2.5 text-xs text-[var(--lumi-text-tertiary)]">
          暂无低活跃建议——所有订阅的近 8 周更新节奏都在正常范围。
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {items.map((item) => (
            <li
              key={item.feedUrl}
              className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5"
              data-testid="freshness-suggestion-item"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Gauge aria-hidden className="size-3.5 shrink-0 text-[var(--lumi-accent)]" />
                <span className="min-w-0 flex-1 truncate text-sm text-[var(--lumi-text-primary)]">
                  {item.title}
                </span>
                <span className="shrink-0 rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-accent-soft)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-accent)]">
                  {item.suggested}
                </span>
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-[var(--lumi-text-secondary)]">
                依据：近 {item.basis.weeks} 周每周约 {item.basis.yield} 条；发布间隔中位数约{' '}
                {item.basis.medianGapDays} 天（当前：{item.currentPattern}）。
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
                {suggestionsQuery.data.schedulingNote}
              </p>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                {item.refreshAdvisory === 'accepted' ? (
                  <span
                    role="status"
                    className="text-[11px] text-[var(--lumi-success, var(--lumi-text-primary))]"
                    data-testid="advisory-accepted"
                  >
                    已接受低频建议
                  </span>
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={applyMutation.isPending}
                    onClick={() => applyMutation.mutate(item.feedUrl)}
                  >
                    {applyMutation.isPending ? '记录中…' : '接受建议（记录决定）'}
                  </Button>
                )}
                {nativeOrigin !== null && (
                  <a
                    href={nativeOrigin}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex min-h-11 items-center gap-1 text-[11px] text-[var(--lumi-accent)] underline-offset-2 hover:underline"
                  >
                    <ExternalLink aria-hidden className="size-3" />
                    在 FreshRSS 原生界面调整刷新频率
                  </a>
                )}
              </div>
              {applyMutation.isError && applyMutation.variables === item.feedUrl && (
                <p role="alert" className="mt-1 text-[11px] text-[var(--lumi-danger)]">
                  {applyMutation.error instanceof Error ? applyMutation.error.message : '记录失败'}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
