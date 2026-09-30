/** LanguageGroupsPanel — NEW-369 个人资料语言筛选。
 *
 * 分组只来自明确记录或用户校正（entry 更正 → 源更正 → 来源记录）；
 * 未知语言单独呈现（绝不按界面语言猜测）。点击组 = 展开该组样例
 * refs（父级可据此打开条目）。
 */

import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Languages } from 'lucide-react'
import { fetchLanguageGroups } from '../../api/new361'
import { cx } from '../ui/cx'

export function LanguageGroupsPanel({
  query,
}: {
  query: string
}) {
  const enabled = query.trim() !== ''
  const [expanded, setExpanded] = useState<string | null>(null)
  const groups = useQuery({
    queryKey: ['new369', 'by-language', query],
    queryFn: () => fetchLanguageGroups(query),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
  const body = groups.data

  return (
    <section
      data-testid="n369-language-groups"
      aria-label="语言分组"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <Languages aria-hidden className="size-3.5" />
        语言分组
        {body && (
          <span className="font-normal text-[var(--lumi-text-tertiary)]">
            （命中 {body.total} 条{body.complete ? '' : '，统计截断'}）
          </span>
        )}
      </p>
      {groups.isPending && enabled && (
        <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">
          分组中…
        </p>
      )}
      {groups.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          语言分组失败：{groups.error instanceof Error ? groups.error.message : '请稍后重试。'}
        </p>
      )}
      {body && (
        <>
          <div role="group" aria-label="按语言分组" className="flex flex-wrap gap-1.5">
            {body.groups.map((group) => (
              <button
                key={group.language}
                type="button"
                data-testid="n369-language"
                aria-expanded={expanded === group.language}
                onClick={() => setExpanded(expanded === group.language ? null : group.language)}
                className={cx(
                  'flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs',
                  'transition-colors duration-[var(--lumi-motion-fast)]',
                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  expanded === group.language
                    ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                    : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
                )}
              >
                {group.language}
                <span className="tabular-nums opacity-70">{group.count}</span>
              </button>
            ))}
            {body.groups.length === 0 && body.unknown.count === 0 && (
              <span className="text-xs text-[var(--lumi-text-tertiary)]">没有命中。</span>
            )}
          </div>
          {body.unknown.count > 0 && (
            <button
              type="button"
              data-testid="n369-unknown"
              aria-expanded={expanded === 'unknown'}
              onClick={() => setExpanded(expanded === 'unknown' ? null : 'unknown')}
              className={cx(
                'flex min-h-7 w-fit items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs',
                'border border-dashed border-[var(--lumi-border)] text-[var(--lumi-text-tertiary)]',
                'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              )}
            >
              未知语言（单独呈现）
              <span className="tabular-nums">{body.unknown.count}</span>
            </button>
          )}
          {expanded !== null && (
            <p className="text-xs text-[var(--lumi-text-tertiary)]" data-testid="n369-samples">
              {expanded === 'unknown'
                ? `未知语言样例 ${body.unknown.sampleRefs.length} 条（无任何显式语言记录，不做猜测）`
                : `样例 ${body.groups.find((group) => group.language === expanded)?.sampleRefs.length ?? 0} 条`}
            </p>
          )}
          <p className="text-xs text-[var(--lumi-text-tertiary)]">{body.note}</p>
        </>
      )}
    </section>
  )
}
