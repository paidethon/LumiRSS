/** SearchTimelinePanel — N149 主题演变时间线（SearchPage 面板）。
 *
 * 与结果区同参（同 query + 过滤链 + 权限作用域）拉取：
 * - 24 个月逐月计数柱状（纯 CSS，无图表库；hover 标注月份与计数）；
 * - 匹配查询的本人批注卡片（≤10 条 + 超界诚实标注）；
 * - 批注可手动排除：排除列表存本设备（localStorage），变更后触发
 *   时间线 refetch，重渲后排除即生效（可一键清空恢复）。
 */

import { useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { LineChart, X } from 'lucide-react'
import type { SearchTimelineResult } from '../api/types'
import { fetchSearchTimeline, type DistributionParams } from '../lib/search-insight'
import {
  clearExcludedAnnotations,
  excludeAnnotation,
  readExcludedAnnotationIds,
} from '../lib/search-timeline-exclusions'
import type { AnnotationColor } from '../lib/annotations'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

/** 与 AnnotationsLayer COLOR_DOT 同口径（内容标注语义色）。 */
const ANNOTATION_DOT: Record<AnnotationColor, string> = {
  yellow: '#eab308',
  green: '#65a30d',
  pink: '#ec4899',
}

function annotationDot(color: string): string {
  return ANNOTATION_DOT[color as AnnotationColor] ?? 'var(--lumi-accent)'
}

export function SearchTimelinePanel({
  params,
}: {
  params: DistributionParams
}) {
  const enabled = params.q.trim() !== ''
  const queryClient = useQueryClient()
  // excluded 进 state：排除后立即重渲（同时 refetch 兑现「排除 refetch」）。
  const [excluded, setExcluded] = useState<string[]>(() => readExcludedAnnotationIds())

  const timeline = useQuery({
    queryKey: ['search', 'timeline', params],
    queryFn: ({ signal }) => fetchSearchTimeline(params, signal),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })

  const excludeOne = (id: string) => {
    setExcluded(excludeAnnotation(id))
    void queryClient.invalidateQueries({ queryKey: ['search', 'timeline'] })
  }
  const clearAll = () => {
    clearExcludedAnnotations()
    setExcluded([])
    void queryClient.invalidateQueries({ queryKey: ['search', 'timeline'] })
  }

  const body: SearchTimelineResult | undefined = timeline.data
  const maxCount = body ? Math.max(1, ...body.months.map((m) => m.count)) : 1
  const visibleAnnotations =
    body?.annotations.filter((a) => !excluded.includes(a.id)) ?? []
  const hiddenCount = excluded.length

  return (
    <div
      data-testid="timeline-panel"
      className="mt-2 flex flex-col gap-2.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      aria-label="主题演变时间线"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <LineChart aria-hidden className="size-3.5" />
        主题演变（24 个月）
        {body && (
          <span className="font-normal text-[var(--lumi-text-tertiary)]">
            （窗口内共 {body.total} 条）
          </span>
        )}
      </p>

      {timeline.isPending && (
        <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">统计中…</p>
      )}
      {timeline.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          时间线统计失败：{timeline.error instanceof Error ? timeline.error.message : '请稍后重试。'}
        </p>
      )}

      {body && (
        <>
          <div
            data-testid="timeline-months"
            role="img"
            aria-label={`24 个月演变（${body.monthFrom} 至 ${body.monthTo}）`}
            className="flex h-16 items-end gap-[3px]"
          >
            {body.months.map((month) => (
              <span
                key={month.month}
                title={`${month.month}：${month.count} 条`}
                className={cx(
                  'min-h-[2px] flex-1 rounded-t-[2px]',
                  month.count > 0
                    ? 'bg-[var(--lumi-accent)]'
                    : 'bg-[var(--lumi-border)]',
                )}
                style={
                  month.count > 0
                    ? { height: `${Math.max(8, Math.round((month.count / maxCount) * 100))}%` }
                    : { height: '2px' }
                }
              />
            ))}
          </div>
          <p className="flex justify-between text-[10px] text-[var(--lumi-text-tertiary)]">
            <span>{body.monthFrom}</span>
            <span>近 24 个月</span>
            <span>{body.monthTo}</span>
          </p>
          {!body.annotationsComplete && (
            <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
              匹配批注较多，仅显示最近 10 条。
            </p>
          )}
        </>
      )}

      {/* 本人批注卡片（排除后 refetch 重渲即隐藏） */}
      {body && (
        <ul className="flex flex-col gap-1.5" aria-label="相关批注">
          {visibleAnnotations.map((annotation) => (
            <li
              key={annotation.id}
              data-testid="timeline-annotation"
              className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2"
            >
              <span
                aria-hidden
                className="mt-1 size-2 shrink-0 rounded-full"
                style={{ backgroundColor: annotationDot(annotation.color) }}
              />
              <span className="min-w-0 flex-1">
                {annotation.excerpt !== '' && (
                  <span className="line-clamp-2 block text-xs text-[var(--lumi-text-primary)]">
                    {annotation.excerpt}
                  </span>
                )}
                {annotation.note !== '' && (
                  <span className="mt-0.5 line-clamp-2 block text-[11px] text-[var(--lumi-text-secondary)]">
                    {annotation.note}
                  </span>
                )}
              </span>
              <button
                type="button"
                aria-label={`隐藏批注「${annotation.excerpt || annotation.note}」`}
                onClick={() => excludeOne(annotation.id)}
                className="relative flex size-6 shrink-0 items-center justify-center rounded-full text-[var(--lumi-text-tertiary)] transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                <X aria-hidden className="size-3" />
              </button>
            </li>
          ))}
          {visibleAnnotations.length === 0 && !timeline.isPending && (
            <li className="text-xs text-[var(--lumi-text-tertiary)]" role="status">
              没有匹配「{params.q}」的批注。
            </li>
          )}
        </ul>
      )}

      {hiddenCount > 0 && (
        <p className="flex items-center gap-2 text-[11px] text-[var(--lumi-text-tertiary)]">
          已隐藏 {hiddenCount} 条批注（仅本设备生效）。
          <Button variant="ghost" size="sm" onClick={clearAll}>
            恢复显示
          </Button>
        </p>
      )}
    </div>
  )
}
