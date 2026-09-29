/** AuthorSourceFacetsPanel — NEW-364 作者与来源交叉筛选。
 *
 * facet 计数全部是真实命中（BFF 同链聚合）：作者计数不含当前作者
 * 过滤、来源计数不含当前来源过滤——每个数字 = 勾选该项后组合的真实
 * 命中数。点击 = 交给父级应用到 /search 的 author / feedUrl。
 */

import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Users } from 'lucide-react'
import { fetchAuthorSourceFacets } from '../../api/new361'
import { cx } from '../ui/cx'

export function AuthorSourceFacetsPanel({
  query,
  activeAuthor,
  activeFeedUrl,
  onSelectAuthor,
  onSelectFeedUrl,
}: {
  query: string
  activeAuthor: string | null
  activeFeedUrl: string | null
  onSelectAuthor: (author: string | null) => void
  onSelectFeedUrl: (feedUrl: string | null) => void
}) {
  const enabled = query.trim() !== ''
  const facets = useQuery({
    queryKey: ['new364', 'author-source', query, activeAuthor, activeFeedUrl],
    queryFn: () =>
      fetchAuthorSourceFacets({ q: query, author: activeAuthor, feedUrl: activeFeedUrl }),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
  const body = facets.data

  return (
    <section
      data-testid="n364-author-source"
      aria-label="作者与来源交叉筛选"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <Users aria-hidden className="size-3.5" />
        作者与来源交叉筛选
        {body && (
          <span className="font-normal text-[var(--lumi-text-tertiary)]">
            （当前组合实际命中 {body.total} 条）
          </span>
        )}
      </p>
      {facets.isPending && enabled && (
        <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">
          统计中…
        </p>
      )}
      {facets.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          facet 统计失败：{facets.error instanceof Error ? facets.error.message : '请稍后重试。'}
        </p>
      )}
      {body && (
        <>
          <div role="group" aria-label="按作者过滤" className="flex flex-wrap gap-1.5">
            {body.authors.map((facet) => (
              <button
                key={facet.author}
                type="button"
                data-testid="n364-author"
                aria-pressed={activeAuthor === facet.author}
                onClick={() => onSelectAuthor(activeAuthor === facet.author ? null : facet.author)}
                className={cx(
                  'flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs',
                  'transition-colors duration-[var(--lumi-motion-fast)]',
                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  activeAuthor === facet.author
                    ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                    : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
                )}
              >
                <span className="max-w-40 truncate">{facet.author}</span>
                <span className="shrink-0 tabular-nums opacity-70">{facet.count}</span>
              </button>
            ))}
            {body.authors.length === 0 && (
              <span className="text-xs text-[var(--lumi-text-tertiary)]">没有可筛的作者。</span>
            )}
          </div>
          <div role="group" aria-label="按来源过滤" className="flex flex-wrap gap-1.5">
            {body.sources.map((facet) => (
              <button
                key={facet.feedUrl}
                type="button"
                data-testid="n364-source"
                aria-pressed={activeFeedUrl === facet.feedUrl}
                onClick={() => onSelectFeedUrl(activeFeedUrl === facet.feedUrl ? null : facet.feedUrl)}
                title={facet.feedUrl}
                className={cx(
                  'flex min-h-7 max-w-56 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs',
                  'transition-colors duration-[var(--lumi-motion-fast)]',
                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  activeFeedUrl === facet.feedUrl
                    ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                    : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
                )}
              >
                <span className="truncate">{facet.feedTitle || facet.feedUrl}</span>
                <span className="shrink-0 tabular-nums opacity-70">{facet.count}</span>
              </button>
            ))}
          </div>
          {(!body.authorsComplete || !body.sourcesComplete) && (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              候选较多，仅显示前 20 个。
            </p>
          )}
        </>
      )}
    </section>
  )
}
