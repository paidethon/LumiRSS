/** NEW-233 标注汇总阅读页 — 按文章结构汇总本人标注与必要上下文。
 *
 * 每条带「回原段」链接（/reader?entry=…&para=…）；页面绝不渲染第二份
 * 正文——只有引文、批注与回原文定位。 */

import { useQuery } from '@tanstack/react-query'
import { annotationSummary } from '../../api/new231'
import { ANNOTATION_DOT_COLORS } from '../AnnotationsManager'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

export function AnnotationSummarySection({ entryRef }: { entryRef?: string }) {
  const summary = useQuery({
    queryKey: ['new231-annotation-summary', entryRef ?? 'all'],
    queryFn: ({ signal }) => annotationSummary(entryRef, signal),
  })

  return (
    <section aria-label="标注汇总阅读（NEW-233）" className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">标注汇总阅读</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-233</span>
        {summary.data && (
          <span className="ml-auto text-xs text-[var(--lumi-text-secondary)]">
            {summary.data.totalAnnotations} 条标注 · {summary.data.entryCount} 篇
            {summary.data.truncated ? ' · 已截断（仅显示最近 100 篇）' : ''}
          </span>
        )}
      </div>

      {summary.isPending && <Skeleton className="h-16 w-full" />}
      {summary.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">
          汇总加载失败。{summary.error instanceof Error ? summary.error.message : ''}
        </div>
      )}
      {summary.data && summary.data.entries.length === 0 && (
        <EmptyState title="还没有标注" description="在阅读页划选原文即可创建第一批标注。" />
      )}

      {summary.data?.entries.map((entry) => (
        <article key={entry.entryRef} className="flex flex-col gap-1 border-t border-[var(--lumi-border)] pt-2 first:border-t-0 first:pt-0">
          <h4 className="text-sm font-medium text-[var(--lumi-text-primary)]">
            {entry.title || entry.entryRef}
            {entry.source ? <span className="font-normal text-[var(--lumi-text-tertiary)]"> · {entry.source}</span> : null}
          </h4>
          <ul className="flex flex-col gap-1">
            {entry.annotations.map((item) => (
              <li key={item.id} className="flex items-start gap-2 text-xs">
                <span
                  aria-hidden
                  className="mt-1 size-2 shrink-0 rounded-full"
                  style={{ backgroundColor: ANNOTATION_DOT_COLORS[item.color] ?? ANNOTATION_DOT_COLORS.yellow }}
                />
                <div className="min-w-0 flex-1">
                  <p className="text-[var(--lumi-text-primary)]">「{item.excerpt || '（无摘录）'}」</p>
                  {item.note && <p className="text-[var(--lumi-text-secondary)]">{item.note}</p>}
                  {item.stale && <p className="text-[var(--lumi-text-tertiary)]">原文已变化：锚点可能不再准确定位</p>}
                </div>
                <a
                  href={item.backHref}
                  className="shrink-0 text-[var(--lumi-accent)] underline underline-offset-2"
                  aria-label={`回到原段（${item.paraId || '无段落定位'}）`}
                >
                  回原段
                </a>
              </li>
            ))}
          </ul>
        </article>
      ))}
    </section>
  )
}
