/** SearchWhyMissedPanel — N143「为什么没命中」排障面板（SearchPage）。
 *
 * 选一条自己的条目（粘贴 entryRef，或从当前结果里选）→ 服务端对该单
 * 条复跑过滤链 → 逐条列出未通过的 concrete 条件；全部通过 → 诚实说
 * 明「本应命中」，给出按时间排序的位置（rank / rankCapped）。
 * own-scope：他人条目 → 与不存在同一 404，不泄露存在性。
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { SearchX } from 'lucide-react'
import type { SearchItem } from '../api/types'
import { whyMissed, type WhyMissedParams } from '../lib/search-insight'
import { EmptyState } from './ui/EmptyState'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

export function SearchWhyMissedPanel({
  query,
  results,
  filters,
}: {
  /** 当前搜索词（与结果区一致）。 */
  query: string
  /** 当前已加载结果（供「从结果中选」；空结果时只能粘贴 ref）。 */
  results: SearchItem[]
  /** 与结果区相同的过滤条件（面板复跑同一条链）。 */
  filters: Omit<WhyMissedParams, 'query' | 'entryRef'>
}) {
  const [entryRef, setEntryRef] = useState('')
  const [selectedRef, setSelectedRef] = useState<string | null>(null)
  const [submittedRef, setSubmittedRef] = useState<string | null>(null)

  const enabled = submittedRef !== null && query.trim() !== ''
  const detail = useQuery({
    queryKey: ['search', 'why-missed', { query, submittedRef, filters }],
    queryFn: ({ signal }) =>
      whyMissed({ ...filters, query: query.trim(), entryRef: submittedRef! }, signal),
    enabled,
    retry: false,
  })

  const run = (ref: string) => {
    const clean = ref.trim()
    if (clean === '') return
    setSubmittedRef(clean)
  }

  const body = detail.data

  return (
    <div
      data-testid="why-missed-panel"
      className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      role="group"
      aria-label="为什么没命中"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <SearchX aria-hidden className="size-3.5" />
        为什么没命中：对单条条目复跑当前过滤链
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={entryRef}
          onChange={(e) => setEntryRef(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') run(entryRef)
          }}
          placeholder="粘贴 entryRef…"
          aria-label="条目引用（entryRef）"
          className="min-h-7 w-56 min-w-0 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        />
        {results.length > 0 && (
          <select
            value={selectedRef ?? ''}
            onChange={(e) => {
              setSelectedRef(e.target.value === '' ? null : e.target.value)
              if (e.target.value !== '') run(e.target.value)
            }}
            aria-label="从当前结果中选择条目"
            className="min-h-7 max-w-56 min-w-0 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
          >
            <option value="">从当前结果中选择…</option>
            {results.slice(0, 50).map((item) => (
              <option key={item.entryRef} value={item.entryRef}>
                {item.title.slice(0, 40)}
              </option>
            ))}
          </select>
        )}
        <Button size="sm" onClick={() => run(entryRef)} disabled={entryRef.trim() === ''}>
          诊断
        </Button>
      </div>

      {detail.isPending && submittedRef !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          正在诊断…
        </p>
      )}
      {detail.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {detail.error instanceof Error ? detail.error.message : '诊断请求失败。'}
        </p>
      )}
      {body && (
        <div className="flex flex-col gap-1.5" data-testid="why-missed-result">
          <p className="text-xs text-[var(--lumi-text-secondary)]">
            条目「{body.entry.title}」（{body.entry.feedTitle} · {body.entry.publishedAt.slice(0, 10)}）：
          </p>
          {body.matched ? (
            <p className="text-xs text-[var(--lumi-text-primary)]" data-testid="why-missed-matched">
              该条目满足全部条件，本应出现在结果中。
              {body.rank !== null && ` 按时间排序约第 ${body.rank} 条。`}
              {body.rank === null && body.rankCapped && ' 匹配超过 2000 条，未能定位其精确位置。'}
              {body.rank === null && !body.rankCapped && ' 未能在当前索引排序中定位（可能索引正在更新）。'}
            </p>
          ) : (
            <ul className="flex flex-col gap-1" aria-label="排除原因">
              {body.reasons.map((reason, index) => (
                <li
                  key={`${reason.kind}-${index}`}
                  className={cx(
                    'rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] px-2 py-1 text-xs',
                    'text-[var(--lumi-text-secondary)]',
                  )}
                >
                  {reason.detail}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {query.trim() === '' && (
        <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">
          需要先输入搜索词（诊断针对当前查询与过滤链）。
        </p>
      )}
      {submittedRef === null && query.trim() !== '' && (
        <EmptyState
          icon={<SearchX aria-hidden className="size-6" />}
          title="选择或粘贴一条条目引用"
          description="诊断只对当前账户自己的条目有效（他人条目与不存在的引用同样返回 404，不泄露存在性）。"
        />
      )}
    </div>
  )
}
